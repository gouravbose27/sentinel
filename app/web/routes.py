import logging
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app.ado.client import AdoClient, AdoError
from app.config import Settings
from app.llm.openai_provider import OpenAIProvider
from app.models.schemas import SEVERITY_RANK, JobStatus, ReviewJob, ReviewRequest, Severity
from app.review.orchestrator import run_review
from app.review.publisher import publish
from app.review.reviewers import REVIEWERS, catalog

log = logging.getLogger(__name__)

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
router = APIRouter()


def _render_form(request: Request, *, values: dict[str, str], selected: list[str],
                 errors: dict[str, str], status_code: int = 200) -> Response:
    return templates.TemplateResponse(
        request,
        "index.html",
        {"categories": catalog(), "values": values, "selected": selected, "errors": errors},
        status_code=status_code,
    )


def _panel_context(job: ReviewJob) -> dict:
    groups: dict[str, list] = {}
    for finding in job.findings:
        groups.setdefault(finding.file, []).append(finding)
    counts = {s.value: 0 for s in Severity}
    for finding in job.findings:
        counts[finding.severity.value] += 1
    progress = round(100 * job.done_units / job.total_units) if job.total_units else 0
    return {"job": job, "groups": groups, "counts": counts, "progress": progress,
            "severities": [s.value for s in sorted(Severity, key=SEVERITY_RANK.get)]}


async def _run_job(job: ReviewJob, settings: Settings) -> None:
    try:
        async with AdoClient(job.request.org, settings.ado_pat.get_secret_value()) as ado:
            await run_review(job, ado=ado, llm=OpenAIProvider(settings), settings=settings)
    except Exception:
        log.exception("Could not start review job")
        job.fail("Could not start the review. Check the server configuration.")


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> Response:
    settings: Settings = request.app.state.settings
    selected = [c.category.value for c in catalog() if c.available]
    return _render_form(request, values={"org": settings.ado_org}, selected=selected, errors={})


@router.post("/reviews")
async def create_review(
    request: Request,
    org: str = Form(""),
    project: str = Form(""),
    repo: str = Form(""),
    pr_id: str = Form(""),
    categories: list[str] = Form(default=[]),
) -> Response:
    settings: Settings = request.app.state.settings
    values = {"org": org, "project": project, "repo": repo, "pr_id": pr_id}
    available = {c.value for c in REVIEWERS}
    chosen = [c for c in categories if c in available]

    errors: dict[str, str] = {}
    if not settings.openai_api_key.get_secret_value():
        errors["form"] = "OPENAI_API_KEY is not configured on the server."
    elif not settings.ado_pat.get_secret_value():
        errors["form"] = "ADO_PAT is not configured on the server."

    review_request = None
    try:
        review_request = ReviewRequest(
            org=org or settings.ado_org, project=project, repo=repo, pr_id=pr_id, categories=chosen
        )
    except ValidationError as exc:
        for err in exc.errors():
            field = str(err["loc"][0]) if err["loc"] else "form"
            message = "Enter a positive whole number." if field == "pr_id" else (
                "Select at least one analysis module." if field == "categories" else err["msg"].removeprefix("Value error, ")
            )
            errors.setdefault(field, message)

    if errors or review_request is None:
        return _render_form(request, values=values, selected=chosen, errors=errors, status_code=422)

    job = ReviewJob(request=review_request)
    request.app.state.jobs.add(job, _run_job(job, settings))
    return RedirectResponse(f"/reviews/{job.id}", status_code=303)


def _get_job(request: Request, job_id: str) -> ReviewJob:
    job = request.app.state.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Review not found or expired.")
    return job


@router.get("/reviews/{job_id}", response_class=HTMLResponse)
async def review_page(request: Request, job_id: str) -> Response:
    job = _get_job(request, job_id)
    return templates.TemplateResponse(request, "review.html", _panel_context(job))


@router.get("/reviews/{job_id}/panel", response_class=HTMLResponse)
async def review_panel(request: Request, job_id: str) -> Response:
    job = _get_job(request, job_id)
    return templates.TemplateResponse(request, "_panel.html", _panel_context(job))


@router.get("/api/reviews/{job_id}")
async def review_json(request: Request, job_id: str) -> JSONResponse:
    job = _get_job(request, job_id)
    return JSONResponse(job.model_dump(mode="json"))


@router.post("/reviews/{job_id}/post", response_class=HTMLResponse)
async def post_review(
    request: Request, job_id: str, finding_ids: list[str] = Form(default=[])
) -> Response:
    job = _get_job(request, job_id)
    settings: Settings = request.app.state.settings
    context: dict = {"job": job, "result": None, "error": None}
    if job.status is not JobStatus.DONE:
        context["error"] = "The review is not finished yet."
    elif not finding_ids:
        context["error"] = "Select at least one finding to post."
    else:
        try:
            async with AdoClient(job.request.org, settings.ado_pat.get_secret_value()) as ado:
                context["result"] = await publish(ado, job, finding_ids)
        except AdoError as exc:
            context["error"] = str(exc)
    return templates.TemplateResponse(request, "_post_result.html", context)
