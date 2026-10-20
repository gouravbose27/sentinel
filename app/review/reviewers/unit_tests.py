import re

from app.models.schemas import Category, ChangedFile, PRContext
from app.review.reviewers.base import Reviewer

_TEST_PATH = re.compile(
    r"(^|/)(tests?|testing)/|(^|/)test_[^/]*\.(py|sql)$|_test\.(py|sql)$|(^|/)conftest\.py$", re.IGNORECASE
)

_TEST_STYLE = {
    "python": "Write the tests in Python using pytest.",
    "pyspark": "Write the tests in Python using pytest with a local SparkSession fixture.",
    "sql": "Write the tests in SQL (setup INSERTs plus an assertion query), not Python.",
    "sparksql": "Write the tests in Spark SQL (temp views plus an assertion query), not Python.",
}


def is_test_path(path: str) -> bool:
    return bool(_TEST_PATH.search(path))


class UnitTestReviewer(Reviewer):
    category = Category.TEST
    label = "Unit tests"
    description = "Suggested tests for changed logic, in the file's own language"

    def applies_to(self, file: ChangedFile) -> bool:
        return super().applies_to(file) and not is_test_path(file.path)

    def extra_context(self, ctx: PRContext, file: ChangedFile) -> str:
        changed = [f.path for f in ctx.files if is_test_path(f.path)][:20]
        listing = ", ".join(changed) if changed else "none"
        style = _TEST_STYLE.get(file.language, "")
        return f"Test files changed in this PR: {listing}\n{style}\n"
