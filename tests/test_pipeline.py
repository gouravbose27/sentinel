import asyncio

import httpx
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.ado.client import AdoClient
from app.config import Settings
from app.main import create_app
from app.models.schemas import Category, JobStatus, LLMFinding, LLMReview, ReviewJob, ReviewRequest
from app.review.orchestrator import run_review

HEAD_SRC = "def f(x, acc=[]):\n    acc.append(x)\n    return acc\n"


def ado_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/pullrequests/7"):
        return httpx.Response(200, json={
            "title": "Fix things", "description": "d", "createdBy": {"displayName": "Ada"},
            "sourceRefName": "refs/heads/feat", "targetRefName": "refs/heads/main",
        })
    if path.endswith("/iterations"):
        return httpx.Response(200, json={"value": [
            {"id": 1, "sourceRefCommit": {"commitId": "h"}, "commonRefCommit": {"commitId": "b"}}
        ]})
    if path.endswith("/changes"):
        return httpx.Response(200, json={"changeEntries": [
            {"changeType": "add", "item": {"path": "/src/job.py"}},
            {"changeType": "edit", "item": {"path": "/README.md"}},
        ]})
    if path.endswith("/items"):
        return httpx.Response(200, text=HEAD_SRC)
    return httpx.Response(404)


class FakeLLM:
    async def parse(self, *, system, user, schema):
        assert "<diff>" in user and "mutable" in system
        return LLMReview(findings=[
            LLMFinding(severity="high", confidence=0.9, line_start=1, line_end=1, title="Mutable default",
                       description="Shared list.", suggestion="acc=None", references=[]),
            LLMFinding(severity="low", confidence=0.1, line_start=99, line_end=None, title="Weak",
                       description="x", suggestion=None, references=[]),
        ])


def test_review_pipeline_end_to_end():
    settings = Settings(openai_api_key=SecretStr("k"), ado_pat=SecretStr("p"))
    job = ReviewJob(request=ReviewRequest(org="o", project="p", repo="r", pr_id=7, categories=[Category.BUG]))

    async def go():
        http = httpx.AsyncClient(transport=httpx.MockTransport(ado_handler))
        async with AdoClient("o", "p", http=http) as ado:
            await run_review(job, ado=ado, llm=FakeLLM(), settings=settings)

    asyncio.run(go())
    assert job.status is JobStatus.DONE
    assert job.pr_title == "Fix things"
    assert [s.path for s in job.skipped] == ["/README.md"]
    assert len(job.findings) == 1  # low-confidence finding filtered out
    assert job.findings[0].line_start == 1 and job.findings[0].file == "/src/job.py"


def test_prompt_is_scoped_to_selected_category():
    seen: list[str] = []

    class SpyLLM:
        async def parse(self, *, system, user, schema):
            seen.append(system)
            return LLMReview(findings=[])

    settings = Settings(openai_api_key=SecretStr("k"), ado_pat=SecretStr("p"))
    job = ReviewJob(request=ReviewRequest(org="o", project="p", repo="r", pr_id=7, categories=[Category.BUG]))

    async def go():
        http = httpx.AsyncClient(transport=httpx.MockTransport(ado_handler))
        async with AdoClient("o", "p", http=http) as ado:
            await run_review(job, ado=ado, llm=SpyLLM(), settings=settings)

    asyncio.run(go())
    assert seen and all("report only bug findings" in s for s in seen)


def test_closed_pr_never_reaches_llm():
    class ExplodingLLM:
        async def parse(self, **kwargs):
            raise AssertionError("LLM must not be called for a closed PR")

    settings = Settings(openai_api_key=SecretStr("k"), ado_pat=SecretStr("p"))

    for state in ("completed", "abandoned"):
        def handler(request: httpx.Request, state=state) -> httpx.Response:
            if request.url.path.endswith("/pullrequests/7"):
                return httpx.Response(200, json={"title": "t", "status": state})
            return httpx.Response(404)

        job = ReviewJob(request=ReviewRequest(org="o", project="p", repo="r", pr_id=7, categories=[Category.BUG]))

        async def go():
            http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            async with AdoClient("o", "p", http=http) as ado:
                await run_review(job, ado=ado, llm=ExplodingLLM(), settings=settings)

        asyncio.run(go())
        assert job.status is JobStatus.FAILED
        assert state in (job.message or "") or any(state in e for e in job.errors)


def test_pages_render():
    client = TestClient(create_app(Settings(openai_api_key=SecretStr(""), ado_pat=SecretStr(""))))
    assert client.get("/health").json() == {"status": "ok"}
    page = client.get("/")
    assert page.status_code == 200 and "Initiate review" in page.text
    assert "default-src 'self'" in page.headers["content-security-policy"]


def test_form_validation_and_missing_config():
    client = TestClient(create_app(Settings(openai_api_key=SecretStr(""), ado_pat=SecretStr(""))))
    resp = client.post("/reviews", data={"org": "o", "project": "p", "repo": "r", "pr_id": "abc"})
    assert resp.status_code == 422
    assert "OPENAI_API_KEY" in resp.text and "positive whole number" in resp.text


def test_unknown_job_is_404():
    client = TestClient(create_app(Settings()))
    assert client.get("/reviews/nope").status_code == 404
