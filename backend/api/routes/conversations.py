"""Chat / conversation endpoints.

The conversation system itself lives in `hollerbox.conversation` — this
file is the HTTP seam. Each request builds a `ConversationSession` from
the EngineSurface so it picks up the latest provider configuration
(rotating a key takes effect on the next message, not the next restart).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from sse_starlette.sse import EventSourceResponse

from api._attachments import attachments_for_output
from api.deps import EngineSurface, get_surface
from api.schemas import (
    ChatMessage,
    ConversationCreateRequest,
    ConversationSummary,
    FileAttachment,
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


def _select_router_provider(
    surface: EngineSurface, preferred: str | None = None
) -> tuple[str, Provider] | None:
    """Pick the provider for the router.

    If the caller named one and we have it registered, use it. Otherwise
    fall back to the auto-preference order.
    """
    if preferred:
        p = surface.providers.get(preferred)
        if p is not None:
            return preferred, p
        # caller asked for a specific provider that isn't loaded — fall through
        # and let the default path handle "no provider configured" if nothing
        # works.
    for name in _ROUTER_PROVIDER_PREFERENCE:
        p = surface.providers.get(name)
        if p is not None:
            return name, p
    return None


def _build_session(
    surface: EngineSurface,
    *,
    provider_name: str | None = None,
    model: str | None = None,
) -> ConversationSession:
    sel = _select_router_provider(surface, preferred=provider_name)
    if sel is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "No text provider configured — set ANTHROPIC_API_KEY or OPENAI_API_KEY "
            "to use chat, or start Ollama locally.",
        )
    _name, provider = sel
    router_obj = Router(provider, model=model)
    return ConversationSession(
        surface.session_factory, runner=surface.runner, router=router_obj
    )


def _msg_to_schema(
    row: MessageRow,
    *,
    attachments: list[FileAttachment] | None = None,
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


def _attachments_for_run(surface: EngineSurface, run_id: str) -> list[FileAttachment]:
    """Every file produced by any successful step in this run."""
    with session_scope(surface.session_factory) as s:
        steps = list(repo.list_step_runs(s, run_id))
    out: list[FileAttachment] = []
    seen: set[str] = set()
    for step in steps:
        if step.status != "success":
            continue
        for att in attachments_for_output(step.output):
            if att.path in seen:
                continue
            seen.add(att.path)
            out.append(att)
    return out


def _build_messages(
    surface: EngineSurface, conv_id: str
) -> list[ChatMessage]:
    """List a conversation's messages with computed attachments."""
    with session_scope(surface.session_factory) as s:
        rows = list(repo.list_messages(s, conv_id))
    cache: dict[str, list[FileAttachment]] = {}
    out: list[ChatMessage] = []
    for row in rows:
        atts: list[FileAttachment] = []
        if row.run_id and row.kind == "result":
            atts = cache.setdefault(row.run_id, _attachments_for_run(surface, row.run_id))
        out.append(_msg_to_schema(row, attachments=atts))
    return out


# --------------------------- CRUD ---------------------------

def _derived_title(surface: EngineSurface, conv_id: str, stored: str) -> str:
    """Use the stored title if set, otherwise the first user message (trimmed).

    Computed on read so existing conversations get sensible titles without
    a migration. Empty thread → "New chat".
    """
    if stored:
        return stored
    with session_scope(surface.session_factory) as s:
        msgs = list(repo.list_messages(s, conv_id))
    for m in msgs:
        if m.role == "user" and m.content.strip():
            text = m.content.strip().replace("\n", " ")
            return text if len(text) <= 60 else text[:57] + "…"
    return "New chat"


@router.get("", response_model=list[ConversationSummary])
def list_conversations(
    surface: EngineSurface = Depends(get_surface),
) -> list[ConversationSummary]:
    with session_scope(surface.session_factory) as s:
        rows = repo.list_conversations(s)
        snapshots = [(r.id, r.title, r.created_at, r.updated_at) for r in rows]
    return [
        ConversationSummary(
            id=cid,
            title=_derived_title(surface, cid, raw_title),
            created_at=created,
            updated_at=updated,
        )
        for cid, raw_title, created, updated in snapshots
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
            id=row.id,
            title=row.title or "New chat",
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


@router.delete("/{conv_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conv_id: str, surface: EngineSurface = Depends(get_surface)
) -> None:
    """Delete a conversation + its messages. Linked runs are kept (detached)."""
    with session_scope(surface.session_factory) as s:
        if not repo.delete_conversation(s, conv_id):
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"conversation {conv_id!r} not found"
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
    session = _build_session(surface, provider_name=body.provider, model=body.model)
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
