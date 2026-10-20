from app.models.schemas import Category
from app.review.reviewers.base import Reviewer


class OptimizationReviewer(Reviewer):
    category = Category.OPTIMIZATION
    label = "Optimization"
    description = "Spark, SQL and Python performance"
