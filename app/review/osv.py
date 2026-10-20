import asyncio
import logging
from dataclasses import dataclass, field

import httpx
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from app.models.schemas import Severity

log = logging.getLogger(__name__)

OSV_URL = "https://api.osv.dev/v1"
MAX_VULNS_PER_PACKAGE = 5
_SEVERITY = {
    "CRITICAL": Severity.CRITICAL,
    "HIGH": Severity.HIGH,
    "MODERATE": Severity.MEDIUM,
    "MEDIUM": Severity.MEDIUM,
    "LOW": Severity.LOW,
}


class OsvError(Exception):
    pass


@dataclass
class Vuln:
    id: str
    summary: str = ""
    aliases: list[str] = field(default_factory=list)
    severity: Severity = Severity.MEDIUM
    fixed: str | None = None  # lowest fixed version above the queried one


def _lowest_fix(detail: dict, package: str, current: str) -> str | None:
    try:
        installed = Version(current)
    except InvalidVersion:
        return None
    candidates: list[Version] = []
    for affected in detail.get("affected", []):
        pkg = affected.get("package", {})
        if pkg.get("ecosystem") != "PyPI" or canonicalize_name(pkg.get("name", "")) != package:
            continue
        for rng in affected.get("ranges", []):
            for event in rng.get("events", []):
                try:
                    if "fixed" in event and Version(event["fixed"]) > installed:
                        candidates.append(Version(event["fixed"]))
                except InvalidVersion:
                    continue
    return str(min(candidates)) if candidates else None


def _parse_vuln(detail: dict, package: str, version: str) -> Vuln:
    rating = str((detail.get("database_specific") or {}).get("severity", "")).upper()
    return Vuln(
        id=detail["id"],
        summary=detail.get("summary", ""),
        aliases=detail.get("aliases", []),
        severity=_SEVERITY.get(rating, Severity.MEDIUM),
        fixed=_lowest_fix(detail, package, version),
    )


class OsvClient:
    """Looks up known vulnerabilities for pinned PyPI packages via OSV.dev."""

    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self._http = http

    async def vulnerabilities(self, packages: list[tuple[str, str]]) -> dict[tuple[str, str], list[Vuln]]:
        if not packages:
            return {}
        if self._http is not None:
            return await self._lookup(self._http, packages)
        async with httpx.AsyncClient(timeout=20) as http:
            return await self._lookup(http, packages)

    async def _lookup(
        self, http: httpx.AsyncClient, packages: list[tuple[str, str]]
    ) -> dict[tuple[str, str], list[Vuln]]:
        queries = [
            {"package": {"name": name, "ecosystem": "PyPI"}, "version": version}
            for name, version in packages
        ]
        try:
            resp = await http.post(f"{OSV_URL}/querybatch", json={"queries": queries})
            resp.raise_for_status()
            results = resp.json().get("results", [])
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("OSV batch query failed: %s", type(exc).__name__)
            raise OsvError("OSV.dev lookup failed") from exc

        ids_by_pkg = {
            pkg: [v["id"] for v in (result.get("vulns") or [])][:MAX_VULNS_PER_PACKAGE]
            for pkg, result in zip(packages, results)
        }
        sem = asyncio.Semaphore(8)

        async def detail(vuln_id: str) -> dict | None:
            async with sem:
                try:
                    r = await http.get(f"{OSV_URL}/vulns/{vuln_id}")
                    r.raise_for_status()
                    return r.json()
                except (httpx.HTTPError, ValueError):
                    return None

        unique = sorted({i for ids in ids_by_pkg.values() for i in ids})
        details = dict(zip(unique, await asyncio.gather(*(detail(i) for i in unique))))

        out: dict[tuple[str, str], list[Vuln]] = {}
        for (name, version), ids in ids_by_pkg.items():
            vulns = [
                _parse_vuln(details[i], name, version) if details.get(i) else Vuln(id=i)
                for i in ids
            ]
            if vulns:
                out[(name, version)] = vulns
        return out
