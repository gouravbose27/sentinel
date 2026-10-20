from dataclasses import dataclass

from app.models.schemas import Category
from app.review.reviewers.base import Reviewer
from app.review.reviewers.bugs import BugReviewer
from app.review.reviewers.dependencies import DependencyReviewer
from app.review.reviewers.optimization import OptimizationReviewer
from app.review.reviewers.security import SecurityReviewer
from app.review.reviewers.unit_tests import UnitTestReviewer

REVIEWERS: dict[Category, Reviewer] = {
    Category.BUG: BugReviewer(),
    Category.TEST: UnitTestReviewer(),
    Category.SECURITY: SecurityReviewer(),
    Category.DEPENDENCY: DependencyReviewer(),
    Category.OPTIMIZATION: OptimizationReviewer(),
}


@dataclass(frozen=True)
class CategoryInfo:
    category: Category
    label: str
    description: str
    available: bool


def catalog() -> list[CategoryInfo]:
    return [CategoryInfo(r.category, r.label, r.description, True) for r in REVIEWERS.values()]
