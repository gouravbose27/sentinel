import logging

from app.ado.client import AdoClient, AdoError
from app.config import Settings
from app.llm.base import LLMProvider
from app.llm.openai_provider import OpenAIProvider
from app.models.schemas import SEVERITY_RANK, JobStatus, ReviewJob
from app.review.orchestrator import run_review
from app.review.publisher import publish

log = logging.getLogger(__name__)


async def _set_status(ado: AdoClient, job: ReviewJob, state: str, description: str) -> None:
    req = job.request
    try:
        await ado.create_status(req.project, req.repo, req.pr_id, state=state, description=description)
    except AdoError as exc:
        log.warning("Could not set PR status: %s", exc)


async def _finish_auto(ado: AdoClient, job: ReviewJob, settings: Settings) -> None:
    req = job.request
    if job.status is not JobStatus.DONE:
        if settings.status_check_enabled:
            await _set_status(ado, job, "error", "AI review could not complete")
        return

    if settings.auto_post_comments and job.findings:
        try:
            result = await publish(ado, job, [f.id for f in job.findings])
            job.message = f"Review complete; {result.posted} comments posted"
        except AdoError as exc:
            job.warnings.append(f"Could not post comments: {exc}")

    if settings.status_check_enabled:
        limit = SEVERITY_RANK[settings.block_on_severity]
        blocking = sum(1 for f in job.findings if SEVERITY_RANK[f.severity] <= limit)
        if blocking:
            await _set_status(ado, job, "failed", f"{blocking} finding(s) at {settings.block_on_severity.value} or above")
        else:
            await _set_status(ado, job, "succeeded", f"{len(job.findings)} finding(s), none blocking")
    log.info("Automatic review of PR %s finished with %d findings", req.pr_id, len(job.findings))


async def execute_job(
    job: ReviewJob, settings: Settings, *, auto: bool = False, llm: LLMProvider | None = None
) -> None:
    """Run a review job to completion; `auto` adds PR comments and a status check (webhooks)."""
    try:
        async with AdoClient(job.request.org, settings.ado_pat.get_secret_value()) as ado:
            if auto and settings.status_check_enabled:
                await _set_status(ado, job, "pending", "AI review in progress")
            await run_review(job, ado=ado, llm=llm or OpenAIProvider(settings, job.request.model), settings=settings)
            if auto:
                await _finish_auto(ado, job, settings)
    except Exception:
        log.exception("Review job crashed")
        job.fail("Could not complete the review. Check the server logs.")
