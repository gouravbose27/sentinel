import asyncio
import logging

from app.ado.client import AdoClient, AdoError
from app.config import Settings
from app.llm.base import LLMError, LLMProvider
from app.models.schemas import Category, JobStatus, ReviewJob
from app.review.aggregator import aggregate
from app.review.files import collect_pull_request
from app.review.reviewers import REVIEWERS
from app.review.reviewers.base import Reviewer, ReviewerError

log = logging.getLogger(__name__)


async def run_review(
    job: ReviewJob,
    *,
    ado: AdoClient,
    llm: LLMProvider,
    settings: Settings,
    reviewers: dict[Category, Reviewer] | None = None,
) -> None:
    request = job.request
    registry = reviewers if reviewers is not None else REVIEWERS
    try:
        job.status, job.message = JobStatus.FETCHING, "Fetching pull request"
        ctx = await collect_pull_request(ado, request, settings)
        job.pr_title, job.pr_author = ctx.title, ctx.author
        job.source_branch, job.target_branch = ctx.source_branch, ctx.target_branch
        job.skipped = ctx.skipped

        selected = [registry[c] for c in request.categories if c in registry]
        units = []
        for file in ctx.files:
            for reviewer in selected:
                if not reviewer.applies_to(file):
                    continue
                segments = reviewer.segments(file, settings.max_chunk_chars)
                for i, segment in enumerate(segments, start=1):
                    units.append((reviewer, file, segment, i, len(segments)))

        if len(units) > settings.max_segments:
            job.warnings.append(
                f"Large pull request: only the first {settings.max_segments} of {len(units)} "
                "analysis segments were reviewed."
            )
            units = units[: settings.max_segments]
        job.files_reviewed = list(dict.fromkeys(u[1].path for u in units))

        job.total_units = len(units)
        job.status, job.message = JobStatus.REVIEWING, "Analyzing changes"
        sem = asyncio.Semaphore(settings.llm_concurrency)

        async def work(reviewer, file, segment, part, parts) -> None:
            async with sem:
                try:
                    found = await reviewer.review_segment(
                        llm, ctx=ctx, file=file, segment=segment, part=part, parts=parts
                    )
                except (LLMError, ReviewerError) as exc:
                    job.errors.append(f"{file.path}: {exc}")
                except Exception:
                    log.exception("Unexpected reviewer failure")
                    job.errors.append(f"{file.path}: unexpected error during analysis")
                else:
                    job.findings.extend(found)
                finally:
                    job.done_units += 1

        await asyncio.gather(*(work(*u) for u in units))

        job.findings = [f for f in job.findings if f.category in request.categories]
        job.findings = aggregate(job.findings, settings.min_confidence)
        if units and job.done_units == len(job.errors):
            job.fail("Every analysis request failed. " + job.errors[0])
            return
        job.status = JobStatus.DONE
        job.message = "Review complete" if units else "No reviewable changes found for the selected modules"
    except AdoError as exc:
        job.fail(str(exc))
    except Exception:
        log.exception("Review job failed")
        job.fail("Unexpected error while reviewing. Check the server logs.")
