"""Chat / conversation endpoints.

The conversation system itself lives in `hollerbox.conversation` — this
file is the HTTP seam. Each request builds a `ConversationSession` from
the EngineSurface so it picks up the latest provider configuration
(rotating a key takes effect on the next message, not the next restart).
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, status
from sse_starlette.sse import EventSourceResponse

from api.deps import EngineSurface, get_surface
from api.schemas import (
    ChatMessage,
    ConversationCreateRequest,
    ConversationSummary,
    MessageAttachment,
    SendMessageRequest,
    SendMessageResponse,
)
from hollerbox.conversation import ConversationSession, Router
from hollerbox.providers.base import Provider
from hollerbox.store import MessageRow, repo, session_scope

router = APIRouter(prefix="/conversations", tags=["chat"])

# Preference order — first text provider whose name is present wins.
_ROUTER_PROVIDER_PREFERENCE = ["anthropic", "openai", "ollama", "mock"]
_SSE_POLL_SECONDS = 0.25


def _select_router_provider(surface: EngineSurface) -> Provider | None:
    for name in _ROUTER_PROVIDER_PREFERENCE:
        p = surface.providers.get(name)
        if p is not None:
            return p
    return None


def _build_session(surface: EngineSurface) -> ConversationSession:
    provider = _select_router_provider(surface)
    if provider is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "No text provider configured — set ANTHROPIC_API_KEY or OPENAI_API_KEY "
            "to use chat, or start Ollama locally.",
        )
    router_obj = Router(provider)
    return ConversationSession(
        surface.session_factory, runner=surface.runner, router=router_obj
    )


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def _msg_to_schema(
    row: MessageRow,
    *,
    attachments: list[MessageAttachment] | None = None,
) -> ChatMessage:
    return ChatMessage(
        id=row.id,
        conversation_id=row.conversation_id,
        role=row.role,  # type: ignore[arg-type]
        content=row.content,
        kind=row.kind,  # type: ignore[arg-type]
        run_id=row.run_id,
        created_at=row.created_at,
        attachments=attachments or [],
    )


def _attachments_for_run(surface: EngineSurface, run_id: str) -> list[MessageAttachment]:
    """Pull every file path out of a run's step outputs and turn it into
    an attachment record the UI can render."""
    out: list[MessageAttachment] = []
    seen_paths: set[str] = set()
    with session_scope(surface.session_factory) as s:
        steps = list(repo.list_step_runs(s, run_id))
    for step in steps:
        if step.status != "success":
            continue
        candidates: list[str] = []
        for key in ("path", "out_path", "output_path"):
            v = (step.output or {}).get(key)
            if isinstance(v, str):
                candidates.append(v)
        for key in ("paths", "files", "outputs"):
            v = (step.output or {}).get(key)
            if isinstance(v, list):
                for item in v:
                    if isinstance(item, str):
                        candidates.append(item)
        for raw in candidates:
            p = Path(raw).expanduser()
            norm = str(p.resolve(strict=False))
            if norm in seen_paths:
                continue
            seen_paths.add(norm)
            is_image = p.suffix.lower() in _IMAGE_EXTS or (
                (mimetypes.guess_type(p.name)[0] or "").startswith("image/")
            )
            size = p.stat().st_size if p.is_file() else None
            out.append(
                MessageAttachment(
                    kind="image" if is_image else "file",
                    path=norm,
                    url=f"/files?path={quote(norm)}",
                    name=p.name,
                    size_bytes=size,
                )
            )
    return out


def _build_messages(
    surface: EngineSurface, conv_id: str
) -> list[ChatMessage]:
    """List a conversation's messages with computed attachments."""
    with session_scope(surface.session_factory) as s:
        rows = list(repo.list_messages(s, conv_id))
    cache: dict[str, list[MessageAttachment]] = {}
    out: list[ChatMessage] = []
    for row in rows:
        atts: list[MessageAttachment] = []
        if row.run_id and row.kind == "result":
            atts = cache.setdefault(row.run_id, _attachments_for_run(surface, row.run_id))
        out.append(_msg_to_schema(row, attachments=atts))
    return out


# --------------------------- CRUD ---------------------------

@router.get("", response_model=list[ConversationSummary])
def list_conversations(
    surface: EngineSurface = Depends(get_surface),
) -> list[ConversationSummary]:
    with session_scope(surface.session_factory) as s:
        rows = repo.list_conversations(s)
        return [
            ConversationSummary(
                id=r.id, title=r.title, created_at=r.created_at, updated_at=r.updated_at
            )
            for r in rows
        ]


