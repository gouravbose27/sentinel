import asyncio
from base64 import b64encode

import httpx
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.ado.client import AdoClient, AdoError
from app.config import Settings
from app.main import create_app
from app.models.schemas import Category, Finding, ReviewJob, ReviewRequest, Severity
from app.review.publisher import publish
import app.web.webhook as webhook

EVENT = {
    "eventType": "git.pullrequest.updated",
    "resource": {
        "pullRequestId": 7, "status": "active",
        "repository": {"name": "repo", "project": {"name": "Proj"}},
        "lastMergeSourceCommit": {"commitId": "abc"},
    },
}


def make_client(**kw) -> TestClient:
    settings = Settings(ado_org="org", webhook_secret=SecretStr("s3cret"), **kw)
    return TestClient(create_app(settings))


def test_webhook_disabled_without_secret():
    client = TestClient(create_app(Settings(ado_org="org")))
    assert client.post("/webhooks/ado", json=EVENT).status_code == 404


def test_webhook_requires_secret_and_dedupes(monkeypatch):
    started = []

    async def fake_execute(job, settings, **kw):
        started.append(job.request.pr_id)

    monkeypatch.setattr(webhook, "execute_job", fake_execute)
    client = make_client()
    assert client.post("/webhooks/ado", json=EVENT).status_code == 401
    assert client.post("/webhooks/ado", json=EVENT, headers={"X-Webhook-Secret": "nope"}).status_code == 401

    ok = client.post("/webhooks/ado", json=EVENT, headers={"X-Webhook-Secret": "s3cret"})
    assert ok.status_code == 202 and ok.json()["status"] == "accepted"
    again = client.post("/webhooks/ado", json=EVENT, headers={"X-Webhook-Secret": "s3cret"})
    assert again.json()["reason"] == "already reviewed this commit"

    basic = {"Authorization": "Basic " + b64encode(b"hook:s3cret").decode()}
    other = {**EVENT, "resource": {**EVENT["resource"], "lastMergeSourceCommit": {"commitId": "def"}}}
    assert client.post("/webhooks/ado", json=other, headers=basic).status_code == 202
    assert started == [7, 7]


def test_webhook_ignores_drafts_and_other_events():
    client = make_client()
    h = {"X-Webhook-Secret": "s3cret"}
    draft = {**EVENT, "resource": {**EVENT["resource"], "isDraft": True}}
    assert client.post("/webhooks/ado", json=draft, headers=h).json()["status"] == "ignored"
    assert client.post("/webhooks/ado", json={"eventType": "build.complete"}, headers=h).json()["status"] == "ignored"


def test_ui_password_and_origin_check():
    client = TestClient(create_app(Settings(ui_password=SecretStr("pw"))))
    assert client.get("/").status_code == 401
    assert client.get("/health").status_code == 200
    auth = {"Authorization": "Basic " + b64encode(b"me:pw").decode()}
    assert client.get("/", headers=auth).status_code == 200
    evil = client.post("/reviews", data={}, headers={**auth, "Origin": "https://evil.example"})
    assert evil.status_code == 403


def test_ado_client_retries_transient_errors(monkeypatch):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503 if len(calls) < 3 else 200, json={"title": "ok"})

    async def no_sleep(_):
        return None

    monkeypatch.setattr("app.ado.client.asyncio.sleep", no_sleep)

    async def go():
        async with AdoClient("o", "p", http=httpx.AsyncClient(transport=httpx.MockTransport(handler))) as ado:
            return await ado.get_pull_request("p", "r", 1)

    assert asyncio.run(go()) == {"title": "ok"}
    assert len(calls) == 3


def test_publish_skips_existing_threads_and_posts_summary():
    job = ReviewJob(request=ReviewRequest(org="o", project="p", repo="r", pr_id=1, categories=[Category.BUG]))
    new = Finding(category=Category.BUG, severity=Severity.HIGH, confidence=0.9, file="/a.py",
                  line_start=3, title="New", description="d", suggestion="x = 1")
    old = Finding(category=Category.BUG, severity=Severity.LOW, confidence=0.9, file="/a.py",
                  line_start=9, title="Old", description="d")
    job.findings = [new, old]
    posted = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            marker = f"<!-- ai-pr-review:{old.fingerprint} -->"
            return httpx.Response(200, json={"value": [{"comments": [{"content": marker}]}]})
        posted.append(request.content.decode())
        return httpx.Response(200, json={})

    async def go():
        async with AdoClient("o", "p", http=httpx.AsyncClient(transport=httpx.MockTransport(handler))) as ado:
            return await publish(ado, job, [new.id, old.id])

    result = asyncio.run(go())
    assert (result.posted, result.duplicates, result.failed) == (1, 1, 0)
    assert len(posted) == 2  # the finding thread plus the summary
    assert '"line":3' in posted[0].replace(" ", "") and "x = 1" in posted[0]
