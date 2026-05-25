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
            preview = _preview_value(last.output)
            return f"done — `{run.workflow.name}` finished. {preview}".rstrip()
        return f"done — `{run.workflow.name}` finished."
    if run.status == "failed":
        return f"that didn't work — `{run.workflow.name}` failed: {run.error or 'unknown error'}"
    if run.status == "cancelled":
        return f"cancelled — `{run.workflow.name}` was stopped."
    # shouldn't reach here for terminal states; defensive fall-through
    return f"`{run.workflow.name}` is {run.status}."


def _preview_value(output: dict) -> str:
    """Short preview of a step output for the result message."""
    if "text" in output and isinstance(output["text"], str):
        text = output["text"].strip()
        return text if len(text) <= 240 else text[:237] + "…"
    if "path" in output:
        return f"wrote {output['path']}"
    if "stdout" in output and isinstance(output["stdout"], str):
        out = output["stdout"].strip()
        return out if len(out) <= 240 else out[:237] + "…"
    return ""
