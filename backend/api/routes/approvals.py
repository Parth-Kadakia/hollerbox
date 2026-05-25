"""Approve / reject / cancel for a paused or queued run.

Approve and reject call `Runner.resume()` synchronously from the request
thread — they're fast (drive the remaining steps) and treating them as
synchronous keeps the API contract simple. A long resume could be moved
into the worker by re-queuing later if it becomes a problem.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from api.deps import EngineSurface, get_surface
from api.schemas import ApprovalDecision
from hollerbox.core.workflow import WorkflowLoadError, load_workflow_from_source
from hollerbox.store import repo, session_scope

router = APIRouter(prefix="/runs", tags=["approvals"])


def _resume_workflow(surface: EngineSurface, run_id: str) -> tuple[str, object]:
    """Find a paused run + reconstruct its workflow. Raises 404/409 as needed."""
    with session_scope(surface.session_factory) as s:
        run_row = repo.get_run(s, run_id)
        if run_row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"run {run_id!r} not found")
        if run_row.status != "paused":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"run is {run_row.status!r}, not paused — cannot approve/reject",
            )
        wf_row = run_row.workflow
        if wf_row is None or not wf_row.yaml_source:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "run has no associated workflow YAML — cannot resume",
            )
        yaml_source = wf_row.yaml_source
        wf_name = wf_row.name
        full_id = run_row.id

    try:
        wf = load_workflow_from_source(yaml_source, name_hint=wf_name)
    except WorkflowLoadError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, exc.message) from exc
    return full_id, wf


@router.post("/{run_id}/approve", response_model=ApprovalDecision)
def approve_run(
    run_id: str, surface: EngineSurface = Depends(get_surface)
) -> ApprovalDecision:
    full_id, wf = _resume_workflow(surface, run_id)
    result = surface.runner.resume(wf, run_id=full_id, approved=True)
    return ApprovalDecision(
        run_id=result.run_id,
        status=result.status,
        last_step_id=result.last_step_id,
        error=result.error,
    )


@router.post("/{run_id}/reject", response_model=ApprovalDecision)
def reject_run(
    run_id: str, surface: EngineSurface = Depends(get_surface)
) -> ApprovalDecision:
    full_id, wf = _resume_workflow(surface, run_id)
    result = surface.runner.resume(wf, run_id=full_id, approved=False)
    return ApprovalDecision(
        run_id=result.run_id,
        status=result.status,
        last_step_id=result.last_step_id,
        error=result.error,
    )


@router.post("/{run_id}/cancel", response_model=ApprovalDecision)
def cancel_run(
    run_id: str, surface: EngineSurface = Depends(get_surface)
) -> ApprovalDecision:
    with session_scope(surface.session_factory) as s:
        row = repo.get_run(s, run_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"run {run_id!r} not found")
        if row.status not in ("queued", "paused", "running"):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"run is {row.status!r} — only queued/paused/running can be cancelled",
            )
        full_id = row.id

    result = surface.runner.cancel(full_id, reason="cancelled via API")
    return ApprovalDecision(
        run_id=result.run_id,
        status=result.status,
        error=result.error,
    )
