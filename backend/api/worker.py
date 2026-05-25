"""Background worker — polls `queued` runs and drives them via the Runner.

This is the thin seam the brief calls out (§9): the Runner is the engine
primitive, the worker is the dispatcher. Phase 9 swaps this loop for a
real queue (Redis/RQ, Celery) without changing the engine.

Design notes:
- Each `drive_queued()` call is fully synchronous (blocking SQLAlchemy +
  `time.sleep` for retries). We dispatch it in a thread executor so the
  asyncio event loop stays free for HTTP and SSE.
- One run at a time, in order — sequencing keeps Phase 1 semantics (no
  cross-run contention) and matches the §1 "single machine, single
  worker" non-goal carve-out.
- Tests typically disable the loop (`HOLLERBOX_WORKER_ENABLED=0`) and
  call `Worker.drive_one()` themselves so they can assert against state
  deterministically.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from hollerbox.core.workflow import WorkflowLoadError, load_workflow_from_source
from hollerbox.store import RunRow, repo, session_scope

if TYPE_CHECKING:
    from api.deps import EngineSurface

log = logging.getLogger("hollerbox.worker")

_POLL_SECONDS = 0.2


class Worker:
    """Background dispatcher for queued runs."""

    def __init__(self, surface: EngineSurface, *, poll_seconds: float = _POLL_SECONDS):
        self._surface = surface
        self._poll = poll_seconds
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run_forever(), name="hollerbox-worker")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        try:
            await asyncio.wait_for(self._task, timeout=2.0)
        except TimeoutError:
            self._task.cancel()
        self._task = None

    async def _run_forever(self) -> None:
        while not self._stop.is_set():
            drove = await asyncio.get_running_loop().run_in_executor(None, self.drive_one)
            if not drove:
                # Nothing queued — short sleep before polling again. The
                # wait_for races the stop signal so shutdown is immediate.
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=self._poll)

    # --------------------------- sync entry points ---------------------------

    def drive_one(self) -> bool:
        """Pick up the oldest `queued` run and drive it to completion/pause.

        Returns True if a run was driven (so the loop should poll again
        immediately), False if the queue is empty. Errors during dispatch
        mark the run failed and are logged — they don't tear down the loop.
        """
        claim = self._claim_one_queued()
        if claim is None:
            return False
        run_id, yaml_source, wf_name = claim
        try:
            workflow = load_workflow_from_source(yaml_source, name_hint=wf_name)
        except WorkflowLoadError as exc:
            log.exception("worker: workflow YAML failed to parse for run %s", run_id)
            self._mark_failed(run_id, f"workflow YAML invalid: {exc}")
            return True

        try:
            self._surface.runner.drive_queued(workflow, run_id=run_id)
        except Exception as exc:  # noqa: BLE001 — worker is the catch-all
            log.exception("worker: drive_queued crashed for run %s", run_id)
            self._mark_failed(run_id, f"{type(exc).__name__}: {exc}")
        return True

    # --------------------------- internals ---------------------------

    def _claim_one_queued(self) -> tuple[str, str, str] | None:
        """Return (run_id, yaml_source, workflow_name) for one queued run, or None.

        We don't change the run row here — the Runner flips it to
        `running` on entry. A second worker is not contemplated in v1
        (see §9); when distributed we'll need an atomic SELECT ... FOR
        UPDATE SKIP LOCKED or a claim token.
        """
        with session_scope(self._surface.session_factory) as s:
            from sqlalchemy import select

            row = s.scalar(
                select(RunRow)
                .where(RunRow.status == "queued")
                .order_by(RunRow.created_at)
                .limit(1)
            )
            if row is None:
                return None
            wf = row.workflow
            if wf is None or not wf.yaml_source:
                # Orphaned run — mark it failed so it doesn't poison the loop.
                repo.update_run_status(
                    s,
                    row,
                    status="failed",
                    error="run has no associated workflow YAML",
                )
                return None
            return row.id, wf.yaml_source, wf.name

    def _mark_failed(self, run_id: str, error: str) -> None:
        with session_scope(self._surface.session_factory) as s:
            row = repo.get_run(s, run_id)
            if row is None:
                return
            repo.update_run_status(s, row, status="failed", error=error)
