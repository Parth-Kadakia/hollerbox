"""Workflows CRUD.

Workflows are *upserted* by name from raw YAML text — POSTing the YAML is
the only way to create or update one. We parse + validate server-side
(via `load_workflow_from_source`) so the API returns a clean 422 with the
exact validation error if the YAML is malformed.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from api.deps import EngineSurface, get_surface
from api.schemas import (
    WorkflowDetail,
    WorkflowSummary,
    WorkflowUpsertRequest,
    WorkflowValidateRequest,
    WorkflowValidateResponse,
)
from hollerbox.core.templating import find_references
from hollerbox.core.workflow import WorkflowLoadError, load_workflow_from_source
from hollerbox.store import RunRow, WorkflowRow, repo, session_scope

router = APIRouter(prefix="/workflows", tags=["workflows"])


def _summary(row: WorkflowRow) -> WorkflowSummary:
    return WorkflowSummary(
        name=row.name,
        version=row.version,
        description=row.description,
        enabled=row.enabled,
        updated_at=row.updated_at,
    )


def _detail(row: WorkflowRow) -> WorkflowDetail:
    return WorkflowDetail(
        name=row.name,
        version=row.version,
        description=row.description,
        enabled=row.enabled,
        updated_at=row.updated_at,
        yaml_source=row.yaml_source,
    )


@router.get("", response_model=list[WorkflowSummary])
def list_workflows(surface: EngineSurface = Depends(get_surface)) -> list[WorkflowSummary]:
    with session_scope(surface.session_factory) as s:
        return [_summary(r) for r in repo.list_workflows(s)]


@router.post("/validate", response_model=WorkflowValidateResponse)
def validate_workflow(body: WorkflowValidateRequest) -> WorkflowValidateResponse:
    """Lint YAML without persisting. Returns 200 even on invalid input.

    The Editor page wires this to Monaco for live validation, so callers
    expect a structured `{valid, errors}` body rather than HTTP 4xx.
    """
    try:
        wf = load_workflow_from_source(body.yaml_source)
    except WorkflowLoadError as exc:
        return WorkflowValidateResponse(valid=False, errors=[exc.message])
    return WorkflowValidateResponse(
        valid=True,
        name=wf.name,
        step_ids=[s.id for s in wf.steps],
        references=sorted(set(find_references(wf.model_dump()))),
    )


@router.get("/{name}", response_model=WorkflowDetail)
def get_workflow(name: str, surface: EngineSurface = Depends(get_surface)) -> WorkflowDetail:
    with session_scope(surface.session_factory) as s:
        row = repo.get_workflow_by_name(s, name)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"workflow {name!r} not found")
        return _detail(row)


@router.put("/{name}", response_model=WorkflowDetail)
def upsert_workflow(
    name: str,
    body: WorkflowUpsertRequest,
    surface: EngineSurface = Depends(get_surface),
) -> WorkflowDetail:
    try:
        wf = load_workflow_from_source(body.yaml_source, name_hint=name)
    except WorkflowLoadError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.message) from exc
    if wf.name != name:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"workflow name in YAML ({wf.name!r}) does not match path ({name!r})",
        )
    with session_scope(surface.session_factory) as s:
        row = repo.upsert_workflow(s, wf, yaml_source=body.yaml_source)
        return _detail(row)


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workflow(name: str, surface: EngineSurface = Depends(get_surface)) -> None:
    with session_scope(surface.session_factory) as s:
        row = repo.get_workflow_by_name(s, name)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"workflow {name!r} not found")
        has_runs = s.scalar(select(RunRow.id).where(RunRow.workflow_id == row.id).limit(1))
        if has_runs is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"workflow {name!r} has run history; disable it instead of deleting",
            )
        s.delete(row)
