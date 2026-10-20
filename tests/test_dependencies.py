import asyncio

import httpx

from app.models.schemas import Category, ChangedFile, PRContext, Severity
from app.review.dependencies import parse_manifest
from app.review.osv import OsvClient
from app.review.reviewers.dependencies import DependencyReviewer


def test_parse_requirements():
    deps = parse_manifest("/requirements.txt", "# c\nrequests==2.31.0\nPyYAML>=6  # yaml\nnumpy\n-r other.txt\n")
    assert deps["requests"].pinned == "2.31.0" and deps["requests"].line == 2
    assert deps["pyyaml"].pinned is None and deps["pyyaml"].spec == ">=6"
    assert deps["numpy"].spec == ""


def test_parse_pyproject_and_pipfile_and_conda():
    pyproject = (
        '[project]\ndependencies = ["pandas==2.0.1", "pyspark>=3.4"]\n'
        '[tool.poetry.dependencies]\npython = "^3.11"\nrequests = "2.31.0"\n'
    )
    deps = parse_manifest("/pyproject.toml", pyproject)
    assert deps["pandas"].pinned == "2.0.1" and deps["pandas"].line == 2
    assert deps["requests"].pinned == "2.31.0" and "python" not in deps

    pipfile = '[packages]\nflask = "==2.0.0"\nboto3 = "*"\n'
    deps = parse_manifest("/Pipfile", pipfile)
    assert deps["flask"].pinned == "2.0.0" and deps["boto3"].spec == ""

    conda = "channels:\n  - conda-forge\ndependencies:\n  - python=3.11\n  - numpy=1.26.0\n  - pip:\n    - requests==2.0.0\n"
    deps = parse_manifest("/environment.yml", conda)
    assert set(deps) == {"numpy", "requests"} and deps["numpy"].pinned == "1.26.0"


def osv_transport(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/querybatch"):
        return httpx.Response(200, json={"results": [{"vulns": [{"id": "GHSA-xxxx"}]}]})
    return httpx.Response(200, json={
        "id": "GHSA-xxxx", "summary": "Header injection", "aliases": ["CVE-2024-0001"],
        "database_specific": {"severity": "HIGH"},
        "affected": [{"package": {"name": "requests", "ecosystem": "PyPI"},
                      "ranges": [{"events": [{"introduced": "0"}, {"fixed": "2.32.0"}]}]}],
    })


def review(base: str, head: str, path: str = "/requirements.txt", segment: str = "static"):
    reviewer = DependencyReviewer(OsvClient(httpx.AsyncClient(transport=httpx.MockTransport(osv_transport))))
    file = ChangedFile(path, "edit", "manifest", base, head)
    ctx = PRContext("t", "", "", "", "", [file], [])
    return asyncio.run(reviewer.review_segment(None, ctx=ctx, file=file, segment=segment, part=1, parts=2))


def test_static_checks():
    findings = review("flask==1.0\nrequests==2.0\n", "flask==2.0\nrequests==1.0\nnose\nboto3\n")
    titles = {f.title for f in findings}
    assert "Major version upgrade: flask 1.0 to 2.0" in titles
    assert "requests downgraded from 2.0 to 1.0" in titles
    assert "Deprecated package: nose" in titles
    assert "boto3 is not pinned to an exact version" in titles


def test_osv_finding_has_fix_and_severity():
    (finding,) = review("", "requests==2.31.0\n", segment="osv")
    assert finding.category is Category.DEPENDENCY and finding.severity is Severity.HIGH
    assert finding.suggestion == "requests>=2.32.0"
    assert "CVE-2024-0001" in finding.references and finding.line_start == 1


def test_unchanged_dependencies_are_not_queried():
    assert review("requests==2.31.0\n", "requests==2.31.0\n# note\n", segment="osv") == []
