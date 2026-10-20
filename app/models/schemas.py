import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from urllib.parse import quote

from pydantic import BaseModel, Field, field_validator


class Severity(StrEnum):
    # Declaration order doubles as sort order (most severe first).
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


SEVERITY_RANK = {s: i for i, s in enumerate(Severity)}


class Category(StrEnum):
    BUG = "bug"
    TEST = "test"
    SECURITY = "security"
    DEPENDENCY = "dependency"
    OPTIMIZATION = "optimization"


class JobStatus(StrEnum):
    QUEUED = "queued"
    FETCHING = "fetching"
    REVIEWING = "reviewing"
    DONE = "done"
    FAILED = "failed"


# Schemas sent to the LLM: strict structured outputs need every field required, no defaults.
class LLMFinding(BaseModel):
    severity: Severity
    confidence: float
    line_start: int | None
    line_end: int | None
    title: str
    description: str
    suggestion: str | None
    references: list[str]


class LLMReview(BaseModel):
    findings: list[LLMFinding]


class Finding(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    category: Category
    severity: Severity
    confidence: float
    file: str
    line_start: int | None = None
    line_end: int | None = None
    title: str
    description: str
    suggestion: str | None = None
    references: list[str] = Field(default_factory=list)

    @property
    def fingerprint(self) -> str:
        key = f"{self.category}|{self.file}|{self.line_start}|{self.title}"
        return hashlib.sha1(key.encode(), usedforsecurity=False).hexdigest()[:12]


class SkippedFile(BaseModel):
    path: str
    reason: str


@dataclass
class ChangedFile:
    path: str
    change_type: str
    language: str
    base_content: str
    head_content: str

    @property
    def line_count(self) -> int:
        return len(self.head_content.splitlines())


@dataclass
class PRContext:
    title: str
    description: str
    author: str
    source_branch: str
    target_branch: str
    files: list[ChangedFile]
    skipped: list[SkippedFile]


_ORG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,49}$")
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$")


class ReviewRequest(BaseModel):
    org: str
    project: str
    repo: str
    pr_id: int = Field(gt=0)
    categories: list[Category] = Field(min_length=1)
    model: str | None = None

    @field_validator("org", "project", "repo", mode="before")
    @classmethod
    def _strip(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v

    @field_validator("org")
    @classmethod
    def _check_org(cls, v: str) -> str:
        if not _ORG_RE.match(v):
            raise ValueError("Enter a valid Azure DevOps organization name.")
        return v

    @field_validator("project", "repo")
    @classmethod
    def _check_name(cls, v: str) -> str:
        if not _NAME_RE.match(v):
            raise ValueError("Use letters, numbers, spaces, '.', '_' or '-'.")
        return v


class ReviewJob(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    request: ReviewRequest
    status: JobStatus = JobStatus.QUEUED
    message: str = "Queued"
    pr_title: str = ""
    pr_author: str = ""
    source_branch: str = ""
    target_branch: str = ""
    total_units: int = 0
    done_units: int = 0
    findings: list[Finding] = Field(default_factory=list)
    files_reviewed: list[str] = Field(default_factory=list)
    skipped: list[SkippedFile] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_active(self) -> bool:
        return self.status in (JobStatus.QUEUED, JobStatus.FETCHING, JobStatus.REVIEWING)

    @property
    def pr_url(self) -> str:
        r = self.request
        org, project, repo = (quote(p, safe="") for p in (r.org, r.project, r.repo))
        return f"https://dev.azure.com/{org}/{project}/_git/{repo}/pullrequest/{r.pr_id}"

    def fail(self, message: str) -> None:
        self.status = JobStatus.FAILED
        self.message = message
