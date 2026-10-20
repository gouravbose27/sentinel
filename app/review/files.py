import asyncio
import re

from app.ado.client import AdoClient, AdoError
from app.config import Settings
from app.models.schemas import ChangedFile, PRContext, ReviewRequest, SkippedFile
from app.review.dependencies import manifest_kind

_IGNORED_PARTS = ("/node_modules/", "/.venv/", "/venv/", "/site-packages/", "/vendor/", "/__pycache__/")
_GENERATED = ("_pb2.py", "_pb2_grpc.py", ".min.")
_PYSPARK_RE = re.compile(r"\b(pyspark|SparkSession|spark\.(sql|read|table|createDataFrame)|DataFrame)\b")
_SPARKSQL_RE = re.compile(
    r"\b(USING\s+(DELTA|PARQUET)|OPTIMIZE|ZORDER|LATERAL\s+VIEW|CLUSTER\s+BY|DISTRIBUTE\s+BY|"
    r"TBLPROPERTIES|PARTITIONED\s+BY|MERGE\s+INTO|explode\s*\(|CREATE\s+OR\s+REPLACE\s+TEMP)",
    re.IGNORECASE,
)


def classify(path: str, content: str) -> str | None:
    """Return a language label for reviewable files, or None."""
    lower = path.lower()
    if manifest_kind(path):
        return "manifest"
    if lower.endswith(".py"):
        return "pyspark" if _PYSPARK_RE.search(content) else "python"
    if lower.endswith(".sql"):
        return "sparksql" if _SPARKSQL_RE.search(content) else "sql"
    return None


def skip_reason(path: str) -> str | None:
    lower = path.lower()
    if any(part in lower for part in _IGNORED_PARTS):
        return "vendored or environment path"
    if any(marker in lower for marker in _GENERATED):
        return "generated file"
    if not lower.endswith((".py", ".sql")) and not manifest_kind(path):
        return "unsupported file type"
    return None


async def collect_pull_request(
    ado: AdoClient, request: ReviewRequest, settings: Settings
) -> PRContext:
    project, repo, pr_id = request.project, request.repo, request.pr_id
    pr = await ado.get_pull_request(project, repo, pr_id)
    pr_status = str(pr.get("status", "active")).lower()
    if pr_status != "active":
        raise AdoError(f"Pull request {pr_id} is {pr_status}; only active pull requests can be reviewed.")
    iteration = await ado.get_latest_iteration(project, repo, pr_id)
    head_commit = iteration["sourceRefCommit"]["commitId"]
    base_commit = iteration["commonRefCommit"]["commitId"]
    entries = await ado.get_changes(project, repo, pr_id, iteration["id"])

    skipped: list[SkippedFile] = []
    candidates: list[tuple[str, str, str]] = []  # (path, base_path, change_type)
    for entry in entries:
        item = entry.get("item") or {}
        path = item.get("path")
        if not path or item.get("isFolder"):
            continue
        change_type = str(entry.get("changeType", "edit")).lower()
        if "delete" in change_type:
            skipped.append(SkippedFile(path=path, reason="deleted"))
        elif (reason := skip_reason(path)) is not None:
            skipped.append(SkippedFile(path=path, reason=reason))
        elif len(candidates) >= settings.max_files:
            skipped.append(SkippedFile(path=path, reason=f"over the {settings.max_files}-file limit"))
        else:
            candidates.append((path, entry.get("originalPath") or path, change_type))

    sem = asyncio.Semaphore(8)

    async def fetch(path: str, base_path: str, change_type: str) -> ChangedFile | SkippedFile:
        async with sem:
            head = await ado.get_file_text(project, repo, path, head_commit)
            if head is None:
                return SkippedFile(path=path, reason="content unavailable")
            if len(head) > settings.max_file_chars:
                return SkippedFile(path=path, reason="file too large")
            base = ""
            if "add" not in change_type:
                base = await ado.get_file_text(project, repo, base_path, base_commit) or ""
        language = classify(path, head)
        assert language is not None  # extension already vetted by skip_reason
        return ChangedFile(path, change_type, language, base, head)

    files: list[ChangedFile] = []
    for result in await asyncio.gather(*(fetch(*c) for c in candidates)):
        if isinstance(result, SkippedFile):
            skipped.append(result)
        elif result.base_content != result.head_content:
            files.append(result)

    return PRContext(
        title=pr.get("title", ""),
        description=pr.get("description") or "",
        author=(pr.get("createdBy") or {}).get("displayName", ""),
        source_branch=str(pr.get("sourceRefName", "")).removeprefix("refs/heads/"),
        target_branch=str(pr.get("targetRefName", "")).removeprefix("refs/heads/"),
        files=files,
        skipped=skipped,
    )
