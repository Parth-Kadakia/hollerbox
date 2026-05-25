"""Pydantic request/response models for the HollerBox HTTP API.

Routes own the engine→schema translation so the engine itself never
imports anything from `api/`. Field types here mirror §8 columns; the
write-only secret pattern (`{"set": true}`) is enforced via dedicated
schemas with no `value` field on output.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# --------------------------- workflows ---------------------------

class WorkflowSummary(BaseModel):
    """List-view fields — heavier `yaml_source` is fetched per-detail."""

    name: str
    version: int
    description: str
    enabled: bool
    updated_at: datetime


class WorkflowDetail(WorkflowSummary):
    yaml_source: str


class WorkflowUpsertRequest(BaseModel):
    """PUT /workflows/{name} body — YAML text in, parsed + validated server-side."""

    model_config = ConfigDict(extra="forbid")
    yaml_source: str = Field(min_length=1)


class WorkflowValidateRequest(BaseModel):
    """POST /workflows/validate body — lint YAML without persisting."""

    model_config = ConfigDict(extra="forbid")
    yaml_source: str = Field(min_length=1)


class WorkflowValidateResponse(BaseModel):
    """Result of a `validate` call. `errors` is empty when `valid` is True."""

    valid: bool
    name: str | None = None
    step_ids: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


# --------------------------- runs / step runs ---------------------------

class StepRunDetail(BaseModel):
    step_id: str
    step_type: str
    status: str
    resolved_input: dict[str, Any]
    output: dict[str, Any]
    logs: list[str]
    error: str | None
    attempt: int
    started_at: datetime | None
    finished_at: datetime | None


class RunSummary(BaseModel):
    id: str
    workflow_name: str
    status: str
    dry_run: bool
    trigger_kind: str
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None
    created_at: datetime


class RunDetail(RunSummary):
    inputs: dict[str, Any]
    steps: list[StepRunDetail]


class RunRequest(BaseModel):
    """POST /workflows/{name}/run body."""

    model_config = ConfigDict(extra="forbid")
    inputs: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = False
    trigger_kind: Literal["manual", "chat"] = "manual"


# --------------------------- approvals ---------------------------

class ApprovalDecision(BaseModel):
    """Returned from approve/reject/cancel — same shape as Runner result."""

    run_id: str
    status: str
    last_step_id: str | None = None
    error: str | None = None


# --------------------------- settings ---------------------------

class SettingValue(BaseModel):
    """Settings are JSON-typed; wrap so we can extend later without churn."""

    model_config = ConfigDict(extra="forbid")
    value: Any


# --------------------------- secrets (WRITE-ONLY) ---------------------------

class SecretPresence(BaseModel):
    """List response — names only, no values. §10."""

    name: str
    set: Literal[True] = True


class SecretWriteRequest(BaseModel):
    """PUT /secrets/{name} body — value in, never out."""

    model_config = ConfigDict(extra="forbid")
    value: str = Field(min_length=1)


# --------------------------- conversations / messages ---------------------------

class ConversationSummary(BaseModel):
    """List-view shape for a conversation."""

    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = ""


class ChatMessage(BaseModel):
    """One persisted message in a conversation."""

    id: str
    conversation_id: str
    role: Literal["user", "assistant", "system"]
    content: str
    kind: Literal["text", "ack", "approval_request", "result", "error"]
    run_id: str | None
    created_at: datetime


class SendMessageRequest(BaseModel):
    """POST /conversations/{id}/messages body."""

    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1)


class SendMessageResponse(BaseModel):
    """Return for POST — caller can subscribe to SSE for the rest."""

    user_message_id: str
    assistant_message_ids: list[str]
    messages: list[ChatMessage]
