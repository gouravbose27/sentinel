from abc import ABC
from typing import ClassVar

from app.llm.base import LLMProvider
from app.models.schemas import Category, ChangedFile, Finding, LLMFinding, LLMReview
from app.review.prompts import COMMON_RULES, build_user_prompt, focus_for


class Reviewer(ABC):
    category: ClassVar[Category]
    label: ClassVar[str]
    description: ClassVar[str]

    async def review_chunk(
        self,
        llm: LLMProvider,
        *,
        title: str,
        pr_description: str,
        file: ChangedFile,
        chunk: str,
        part: int,
        parts: int,
    ) -> list[Finding]:
        system = f"{COMMON_RULES}\nFocus:\n{focus_for(self.category, file.language)}"
        user = build_user_prompt(
            title=title, description=pr_description, path=file.path, language=file.language,
            change_type=file.change_type, part=part, parts=parts, chunk=chunk,
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
