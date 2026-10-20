from app.llm.base import LLMProvider
from app.models.schemas import Category, ChangedFile, Finding, PRContext
from app.review.reviewers.base import Reviewer
from app.review.security_rules import scan


class SecurityReviewer(Reviewer):
    category = Category.SECURITY
    label = "Security"
    description = "Injection, hardcoded secrets, unsafe deserialization"

    async def review_segment(
        self, llm: LLMProvider, *, ctx: PRContext, file: ChangedFile, segment: str, part: int, parts: int
    ) -> list[Finding]:
        findings = await super().review_segment(
            llm, ctx=ctx, file=file, segment=segment, part=part, parts=parts
        )
        # Rules scan the whole file, so run them once rather than per segment.
        return (scan(file) if part == 1 else []) + findings
