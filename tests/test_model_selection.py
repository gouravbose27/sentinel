from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.main import create_app
import app.web.routes as routes

FORM = {"org": "org", "project": "Proj", "repo": "repo", "pr_id": "7", "categories": ["bug"]}


def make_client() -> TestClient:
    settings = Settings(
        ado_org="org", openai_api_key=SecretStr("k"), ado_pat=SecretStr("p"),
        openai_model="gpt-4o", openai_models="gpt-4o-mini",
    )
    return TestClient(create_app(settings))


def test_available_models_include_default_first():
    s = Settings(openai_model="gpt-4o", openai_models="gpt-4o-mini, gpt-4o,")
    assert s.available_models == ["gpt-4o", "gpt-4o-mini"]


def test_index_lists_models():
    html = make_client().get("/").text
    assert 'value="gpt-4o-mini"' in html


def test_unlisted_model_rejected():
    resp = make_client().post("/reviews", data={**FORM, "model": "evil-model"})
    assert resp.status_code == 422


def test_selected_model_reaches_job(monkeypatch):
    seen = []

    async def fake_execute(job, settings, **kw):
        seen.append(job.request.model)

    monkeypatch.setattr(routes, "execute_job", fake_execute)
    resp = make_client().post("/reviews", data={**FORM, "model": "gpt-4o-mini"}, follow_redirects=False)
    assert resp.status_code == 303
    assert seen == ["gpt-4o-mini"]
