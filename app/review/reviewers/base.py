from abc import ABC
from typing import ClassVar

from app.llm.base import LLMProvider
from app.models.schemas import Category, ChangedFile, Finding, LLMFinding, LLMReview, PRContext
from app.review.chunker import build_chunks
from app.review.prompts import COMMON_RULES, build_user_prompt, focus_for
from app.review.secrets import redact

CODE_LANGUAGES = frozenset({"python", "pyspark", "sql", "sparksql"})


class ReviewerError(Exception):
    """A reviewer could not finish; the message is safe to show to the user."""


class Reviewer(ABC):
    category: ClassVar[Category]
    label: ClassVar[str]
    description: ClassVar[str]
    languages: ClassVar[frozenset[str]] = CODE_LANGUAGES

    def applies_to(self, file: ChangedFile) -> bool:
        return file.language in self.languages

    def segments(self, file: ChangedFile, max_chars: int) -> list[str]:
        """Independent units of work; each is reviewed (and can fail) on its own."""
        return build_chunks(file.base_content, file.head_content, max_chars)

    def extra_context(self, ctx: PRContext, file: ChangedFile) -> str:
        return ""

    async def review_segment(
        self,
        llm: LLMProvider,
        *,
        ctx: PRContext,
        file: ChangedFile,
        segment: str,
        part: int,
        parts: int,
    ) -> list[Finding]:
        system = f"{COMMON_RULES}\nFocus:\n{focus_for(self.category, file.language)}"
        user = build_user_prompt(
            title=ctx.title, description=ctx.description, path=file.path, language=file.language,
            change_type=file.change_type, part=part, parts=parts, chunk=redact(segment),
            extra=self.extra_context(ctx, file),
        )
        result = await llm.parse(system=system, user=user, schema=LLMReview)
        return [self._to_finding(raw, file) for raw in result.findings]

    def _to_finding(self, raw: LLMFinding, file: ChangedFile) -> Finding:
        start, end = raw.line_start, raw.line_end
        if start is None or not 1 <= start <= file.line_count:
            start = end = None
        elif end is None or not start <= end <= file.line_count:
            end = start
        return Finding(
            category=self.category,
            severity=raw.severity,
            confidence=min(max(raw.confidence, 0.0), 1.0),
            file=file.path,
            line_start=start,
            line_end=end,
            title=raw.title.strip(),
            description=raw.description.strip(),
            suggestion=(raw.suggestion or "").strip() or None,
            references=[r.strip() for r in raw.references if r.strip()],
        )
