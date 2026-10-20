import asyncio
import logging
from typing import Any
from urllib.parse import quote

import httpx

log = logging.getLogger(__name__)

API_VERSION = "7.1"
HOST = "https://dev.azure.com"
MAX_ATTEMPTS = 3
RETRYABLE = {429, 500, 502, 503, 504}


class AdoError(Exception):
    """Azure DevOps request failed; message is safe to show to the user."""


class AdoClient:
    def __init__(self, org: str, pat: str, *, http: httpx.AsyncClient | None = None) -> None:
        self._org = org
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(
            auth=("", pat), timeout=30, headers={"Accept": "application/json"}
        )

    async def __aenter__(self) -> "AdoClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._owns_http:
            await self._http.aclose()

    @staticmethod
    def _backoff(attempt: int, retry_after: str | None) -> float:
        if retry_after and retry_after.isdigit():
            return min(int(retry_after), 30)
        return 0.5 * 2 ** (attempt - 1)

    def _repo_url(self, project: str, repo: str) -> str:
        q = lambda s: quote(s, safe="")  # noqa: E731
        return f"{HOST}/{q(self._org)}/{q(project)}/_apis/git/repositories/{q(repo)}"

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        allow_404: bool = False,
    ) -> httpx.Response | None:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                resp = await self._http.request(
                    method, url, params={"api-version": API_VERSION, **(params or {})}, json=json
                )
            except httpx.HTTPError as exc:
                if attempt < MAX_ATTEMPTS:
                    await asyncio.sleep(self._backoff(attempt, None))
                    continue
                log.warning("Azure DevOps request failed: %s", type(exc).__name__)
                raise AdoError("Could not reach Azure DevOps.") from exc
            if resp.status_code in RETRYABLE and attempt < MAX_ATTEMPTS:
                await asyncio.sleep(self._backoff(attempt, resp.headers.get("Retry-After")))
                continue
            break

        status = resp.status_code
        if status == 404 and allow_404:
            return None
        # Azure DevOps answers a bad PAT with 401, 203 or a redirect to the sign-in page.
        if status in (401, 203, 302):
            raise AdoError("Azure DevOps rejected the credentials. Check ADO_PAT.")
        if status == 403:
            raise AdoError("The PAT lacks permission for this operation.")
        if status == 404:
            raise AdoError("Pull request or repository not found. Check organization, project, repo and PR number.")
        if status >= 400:
            raise AdoError(f"Azure DevOps returned HTTP {status}.")
        return resp

    async def get_pull_request(self, project: str, repo: str, pr_id: int) -> dict[str, Any]:
        resp = await self._request("GET", f"{self._repo_url(project, repo)}/pullrequests/{pr_id}")
        return resp.json()  # type: ignore[union-attr]

    async def get_latest_iteration(self, project: str, repo: str, pr_id: int) -> dict[str, Any]:
        resp = await self._request(
            "GET", f"{self._repo_url(project, repo)}/pullrequests/{pr_id}/iterations"
        )
        iterations = resp.json().get("value", [])  # type: ignore[union-attr]
        if not iterations:
            raise AdoError("The pull request has no iterations yet.")
        return max(iterations, key=lambda i: i["id"])

    async def get_changes(
        self, project: str, repo: str, pr_id: int, iteration_id: int
    ) -> list[dict[str, Any]]:
        url = f"{self._repo_url(project, repo)}/pullrequests/{pr_id}/iterations/{iteration_id}/changes"
        entries: list[dict[str, Any]] = []
        skip = 0
        while True:
            resp = await self._request("GET", url, params={"$top": 500, "$skip": skip})
            data = resp.json()  # type: ignore[union-attr]
            entries.extend(data.get("changeEntries", []))
            next_skip = data.get("nextSkip") or 0
            if next_skip <= skip:
                return entries
            skip = next_skip

    async def get_file_text(self, project: str, repo: str, path: str, commit_id: str) -> str | None:
        resp = await self._request(
            "GET",
            f"{self._repo_url(project, repo)}/items",
            params={
                "path": path,
                "versionDescriptor.version": commit_id,
                "versionDescriptor.versionType": "commit",
                "$format": "text",
            },
            allow_404=True,
        )
        return None if resp is None else resp.text

    async def list_threads(self, project: str, repo: str, pr_id: int) -> list[dict[str, Any]]:
        resp = await self._request(
            "GET", f"{self._repo_url(project, repo)}/pullrequests/{pr_id}/threads"
        )
        return resp.json().get("value", [])  # type: ignore[union-attr]

    async def create_thread(
        self,
        project: str,
        repo: str,
        pr_id: int,
        content: str,
        *,
        file_path: str | None = None,
        line_start: int | None = None,
        line_end: int | None = None,
    ) -> None:
        body: dict[str, Any] = {
            "comments": [{"parentCommentId": 0, "content": content, "commentType": 1}],
            "status": 1,
        }
        if file_path:
            context: dict[str, Any] = {"filePath": file_path}
            if line_start:
                context["rightFileStart"] = {"line": line_start, "offset": 1}
                context["rightFileEnd"] = {"line": line_end or line_start, "offset": 2}
            body["threadContext"] = context
        await self._request(
            "POST", f"{self._repo_url(project, repo)}/pullrequests/{pr_id}/threads", json=body
        )

    async def create_status(
        self, project: str, repo: str, pr_id: int, *, state: str, description: str
    ) -> None:
        """state: pending, succeeded, failed or error. Needs the Code (Status) PAT scope."""
        body = {
            "state": state,
            "description": description[:400],
            "context": {"name": "ai-review", "genre": "sentinel"},
        }
        await self._request(
            "POST", f"{self._repo_url(project, repo)}/pullrequests/{pr_id}/statuses", json=body
        )
