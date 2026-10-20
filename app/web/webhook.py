import hmac
from base64 import b64decode

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from app.config import Settings
from app.models.schemas import ReviewJob, ReviewRequest
from app.review.runner import execute_job

router = APIRouter()

EVENTS = {"git.pullrequest.created", "git.pullrequest.updated"}


def _authorized(request: Request, secret: str) -> bool:
    """Accepts the secret as X-Webhook-Secret or as the Basic-auth password."""
    supplied = request.headers.get("x-webhook-secret", "")
    auth = request.headers.get("authorization", "")
    if not supplied and auth.lower().startswith("basic "):
        try:
            supplied = b64decode(auth[6:]).decode().partition(":")[2]
        except ValueError:
            supplied = ""
    return hmac.compare_digest(supplied.encode(), secret.encode())


@router.post("/webhooks/ado", status_code=202)
async def ado_webhook(request: Request) -> dict[str, str]:
    settings: Settings = request.app.state.settings
    secret = settings.webhook_secret.get_secret_value()
    if not secret or not settings.ado_org:
        raise HTTPException(status_code=404)
    if not _authorized(request, secret):
        raise HTTPException(status_code=401)

    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    if not isinstance(payload, dict) or payload.get("eventType") not in EVENTS:
        return {"status": "ignored", "reason": "unsupported event"}

    resource = payload.get("resource") or {}
    if resource.get("isDraft") or resource.get("status", "active") != "active":
        return {"status": "ignored", "reason": "draft or inactive pull request"}

    repo = resource.get("repository") or {}
    commit = (resource.get("lastMergeSourceCommit") or {}).get("commitId", "")
    try:
        review_request = ReviewRequest(
            org=settings.ado_org,
            project=(repo.get("project") or {}).get("name", ""),
            repo=repo.get("name", ""),
            pr_id=resource.get("pullRequestId", 0),
            categories=settings.auto_categories,
        )
    except ValidationError:
        return {"status": "ignored", "reason": "unrecognized payload"}

    jobs = request.app.state.jobs
    # Updates that did not push new commits (votes, titles, ...) repeat the same commit.
    key = f"{review_request.project}/{review_request.repo}/{review_request.pr_id}/{commit}"
    if not jobs.claim(key):
        return {"status": "ignored", "reason": "already reviewed this commit"}
    if jobs.active_count() >= settings.max_active_jobs:
        jobs.release(key)
        raise HTTPException(status_code=429, detail="Too many reviews in progress")

    job = ReviewJob(request=review_request)
    jobs.add(job, execute_job(job, settings, auto=True))
    return {"status": "accepted", "job_id": job.id}
