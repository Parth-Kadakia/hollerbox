"""Turn engine state into chat messages.

Each helper here produces the text body for one logical message kind:
- `ack` — "on it…" right after a chat-triggered run is enqueued
- `approval_request` — "About to X. Reply YES to proceed, NO to cancel."
- `result` — terminal summary (success/failed/cancelled)

The strings are deliberately tight — chat UX is glance-able. The
approval card in the web UI shows the same `describe_effect` text in a
prettier form; CLI/SMS fall back to plain text.
"""

from __future__ import annotations

from hollerbox.store.models import RunRow, StepRunRow


def ack_message(workflow_name: str) -> str:
    return f"on it — running `{workflow_name}`."


def approval_request(step: StepRunRow) -> str:
    effect = step.logs[0] if step.logs else f"about to run step `{step.step_id}`."
    return (
        f"⚠️ {effect}\n\nReply **YES** to proceed, **NO** to cancel."
    )


def result_message(run: RunRow, steps: list[StepRunRow]) -> str:
    if run.status == "success":
        last = steps[-1] if steps else None
        if last is not None and last.output:
            # LLM-style steps put their answer in `text`. Use it as the
            # reply body verbatim — the user wants the whole thing, and
            # the chat bubble handles long content fine.
            text = last.output.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
            preview = _preview_value(last.output)
            if preview:
                return f"done — `{run.workflow.name}` finished. {preview}".rstrip()
        return f"done — `{run.workflow.name}` finished."
    if run.status == "failed":
        return f"that didn't work — `{run.workflow.name}` failed: {run.error or 'unknown error'}"
    if run.status == "cancelled":
        return f"cancelled — `{run.workflow.name}` was stopped."
    # shouldn't reach here for terminal states; defensive fall-through
    return f"`{run.workflow.name}` is {run.status}."


# Cap for non-text outputs (shell stdout, etc.) — these can be huge
# (e.g. `ls -R /`) and we don't want the chat thread eating MB of logs.
_PREVIEW_CHAR_LIMIT = 4000


def _preview_value(output: dict) -> str:
    """Short preview of a step output when there's no `text` field to
    use as the message body."""
    if isinstance(output.get("path"), str):
        return f"wrote {output['path']}"
    if isinstance(output.get("paths"), list) and output["paths"]:
        paths = [str(p) for p in output["paths"] if isinstance(p, str)]
        if len(paths) == 1:
            return f"wrote {paths[0]}"
        return f"wrote {len(paths)} files: {paths[0]} …"
    if "stdout" in output and isinstance(output["stdout"], str):
        out = output["stdout"].strip()
        if len(out) <= _PREVIEW_CHAR_LIMIT:
            return out
        return out[: _PREVIEW_CHAR_LIMIT - 1] + "…"
    return ""
