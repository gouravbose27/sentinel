import difflib

from app.models.schemas import SEVERITY_RANK, Finding


def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _overlap(a: Finding, b: Finding) -> bool:
    if a.line_start is None or b.line_start is None:
        return False
    return a.line_start <= (b.line_end or b.line_start) and b.line_start <= (a.line_end or a.line_start)


def is_duplicate(a: Finding, b: Finding) -> bool:
    if a.category != b.category or a.file != b.file:
        return False
    if a.line_start is None and b.line_start is None:
        return _ratio(a.title, b.title) >= 0.8
    if not _overlap(a, b):
        return False
    shared_ref = bool({r.upper() for r in a.references} & {r.upper() for r in b.references})
    return shared_ref or _ratio(a.title, b.title) >= 0.6


def _merge(keep: Finding, other: Finding) -> Finding:
    best, rest = sorted((keep, other), key=lambda f: (SEVERITY_RANK[f.severity], -f.confidence))
    refs = list(dict.fromkeys([*best.references, *rest.references]))
    return best.model_copy(update={
        "references": refs,
        "suggestion": best.suggestion or rest.suggestion,
        "confidence": max(best.confidence, rest.confidence),
    })


def aggregate(findings: list[Finding], min_confidence: float) -> list[Finding]:
    """Drop low-confidence findings, merge duplicates, and order by severity."""
    merged: list[Finding] = []
    for finding in (f for f in findings if f.confidence >= min_confidence):
        for i, existing in enumerate(merged):
            if is_duplicate(existing, finding):
                merged[i] = _merge(existing, finding)
                break
        else:
            merged.append(finding)
    return sorted(
        merged,
        key=lambda f: (SEVERITY_RANK[f.severity], f.file, f.line_start or 0, -f.confidence),
    )
