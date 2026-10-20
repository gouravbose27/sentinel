import re
from dataclasses import dataclass, field

from app.ado.client import AdoClient, AdoError
from app.models.schemas import Finding, ReviewJob

_MARKER_RE = re.compile(r"<!-- ai-pr-review:([\w-]+) -->")


@dataclass
class PublishResult:
    posted: int = 0
    duplicates: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def format_comment(finding: Finding) -> str:
    lang = "sql" if finding.file.lower().endswith(".sql") else "python"
    lines = [f"**[{finding.severity.value.title()} | {finding.category.value.title()}] {finding.title}**", ""]
    lines.append(finding.description)
    if finding.suggestion:
        lines += ["", "Suggestion:", f"```{lang}", finding.suggestion, "```"]
    if finding.references:
        lines += ["", "References: " + ", ".join(finding.references)]
    lines += ["", f"_AI review, confidence {finding.confidence:.0%}_", f"<!-- ai-pr-review:{finding.fingerprint} -->"]
    return "\n".join(lines)


def format_summary(job: ReviewJob, posted: int) -> str:
    counts: dict[str, int] = {}
    for f in job.findings:
        counts[f.severity.value] = counts.get(f.severity.value, 0) + 1
    breakdown = ", ".join(f"{n} {sev}" for sev, n in counts.items()) or "no findings"
    return (
        f"**AI review summary**\n\n{len(job.findings)} findings ({breakdown}) across "
        f"{len(job.files_reviewed)} files. {posted} comments posted.\n\n"
        f"<!-- ai-pr-review:summary-{job.id} -->"
    )


async def publish(ado: AdoClient, job: ReviewJob, finding_ids: list[str]) -> PublishResult:
    req = job.request
    wanted = set(finding_ids)
    selected = [f for f in job.findings if f.id in wanted]
    result = PublishResult()

    threads = await ado.list_threads(req.project, req.repo, req.pr_id)
    seen = {
        m
        for thread in threads
        for comment in thread.get("comments", [])
        for m in _MARKER_RE.findall(comment.get("content") or "")
    }

    for finding in selected:
        if finding.fingerprint in seen:
            result.duplicates += 1
            continue
        try:
            await ado.create_thread(
                req.project, req.repo, req.pr_id, format_comment(finding),
                file_path=finding.file, line_start=finding.line_start, line_end=finding.line_end,
            )
            result.posted += 1
        except AdoError as exc:
            result.failed += 1
            if str(exc) not in result.errors:
                result.errors.append(str(exc))

    summary_marker = f"summary-{job.id}"
    if result.posted and summary_marker not in seen:
        try:
            await ado.create_thread(req.project, req.repo, req.pr_id, format_summary(job, result.posted))
        except AdoError as exc:
            result.errors.append(str(exc))
    return result
