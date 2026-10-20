import asyncio
import logging

from app.ado.client import AdoClient, AdoError
from app.config import Settings
from app.llm.base import LLMError, LLMProvider
from app.models.schemas import SEVERITY_RANK, JobStatus, ReviewJob
from app.review.chunker import build_chunks
from app.review.files import collect_pull_request
from app.review.reviewers import REVIEWERS

log = logging.getLogger(__name__)


async def run_review(
    job: ReviewJob, *, ado: AdoClient, llm: LLMProvider, settings: Settings
) -> None:
    request = job.request
    try:
        job.status, job.message = JobStatus.FETCHING, "Fetching pull request"
        ctx = await collect_pull_request(ado, request, settings)
        job.pr_title, job.pr_author = ctx.title, ctx.author
        job.source_branch, job.target_branch = ctx.source_branch, ctx.target_branch
        job.skipped = ctx.skipped
        job.files_reviewed = [f.path for f in ctx.files]

        reviewers = [REVIEWERS[c] for c in request.categories if c in REVIEWERS]
        units = []
        for file in ctx.files:
            chunks = build_chunks(file.base_content, file.head_content, settings.max_chunk_chars)
            for reviewer in reviewers:
                for i, chunk in enumerate(chunks, start=1):
                    units.append((reviewer, file, chunk, i, len(chunks)))

        job.total_units = len(units)
        job.status, job.message = JobStatus.REVIEWING, "Analyzing changes"
        sem = asyncio.Semaphore(settings.llm_concurrency)

        async def work(reviewer, file, chunk, part, parts) -> None:
            async with sem:
                try:
                    found = await reviewer.review_chunk(
                        llm, title=ctx.title, pr_description=ctx.description,
                        file=file, chunk=chunk, part=part, parts=parts,
                    )
                except LLMError as exc:
                    job.errors.append(f"{file.path}: {exc}")
                except Exception:
                    log.exception("Unexpected reviewer failure")
                    job.errors.append(f"{file.path}: unexpected error during analysis")
                else:
                    job.findings.extend(found)
                finally:
                    job.done_units += 1

        await asyncio.gather(*(work(*u) for u in units))

        job.findings = sorted(
            (f for f in job.findings if f.confidence >= settings.min_confidence),
            key=lambda f: (SEVERITY_RANK[f.severity], f.file, f.line_start or 0, -f.confidence),
        )
        if units and job.done_units == len(job.errors):
            job.fail("Every analysis request failed. " + job.errors[0])
            return
        job.status = JobStatus.DONE
        job.message = "Review complete" if units else "No reviewable Python or SQL changes found"
    except AdoError as exc:
        job.fail(str(exc))
    except Exception:
        log.exception("Review job failed")
        job.fail("Unexpected error while reviewing. Check the server logs.")