@router.post(
    "",
    response_model=ConversationSummary,
    status_code=status.HTTP_201_CREATED,
)
def create_conversation(
    body: ConversationCreateRequest,
    surface: EngineSurface = Depends(get_surface),
) -> ConversationSummary:
    with session_scope(surface.session_factory) as s:
        row = repo.create_conversation(s, title=body.title)
        return ConversationSummary(
            id=row.id, title=row.title, created_at=row.created_at, updated_at=row.updated_at
        )


@router.get("/{conv_id}/messages", response_model=list[ChatMessage])
def list_messages(
    conv_id: str, surface: EngineSurface = Depends(get_surface)
) -> list[ChatMessage]:
    with session_scope(surface.session_factory) as s:
        conv = repo.get_conversation(s, conv_id)
        if conv is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"conversation {conv_id!r} not found")
    return _build_messages(surface, conv_id)


# --------------------------- send ---------------------------

@router.post("/{conv_id}/messages", response_model=SendMessageResponse)
def send_message(
    conv_id: str,
    body: SendMessageRequest,
    surface: EngineSurface = Depends(get_surface),
) -> SendMessageResponse:
    session = _build_session(surface)
    try:
        turn = session.post_user_message(conv_id, body.content)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — surface provider failures as 502s
        # An Ollama daemon offline, an upstream rate-limit, etc. — record an
        # error message in the thread so the user sees it, and return 502.
        with session_scope(surface.session_factory) as s:
            repo.add_message(
                s,
                conversation_id=conv_id,
                role="assistant",
                content=(
                    f"The router couldn't reach the LLM provider: {exc}. "
                    "Check that your API key is correct, or start Ollama locally."
                ),
                kind="error",
            )
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    # Snapshot the whole thread so the client can render without a second roundtrip.
    msgs = _build_messages(surface, conv_id)
    return SendMessageResponse(
        user_message_id=turn.user_message_id,
        assistant_message_ids=turn.assistant_message_ids,
        messages=msgs,
    )


# --------------------------- SSE ---------------------------

@router.get("/{conv_id}/events")
async def stream_conversation_events(
    conv_id: str, surface: EngineSurface = Depends(get_surface)
) -> EventSourceResponse:
    """Stream new messages as the worker drives runs.

    The conversation `refresh()` materializes `approval_request` /
    `result` / `error` messages from current run state. We call it on
    every tick and emit `message` events for anything the client hasn't
    seen yet. Closes when there are no live runs left and the client has
    received every persisted message.
    """
    # Validate the conversation exists before opening the long-poll.
    with session_scope(surface.session_factory) as s:
        if repo.get_conversation(s, conv_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"conversation {conv_id!r} not found")

    session = _build_session(surface)

    async def gen() -> AsyncIterator[dict[str, str]]:
        seen_ids: set[str] = set()
        idle_ticks = 0
        while True:
            # Reconcile message thread with current run state.
            session.refresh(conv_id)

            with session_scope(surface.session_factory) as s:
                msg_rows = list(repo.list_messages(s, conv_id))
                # Are there any non-terminal runs the user is waiting on?
                from sqlalchemy import select

                from hollerbox.store import RunRow

                active = s.scalar(
                    select(RunRow.id)
                    .where(RunRow.conversation_id == conv_id)
                    .where(RunRow.status.in_(("queued", "running", "paused")))
                    .limit(1)
                )

            new_rows = [m for m in msg_rows if m.id not in seen_ids]
            new_msgs = (
                [m for m in _build_messages(surface, conv_id) if m.id in {r.id for r in new_rows}]
                if new_rows
                else []
            )
            for m in new_msgs:
                seen_ids.add(m.id)
                yield {
                    "event": "message",
                    "data": m.model_dump_json(),
                }

            if active is None and not new_msgs:
                idle_ticks += 1
            else:
                idle_ticks = 0

            # After ~3 seconds of nothing happening with no active run, close.
            if idle_ticks * _SSE_POLL_SECONDS >= 3.0:
                yield {"event": "done", "data": json.dumps({"conversation_id": conv_id})}
                break

            await asyncio.sleep(_SSE_POLL_SECONDS)

    return EventSourceResponse(gen())
