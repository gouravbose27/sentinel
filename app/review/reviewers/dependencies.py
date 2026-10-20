from packaging.version import InvalidVersion, Version

from app.llm.base import LLMProvider
from app.models.schemas import SEVERITY_RANK, Category, ChangedFile, Finding, PRContext, Severity
from app.review.dependencies import Dep, manifest_kind, parse_manifest
from app.review.osv import OsvClient, OsvError
from app.review.reviewers.base import Reviewer, ReviewerError

MAX_PACKAGES = 100
DEPRECATED = {
    "pycrypto": "pycryptodome",
    "nose": "pytest",
    "sklearn": "scikit-learn",
    "pep8": "pycodestyle",
}

_STATIC, _OSV = "static", "osv"


def _version(text: str | None) -> Version | None:
    try:
        return Version(text) if text else None
    except InvalidVersion:
        return None


class DependencyReviewer(Reviewer):
    category = Category.DEPENDENCY
    label = "Dependencies"
    description = "Known CVEs, unpinned or deprecated packages"
    languages = frozenset({"manifest"})

    def __init__(self, osv: OsvClient | None = None) -> None:
        self._osv = osv or OsvClient()

    def segments(self, file: ChangedFile, max_chars: int) -> list[str]:
        # Static checks and the network lookup are separate units so one can fail alone.
        return [_STATIC, _OSV]

    async def review_segment(
        self, llm: LLMProvider, *, ctx: PRContext, file: ChangedFile, segment: str, part: int, parts: int
    ) -> list[Finding]:
        base = parse_manifest(file.path, file.base_content)
        head = parse_manifest(file.path, file.head_content)
        changed = {n: d for n, d in head.items() if n not in base or base[n].spec != d.spec}
        if segment == _STATIC:
            return self._static_checks(file, base, changed)
        return await self._vulnerability_checks(file, changed)

    def _finding(self, file: ChangedFile, dep: Dep, severity: Severity, confidence: float,
                 title: str, description: str, suggestion: str | None = None,
                 references: list[str] | None = None) -> Finding:
        return Finding(
            category=self.category, severity=severity, confidence=confidence, file=file.path,
            line_start=dep.line, line_end=dep.line, title=title, description=description,
            suggestion=suggestion, references=references or [],
        )

    def _static_checks(self, file: ChangedFile, base: dict[str, Dep], changed: dict[str, Dep]) -> list[Finding]:
        kind = manifest_kind(file.path)
        findings: list[Finding] = []
        for name, dep in changed.items():
            old = base.get(name)
            if old is None and name in DEPRECATED:
                findings.append(self._finding(
                    file, dep, Severity.MEDIUM, 0.8, f"Deprecated package: {name}",
                    f"{name} is no longer maintained or has been renamed.",
                    f"Use {DEPRECATED[name]} instead."))
            if kind in ("requirements", "pipfile") and dep.pinned is None and "~=" not in dep.spec:
                findings.append(self._finding(
                    file, dep, Severity.LOW, 0.6, f"{name} is not pinned to an exact version",
                    "Unpinned or open-ended versions make builds non-reproducible and can pull in "
                    "breaking or vulnerable releases.",
                    f"{name}==<tested version>"))
            new_v, old_v = _version(dep.pinned), _version(old.pinned if old else None)
            if new_v and new_v.is_prerelease:
                findings.append(self._finding(
                    file, dep, Severity.LOW, 0.7, f"{name} is pinned to a pre-release ({dep.pinned})",
                    "Pre-release versions can change or be withdrawn without notice."))
            if new_v and old_v and new_v.major > old_v.major:
                findings.append(self._finding(
                    file, dep, Severity.LOW, 0.7, f"Major version upgrade: {name} {old.pinned} to {dep.pinned}",
                    "Major releases often contain breaking changes. Review the release notes and run the "
                    "full test suite."))
            elif new_v and old_v and new_v < old_v:
                findings.append(self._finding(
                    file, dep, Severity.LOW, 0.7, f"{name} downgraded from {old.pinned} to {dep.pinned}",
                    "Downgrades can reintroduce fixed bugs or security issues. Confirm this is intentional."))
        return findings

    async def _vulnerability_checks(self, file: ChangedFile, changed: dict[str, Dep]) -> list[Finding]:
        pinned = {n: d for n, d in changed.items() if d.pinned}
        if not pinned:
            return []
        packages = [(n, d.pinned) for n, d in list(pinned.items())[:MAX_PACKAGES]]  # type: ignore[misc]
        try:
            found = await self._osv.vulnerabilities(packages)
        except OsvError as exc:
            raise ReviewerError("OSV.dev lookup failed; vulnerability check skipped.") from exc

        findings = []
        for (name, version), vulns in found.items():
            worst = min((v.severity for v in vulns), key=SEVERITY_RANK.get)
            fixes = [Version(v.fixed) for v in vulns if v.fixed]
            lines = [f"{v.id}: {v.summary}" if v.summary else v.id for v in vulns]
            refs = [v.id for v in vulns] + [a for v in vulns for a in v.aliases if a.startswith("CVE-")]
            plural = "ies" if len(vulns) > 1 else "y"
            findings.append(self._finding(
                file, pinned[name], worst, 0.95,
                f"{name} {version} has {len(vulns)} known vulnerabilit{plural}",
                " ".join(lines)[:600],
                f"{name}>={max(fixes)}" if fixes else None,
                refs[:8],
            ))
        return findings
