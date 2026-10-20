import asyncio
import time
from collections.abc import Coroutine
from typing import Any

from app.models.schemas import ReviewJob


CLAIM_TTL = 24 * 3600


class JobStore:
    """In-memory job registry; jobs expire after `ttl` seconds."""

    def __init__(self, ttl: int) -> None:
        self._ttl = ttl
        self._jobs: dict[str, tuple[float, ReviewJob]] = {}
        self._tasks: set[asyncio.Task[Any]] = set()
        self._claims: dict[str, float] = {}

    def claim(self, key: str) -> bool:
        """Atomically reserve `key`; False if it was claimed recently (webhook de-duplication)."""
        now = time.monotonic()
        self._claims = {k: ts for k, ts in self._claims.items() if now - ts < CLAIM_TTL}
        if key in self._claims:
            return False
        self._claims[key] = now
        return True

    def release(self, key: str) -> None:
        self._claims.pop(key, None)

    def active_count(self) -> int:
        return sum(1 for _, job in self._jobs.values() if job.is_active)

    def add(self, job: ReviewJob, runner: Coroutine[Any, Any, None]) -> None:
        self._purge()
        self._jobs[job.id] = (time.monotonic(), job)
        task = asyncio.create_task(runner)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def get(self, job_id: str) -> ReviewJob | None:
        entry = self._jobs.get(job_id)
        return entry[1] if entry else None

    def _purge(self) -> None:
        cutoff = time.monotonic() - self._ttl
        for job_id in [k for k, (ts, job) in self._jobs.items() if ts < cutoff and not job.is_active]:
            del self._jobs[job_id]
