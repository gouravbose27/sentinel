from app.models.schemas import Category
from app.review.reviewers.base import Reviewer


class BugReviewer(Reviewer):
    category = Category.BUG
    label = "Bug detection"
    description = "Logic errors, null handling, bad joins, resource leaks"
