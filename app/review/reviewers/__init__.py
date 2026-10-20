from dataclasses import dataclass

from app.models.schemas import Category
from app.review.reviewers.base import Reviewer
from app.review.reviewers.bugs import BugReviewer

REVIEWERS: dict[Category, Reviewer] = {
    Category.BUG: BugReviewer(),
}


@dataclass(frozen=True)
class CategoryInfo:
    category: Category
    label: str
    description: str
    available: bool


_PLANNED = [
    (Category.TEST, "Unit tests", "Suggested pytest cases for changed logic"),
    (Category.SECURITY, "Security", "Injection, secrets, unsafe deserialization"),
    (Category.DEPENDENCY, "Dependencies", "Known CVEs, unpinned or deprecated packages"),
    (Category.OPTIMIZATION, "Optimization", "Spark, SQL and Python performance"),
]


def catalog() -> list[CategoryInfo]:
    available = [
        CategoryInfo(r.category, r.label, r.description, True) for r in REVIEWERS.values()
    ]
    planned = [CategoryInfo(c, label, desc, False) for c, label, desc in _PLANNED if c not in REVIEWERS]
    return available + planned
