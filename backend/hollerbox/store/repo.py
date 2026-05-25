"""Repository helpers — thin, intentional CRUD over SQLAlchemy.

The Runner doesn't talk to SQLAlchemy directly; it goes through these
functions so that swapping the store (Postgres, Redis cache) later is a
local change.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hollerbox.core.workflow import Workflow
from hollerbox.store.models import (
    ConversationRow,
    MessageRow,
    RunRow,
    SecretRow,
    SettingRow,
    StepRunRow,
    WorkflowRow,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


# --------------------------- workflows ---------------------------

def upsert_workflow(session: Session, workflow: Workflow, yaml_source: str) -> WorkflowRow:
    """Insert or update the workflow row for a given (name, workspace_id=NULL)."""
    existing = session.scalar(
        select(WorkflowRow).where(
            WorkflowRow.name == workflow.name,
            WorkflowRow.workspace_id.is_(None),
        )
    )
    if existing is None:
        row = WorkflowRow(
            name=workflow.name,
            version=workflow.version,
            description=workflow.description,
            yaml_source=yaml_source,
        )
        session.add(row)
        session.flush()
        return row

    existing.version = workflow.version
    existing.description = workflow.description
    existing.yaml_source = yaml_source
    existing.updated_at = _utc_now()
    session.flush()
    return existing


def get_workflow_by_name(session: Session, name: str) -> WorkflowRow | None:
    return session.scalar(
        select(WorkflowRow).where(
            WorkflowRow.name == name,
            WorkflowRow.workspace_id.is_(None),
        )
    )


def list_workflows(session: Session) -> Sequence[WorkflowRow]:
    return session.scalars(select(WorkflowRow).order_by(WorkflowRow.name)).all()


# --------------------------- runs ---------------------------

def create_run(
    session: Session,
    *,
    workflow_id: str,
    run_id: str,
    inputs: dict[str, Any],
    dry_run: bool,
    trigger_kind: str = "manual",
    conversation_id: str | None = None,
) -> RunRow:
    row = RunRow(
        id=run_id,
        workflow_id=workflow_id,
        status="queued",
        dry_run=dry_run,
        inputs=inputs,
        context_snapshot={},
        trigger_kind=trigger_kind,
        conversation_id=conversation_id,
    )
    session.add(row)
    session.flush()
    return row


def get_run(session: Session, run_id: str) -> RunRow | None:
    return session.get(RunRow, run_id)


def list_runs(
    session: Session,
    *,
    workflow_name: str | None = None,
    limit: int = 50,
) -> Sequence[RunRow]:
    stmt = select(RunRow).order_by(RunRow.created_at.desc()).limit(limit)
    if workflow_name:
        stmt = stmt.join(WorkflowRow).where(WorkflowRow.name == workflow_name)
    return session.scalars(stmt).all()


def update_run_status(
    session: Session,
    run: RunRow,
    *,
    status: str,
    error: str | None = None,
    context_snapshot: dict[str, Any] | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> RunRow:
    run.status = status
    if error is not None:
        run.error = error
    if context_snapshot is not None:
        run.context_snapshot = context_snapshot
    if started_at is not None:
        run.started_at = started_at
    if finished_at is not None:
        run.finished_at = finished_at
    session.flush()
    return run


# --------------------------- step_runs ---------------------------

def record_step_run(
    session: Session,
    *,
    run_id: str,
    step_id: str,
    step_type: str,
    status: str,
    resolved_input: dict[str, Any],
    output: dict[str, Any],
    logs: list[str],
    error: str | None,
    attempt: int,
    started_at: datetime,
    finished_at: datetime,
) -> StepRunRow:
    row = StepRunRow(
        run_id=run_id,
        step_id=step_id,
        step_type=step_type,
        status=status,
        resolved_input=resolved_input,
        output=output,
        logs=logs,
        error=error,
        attempt=attempt,
        started_at=started_at,
        finished_at=finished_at,
    )
    session.add(row)
    session.flush()
    return row


def list_step_runs(session: Session, run_id: str) -> Sequence[StepRunRow]:
    return session.scalars(
        select(StepRunRow)
        .where(StepRunRow.run_id == run_id)
        .order_by(StepRunRow.created_at)
    ).all()


# --------------------------- settings ---------------------------

def set_setting(session: Session, key: str, value: Any) -> SettingRow:
    existing = session.get(SettingRow, key)
    if existing is None:
        row = SettingRow(key=key, value=value)
        session.add(row)
        session.flush()
        return row
    existing.value = value
    session.flush()
    return existing


def get_setting(session: Session, key: str, default: Any = None) -> Any:
    row = session.get(SettingRow, key)
    return row.value if row is not None else default


# --------------------------- secrets ---------------------------

def upsert_secret(session: Session, *, name: str, ciphertext: bytes) -> SecretRow:
    existing = session.get(SecretRow, name)
    if existing is None:
        row = SecretRow(name=name, value_encrypted=ciphertext)
        session.add(row)
        session.flush()
        return row
    existing.value_encrypted = ciphertext
    existing.updated_at = _utc_now()
    session.flush()
    return existing


def get_secret_ciphertext(session: Session, name: str) -> bytes | None:
    row = session.get(SecretRow, name)
    return row.value_encrypted if row is not None else None


def list_secret_names(session: Session) -> list[str]:
    return list(session.scalars(select(SecretRow.name).order_by(SecretRow.name)).all())


def list_secrets_with_ciphertext(session: Session) -> list[tuple[str, bytes]]:
    rows = session.scalars(select(SecretRow).order_by(SecretRow.name)).all()
    return [(r.name, r.value_encrypted) for r in rows]


def delete_secret(session: Session, name: str) -> bool:
    row = session.get(SecretRow, name)
    if row is None:
        return False
    session.delete(row)
    session.flush()
    return True


# --------------------------- conversations ---------------------------

def create_conversation(session: Session, *, title: str = "") -> ConversationRow:
    row = ConversationRow(title=title)
    session.add(row)
    session.flush()
    return row


def get_conversation(session: Session, conv_id: str) -> ConversationRow | None:
    return session.get(ConversationRow, conv_id)


def list_conversations(session: Session, *, limit: int = 50) -> Sequence[ConversationRow]:
    return session.scalars(
        select(ConversationRow).order_by(ConversationRow.updated_at.desc()).limit(limit)
    ).all()


def add_message(
    session: Session,
    *,
    conversation_id: str,
    role: str,
    content: str,
    kind: str = "text",
    run_id: str | None = None,
) -> MessageRow:
    row = MessageRow(
        conversation_id=conversation_id,
        role=role,
        content=content,
        kind=kind,
        run_id=run_id,
    )
    session.add(row)
    # Touch the conversation so list ordering reflects activity.
    conv = session.get(ConversationRow, conversation_id)
    if conv is not None:
        conv.updated_at = _utc_now()
    session.flush()
    return row


def list_messages(session: Session, conversation_id: str) -> Sequence[MessageRow]:
    return session.scalars(
        select(MessageRow)
        .where(MessageRow.conversation_id == conversation_id)
        .order_by(MessageRow.created_at)
    ).all()
