import asyncio
import time
from collections.abc import Coroutine
from typing import Any

from app.models.schemas import ReviewJob


class JobStore:
    """In-memory job registry; jobs expire after `ttl` seconds."""

    def __init__(self, ttl: int) -> None:
        self._ttl = ttl
        self._jobs: dict[str, tuple[float, ReviewJob]] = {}
        self._tasks: set[asyncio.Task[Any]] = set()

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
