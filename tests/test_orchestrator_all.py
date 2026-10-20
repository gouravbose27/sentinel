import asyncio

import httpx
from pydantic import SecretStr

from app.ado.client import AdoClient
from app.config import Settings
from app.models.schemas import Category, JobStatus, LLMFinding, LLMReview, ReviewJob, ReviewRequest
from app.review.osv import OsvClient
from app.review.orchestrator import run_review
from app.review.reviewers import REVIEWERS
from app.review.reviewers.dependencies import DependencyReviewer

FILES = {
    "/src/job.py": "import os\n\n\ndef load(path):\n    return eval(open(path).read())\n",
    "/tests/test_job.py": "def test_x():\n    assert True\n",
    "/requirements.txt": "requests==2.0.0\n",
}


def ado_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/pullrequests/9"):
        return httpx.Response(200, json={"title": "t", "sourceRefName": "refs/heads/a", "targetRefName": "refs/heads/b"})
    if path.endswith("/iterations"):
        return httpx.Response(200, json={"value": [
            {"id": 1, "sourceRefCommit": {"commitId": "h"}, "commonRefCommit": {"commitId": "b"}}]})
    if path.endswith("/changes"):
        return httpx.Response(200, json={"changeEntries": [
            {"changeType": "add", "item": {"path": p}} for p in FILES]})
    if path.endswith("/items"):
        return httpx.Response(200, text=FILES[request.url.params["path"]])
    return httpx.Response(404)


def osv_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/querybatch"):
        return httpx.Response(200, json={"results": [{"vulns": [{"id": "PYSEC-1"}]}]})
    return httpx.Response(200, json={"id": "PYSEC-1", "summary": "bad"})


class CountingLLM:
    def __init__(self):
        self.calls = []

    async def parse(self, *, system, user, schema):
        self.calls.append(user)
        return LLMReview(findings=[LLMFinding(
            severity="medium", confidence=0.8, line_start=5, line_end=5, title="LLM finding",
            description="x", suggestion=None, references=[])])


def test_all_reviewers_run_and_respect_file_types():
    registry = dict(REVIEWERS)
    registry[Category.DEPENDENCY] = DependencyReviewer(
        OsvClient(httpx.AsyncClient(transport=httpx.MockTransport(osv_handler))))
    llm = CountingLLM()
    job = ReviewJob(request=ReviewRequest(
        org="o", project="p", repo="r", pr_id=9, categories=list(Category)))

    async def go():
        http = httpx.AsyncClient(transport=httpx.MockTransport(ado_handler))
        async with AdoClient("o", "p", http=http) as ado:
            await run_review(job, ado=ado, llm=llm, settings=Settings(ado_pat=SecretStr("p")), reviewers=registry)

    asyncio.run(go())
    assert job.status is JobStatus.DONE, job.message
    # job.py: bug, test, security, optimization = 4 LLM calls; the test file only gets bug/security/optimization
    assert len(llm.calls) == 4 + 3
    assert all("requests==" not in call for call in llm.calls)
    by_category = {f.category for f in job.findings}
    assert by_category == set(Category)
    assert any(f.title == "Use of eval/exec" and f.line_start == 5 for f in job.findings)
    assert any("known vulnerabilit" in f.title for f in job.findings)
    assert not any(f.category is Category.TEST and f.file == "/tests/test_job.py" for f in job.findings)
