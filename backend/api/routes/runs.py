"""Runs — list, detail, enqueue, SSE event stream.

`POST /workflows/{name}/run` creates a `queued` run row and returns
immediately; the background worker (or a test) picks it up via
`Runner.drive_queued`. SSE consumers poll `step_runs` + the parent run
row for transitions; we close the stream when the run reaches a terminal
state (success / failed / cancelled).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sse_starlette.sse import EventSourceResponse

from api.deps import EngineSurface, get_surface
from api.schemas import RunDetail, RunRequest, RunSummary, StepRunDetail
from hollerbox.core.workflow import WorkflowLoadError, load_workflow_from_source
from hollerbox.store import RunRow, StepRunRow, repo, session_scope

router = APIRouter(tags=["runs"])

# Polling cadence for the SSE stream. Phase 3 keeps this naive; Phase 5
# can wire a real pub/sub when chat streaming forces sub-second latency.
_SSE_POLL_SECONDS = 0.25


def _step_detail(row: StepRunRow) -> StepRunDetail:
    return StepRunDetail(
        step_id=row.step_id,
        step_type=row.step_type,
        status=row.status,
        resolved_input=row.resolved_input,
        output=row.output,
        logs=list(row.logs or []),
        error=row.error,
        attempt=row.attempt,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


def _summary(row: RunRow) -> RunSummary:
    return RunSummary(
        id=row.id,
        workflow_name=row.workflow.name if row.workflow else "",
        status=row.status,
        dry_run=row.dry_run,
        trigger_kind=row.trigger_kind,
        started_at=row.started_at,
        finished_at=row.finished_at,
        error=row.error,
        created_at=row.created_at,
    )


def _detail(row: RunRow, steps: list[StepRunRow]) -> RunDetail:
    return RunDetail(
        id=row.id,
        workflow_name=row.workflow.name if row.workflow else "",
        status=row.status,
        dry_run=row.dry_run,
        trigger_kind=row.trigger_kind,
        started_at=row.started_at,
        finished_at=row.finished_at,
        error=row.error,
        created_at=row.created_at,
        inputs=row.inputs,
        steps=[_step_detail(sr) for sr in steps],
    )


# --------------------------- list / detail ---------------------------

@router.get("/runs", response_model=list[RunSummary])
def list_runs(
    workflow: str | None = Query(default=None, description="Filter by workflow name."),
    limit: int = Query(default=50, ge=1, le=500),
    surface: EngineSurface = Depends(get_surface),
) -> list[RunSummary]:
    with session_scope(surface.session_factory) as s:
        rows = repo.list_runs(s, workflow_name=workflow, limit=limit)
        return [_summary(r) for r in rows]


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(run_id: str, surface: EngineSurface = Depends(get_surface)) -> RunDetail:
    with session_scope(surface.session_factory) as s:
        row = repo.get_run(s, run_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"run {run_id!r} not found")
        steps = list(repo.list_step_runs(s, row.id))
        return _detail(row, steps)


# --------------------------- enqueue ---------------------------

@router.post(
    "/workflows/{name}/run",
    response_model=RunSummary,
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_run(
    name: str,
    body: RunRequest,
    surface: EngineSurface = Depends(get_surface),
) -> RunSummary:
    """Create a queued run; the worker picks it up asynchronously."""
    with session_scope(surface.session_factory) as s:
        wf_row = repo.get_workflow_by_name(s, name)
        if wf_row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"workflow {name!r} not found")
        yaml_source = wf_row.yaml_source

    try:
        wf = load_workflow_from_source(yaml_source, name_hint=name)
    except WorkflowLoadError as exc:
        # The stored YAML failed to re-parse — surfaces a server-side
        # problem (someone hand-edited the DB, schema evolved, etc.).
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, exc.message) from exc

    result = surface.runner.enqueue(
        wf,
        inputs=body.inputs,
        yaml_source=yaml_source,
        dry_run=body.dry_run,
        trigger_kind=body.trigger_kind,
    )
    with session_scope(surface.session_factory) as s:
        row = repo.get_run(s, result.run_id)
        assert row is not None  # we just created it
        return _summary(row)


# --------------------------- SSE stream ---------------------------

_TERMINAL = {"success", "failed", "cancelled"}


@router.get("/runs/{run_id}/events")
async def stream_run_events(
    run_id: str, surface: EngineSurface = Depends(get_surface)
) -> EventSourceResponse:
    """Stream a run's progression as SSE.

    Emits a `status` event whenever the run row's status changes, and a
    `step` event for each new `step_runs` row. Closes the connection
    when the run reaches a terminal state.
    """
    # Verify the run exists before opening the long-poll.
    with session_scope(surface.session_factory) as s:
        row = repo.get_run(s, run_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"run {run_id!r} not found")

    async def gen() -> AsyncIterator[dict[str, str]]:
        seen_step_ids: set[str] = set()
        last_status: str | None = None
        # Bounded grace period after terminal state so a slow client gets the
        # final events; the run-detail endpoint is the source of truth anyway.
        terminal_iters_left = 2
        while True:
            with session_scope(surface.session_factory) as s:
                run_row = repo.get_run(s, run_id)
                if run_row is None:
                    break
                steps = list(repo.list_step_runs(s, run_id))
                status_now = run_row.status

            if status_now != last_status:
                yield {
                    "event": "status",
                    "data": json.dumps({"run_id": run_id, "status": status_now}),
                }
                last_status = status_now

            for sr in steps:
                if sr.id in seen_step_ids:
                    continue
                seen_step_ids.add(sr.id)
                yield {
                    "event": "step",
                    "data": _step_detail(sr).model_dump_json(),
                }

            if status_now in _TERMINAL:
                terminal_iters_left -= 1
                if terminal_iters_left <= 0:
                    yield {"event": "done", "data": json.dumps({"run_id": run_id})}
                    break

            await asyncio.sleep(_SSE_POLL_SECONDS)

    return EventSourceResponse(gen())
