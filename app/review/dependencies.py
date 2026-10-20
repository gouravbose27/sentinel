import re
import tomllib
from dataclasses import dataclass
from pathlib import PurePosixPath

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

_REQ_FILE = re.compile(r"^(requirements|constraints)[\w.\-]*\.txt$", re.IGNORECASE)
_CONDA_LINE = re.compile(r"^\s*-\s+([A-Za-z0-9_.\-]+)(?=\s|[=<>~!]|$)\s*(==|=|>=|<=|>|<|~=)?\s*([^\s#]*)")
_EXACT = re.compile(r"^\d[\w.+!\-]*$")


@dataclass(frozen=True)
class Dep:
    name: str  # canonical (PEP 503)
    spec: str  # specifier text such as "==1.2.3" or ">=1.0"; empty when unconstrained
    pinned: str | None  # exact version when the spec pins one
    line: int | None


def manifest_kind(path: str) -> str | None:
    name = PurePosixPath(path).name
    if _REQ_FILE.match(name):
        return "requirements"
    lower = name.lower()
    if lower == "pyproject.toml":
        return "pyproject"
    if lower == "pipfile":
        return "pipfile"
    if lower in ("environment.yml", "environment.yaml"):
        return "conda"
    return None


def _from_requirement(req: Requirement, line: int | None) -> Dep:
    specs = list(req.specifier)
    pinned = None
    if len(specs) == 1 and specs[0].operator in ("==", "===") and "*" not in specs[0].version:
        pinned = specs[0].version
    return Dep(canonicalize_name(req.name), str(req.specifier), pinned, line)


def _parse_requirement(text: str, line: int | None) -> Dep | None:
    try:
        return _from_requirement(Requirement(text.strip()), line)
    except InvalidRequirement:
        return None


def _find_line(text: str, name: str) -> int | None:
    pattern = re.compile(r"(?<![\w.\-])" + re.sub(r"[-_.]+", "[-_.]", name) + r"(?![\w.\-])", re.IGNORECASE)
    for number, line in enumerate(text.splitlines(), start=1):
        if pattern.search(line):
            return number
    return None


def _parse_requirements(text: str) -> dict[str, Dep]:
    deps: dict[str, Dep] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.split(" #")[0].strip().rstrip("\\").strip()
        if not line or line.startswith(("#", "-", "git+", "http")):
            continue
        if (dep := _parse_requirement(line, number)) is not None:
            deps[dep.name] = dep
    return deps


def _toml_spec(name: str, value: object, text: str) -> Dep | None:
    """Poetry/Pipfile style `name = "<spec>"` or `name = { version = "<spec>" }`."""
    version = value.get("version", "") if isinstance(value, dict) else value
    if not isinstance(version, str):
        return None
    version = version.strip()
    canon = canonicalize_name(name)
    line = _find_line(text, name)
    if version in ("", "*"):
        return Dep(canon, "", None, line)
    if _EXACT.match(version):
        return Dep(canon, f"=={version}", version, line)
    if version.startswith("=="):
        return Dep(canon, version, version.lstrip("=").strip() or None, line)
    return Dep(canon, version, None, line)


def _parse_pyproject(text: str) -> dict[str, Dep]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return {}
    deps: dict[str, Dep] = {}
    project = data.get("project", {})
    entries: list[str] = list(project.get("dependencies", []))
    for group in project.get("optional-dependencies", {}).values():
        entries.extend(group)
    for group in data.get("dependency-groups", {}).values():
        entries.extend(item for item in group if isinstance(item, str))
    for entry in entries:
        if (dep := _parse_requirement(entry, None)) is not None:
            deps[dep.name] = Dep(dep.name, dep.spec, dep.pinned, _find_line(text, dep.name))

    poetry = data.get("tool", {}).get("poetry", {})
    sections = [poetry.get("dependencies", {}), poetry.get("dev-dependencies", {})]
    sections += [g.get("dependencies", {}) for g in poetry.get("group", {}).values()]
    for section in sections:
        for name, value in section.items():
            if name.lower() != "python" and (dep := _toml_spec(name, value, text)) is not None:
                deps[dep.name] = dep
    return deps


def _parse_pipfile(text: str) -> dict[str, Dep]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return {}
    deps: dict[str, Dep] = {}
    for section in ("packages", "dev-packages"):
        for name, value in data.get(section, {}).items():
            if (dep := _toml_spec(name, value, text)) is not None:
                deps[dep.name] = dep
    return deps


def _parse_conda(text: str) -> dict[str, Dep]:
    deps: dict[str, Dep] = {}
    in_deps = False
    for number, raw in enumerate(text.splitlines(), start=1):
        if re.match(r"^dependencies\s*:", raw):
            in_deps = True
            continue
        if raw and not raw[0].isspace() and not raw.startswith("-"):
            in_deps = False
        if not in_deps or not (m := _CONDA_LINE.match(raw)):
            continue
        name, op, version = m.group(1), m.group(2), m.group(3)
        if name.lower() in ("pip", "python"):
            continue
        pinned = version if op in ("=", "==") and version and "*" not in version else None
        deps[canonicalize_name(name)] = Dep(canonicalize_name(name), f"{op or ''}{version}", pinned, number)
    return deps


_PARSERS = {
    "requirements": _parse_requirements,
    "pyproject": _parse_pyproject,
    "pipfile": _parse_pipfile,
    "conda": _parse_conda,
}


def parse_manifest(path: str, text: str) -> dict[str, Dep]:
    kind = manifest_kind(path)
    return _PARSERS[kind](text) if kind else {}
