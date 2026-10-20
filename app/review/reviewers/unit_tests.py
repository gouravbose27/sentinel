import re

from app.models.schemas import Category, ChangedFile, PRContext
from app.review.reviewers.base import Reviewer

_TEST_PATH = re.compile(r"(^|/)(tests?|testing)/|(^|/)test_[^/]*\.py$|_test\.py$|(^|/)conftest\.py$", re.IGNORECASE)


def is_test_path(path: str) -> bool:
    return bool(_TEST_PATH.search(path))


class UnitTestReviewer(Reviewer):
    category = Category.TEST
    label = "Unit tests"
    description = "Suggested pytest cases for changed logic"

    def applies_to(self, file: ChangedFile) -> bool:
        return super().applies_to(file) and not is_test_path(file.path)

    def extra_context(self, ctx: PRContext, file: ChangedFile) -> str:
        changed = [f.path for f in ctx.files if is_test_path(f.path)][:20]
        listing = ", ".join(changed) if changed else "none"
        return f"Test files changed in this PR: {listing}\n"
