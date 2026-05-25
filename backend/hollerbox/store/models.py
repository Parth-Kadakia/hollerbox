"""SQLAlchemy 2.0 declarative models — the full §8 schema.

Phase 1 actually exercises only `workflows`, `runs`, `step_runs`, and
`settings`. The remaining tables (`schedules`, `conversations`,
`messages`, `secrets`, `push_subscriptions`) are defined now so later
phases don't have to evolve the schema sideways — every model carries
the `workspace_id NULL` placeholder for the eventual multi-tenant lift.

Migrations: deliberately none yet. Phase 1 uses `Base.metadata.create_all`
on a fresh SQLite file; Alembic gets wired in Phase 9 alongside the
Postgres option.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid_hex() -> str:
    return uuid.uuid4().hex


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Common declarative base for all HollerBox tables."""


# --------------------------- workflows ---------------------------

class WorkflowRow(Base):
    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid_hex)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    yaml_source: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now
    )
    workspace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    runs: Mapped[list[RunRow]] = relationship(back_populates="workflow")
    schedules: Mapped[list[ScheduleRow]] = relationship(back_populates="workflow")

    __table_args__ = (
        UniqueConstraint("name", "workspace_id", name="uq_workflows_name_per_workspace"),
    )


# --------------------------- runs / step_runs ---------------------------

class RunRow(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid_hex)
    workflow_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("workflows.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="queued"
    )  # queued|running|paused|success|failed|cancelled
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    context_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger_kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default="manual"
    )  # manual|cron|schedule|chat
    conversation_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("conversations.id"), nullable=True
    )
    workspace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )

    workflow: Mapped[WorkflowRow] = relationship(back_populates="runs")
    steps: Mapped[list[StepRunRow]] = relationship(
        back_populates="run", order_by="StepRunRow.created_at", cascade="all, delete-orphan"
    )


class StepRunRow(Base):
    __tablename__ = "step_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid_hex)
    run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("runs.id"), nullable=False
    )
    step_id: Mapped[str] = mapped_column(String(255), nullable=False)
    step_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # success|failed|skipped|dry_run|pending_approval
    resolved_input: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    output: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    logs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )

    run: Mapped[RunRow] = relationship(back_populates="steps")


# --------------------------- schedules (Phase 6) ---------------------------

class ScheduleRow(Base):
    __tablename__ = "schedules"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid_hex)
    workflow_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("workflows.id"), nullable=False
    )
    cron: Mapped[str | None] = mapped_column(String(64), nullable=True)
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )

    workflow: Mapped[WorkflowRow] = relationship(back_populates="schedules")


# --------------------------- conversations / messages (Phase 5) ---------------------------

class ConversationRow(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid_hex)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now
    )
    workspace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    messages: Mapped[list[MessageRow]] = relationship(
        back_populates="conversation",
        order_by="MessageRow.created_at",
        cascade="all, delete-orphan",
    )


class MessageRow(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid_hex)
    conversation_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("conversations.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user|assistant|system
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    run_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("runs.id"), nullable=True
    )
    kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default="text"
    )  # text|ack|approval_request|result|error
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )

    conversation: Mapped[ConversationRow] = relationship(back_populates="messages")


# --------------------------- secrets (Phase 2) ---------------------------

class SecretRow(Base):
    __tablename__ = "secrets"

    name: Mapped[str] = mapped_column(String(255), primary_key=True)
    value_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now
    )


# --------------------------- settings ---------------------------

class SettingRow(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=False)


# --------------------------- push_subscriptions (Phase 8) ---------------------------

class PushSubscriptionRow(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid_hex)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    keys: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )


# Convenience re-export for migrations / tests
ALL_TABLES = [
    WorkflowRow,
    RunRow,
    StepRunRow,
    ScheduleRow,
    ConversationRow,
    MessageRow,
    SecretRow,
    SettingRow,
    PushSubscriptionRow,
]
