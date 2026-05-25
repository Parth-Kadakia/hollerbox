"""Runner — executes a workflow's steps sequentially with the §5 guarantees.

What the Runner is responsible for (BUILD_BRIEF §5, §9):

1. **Sequential execution** of `workflow.steps` (DAG executor lands later;
   the runner already operates against an ordered *plan* so swapping is
   local).
2. **Dry-run safety**: destructive steps in a dry-run run do NOT execute;
   instead their `describe_effect()` is recorded as a `dry_run` result.
3. **Approvals**: when a step requires confirmation (or it's destructive
   in a chat-triggered run), the runner records the step as
   `pending_approval`, marks the run `paused`, persists the context
   snapshot, and returns. A second `resume()` call (after approve/reject)
   continues or cancels the run.
4. **Error policy** per step: `stop | continue | retry`, with retry
   honoring `max_attempts` and `backoff_seconds` between attempts. Each
   attempt is its own `step_runs` row (the schema has `attempt: int`).
5. **Resumability**: state is persisted after every step transition so a
   crash or approval pause never loses progress.
6. **Secret hygiene**: `resolved_input` written to `step_runs` is the
   **redacted** form (`${secrets.*}` → ••••), per §10. Real secret values
   never enter the database.

What the Runner does NOT do (yet):
- DAG / parallel execution (Phase 1 is sequential by design)
- HTTP / SSE streaming (Phase 3 wraps this)
- Chat routing (Phase 5)
- LLM step (Phase 2 step type)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy.orm import Session, sessionmaker

from hollerbox import registry
from hollerbox.core.context import RunContext
from hollerbox.core.workflow import StepDefinition, Workflow
from hollerbox.providers.base import Provider
from hollerbox.store import repo, session_scope
from hollerbox.store.models import RunRow, StepRunRow, WorkflowRow
from hollerbox.steps.base import Step, StepResult


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class RunnerResult:
    """Lightweight, detached return value — useful for CLI + API callers.

    We deliberately don't hand back the ORM `RunRow` because session
    boundaries make that fragile. Re-fetch via repo if you need full state.
    """

    run_id: str
    status: str            # success | failed | paused | cancelled
    error: str | None = None
    last_step_id: str | None = None  # the step that caused failure / paused / completed last


class Runner:
    """Executes workflows against a session factory."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        providers: dict[str, Provider] | None = None,
    ) -> None:
        self._sf = session_factory
        self._providers = providers or {}

    # --------------------------- public API ---------------------------

    def execute(
        self,
        workflow: Workflow,
        *,
        inputs: dict[str, Any] | None = None,
        yaml_source: str = "",
        dry_run: bool = False,
        run_id: str | None = None,
        trigger_kind: str = "manual",
        chat_triggered: bool = False,
        settings: dict[str, Any] | None = None,
        secrets: dict[str, Any] | None = None,
    ) -> RunnerResult:
        """Start a fresh run."""
        effective_inputs = {**workflow.inputs, **(inputs or {})}
        ctx = RunContext.new(
            inputs=effective_inputs,
            secrets=secrets,
            settings=settings,
            run_id=run_id,
        )

        with session_scope(self._sf) as session:
            wf_row = repo.upsert_workflow(session, workflow, yaml_source=yaml_source)
            run_row = repo.create_run(
                session,
                workflow_id=wf_row.id,
                run_id=ctx.run["id"],
                inputs=effective_inputs,
                dry_run=dry_run,
                trigger_kind=trigger_kind,
            )
            persistent_run_id = run_row.id

        return self._drive(
            workflow=workflow,
            ctx=ctx,
            run_id=persistent_run_id,
            dry_run=dry_run,
            chat_triggered=chat_triggered,
            start_index=0,
            skip_approval_for=None,
        )

    def resume(
        self,
        workflow: Workflow,
        *,
        run_id: str,
        approved: bool,
        secrets: dict[str, Any] | None = None,
    ) -> RunnerResult:
        """Resume a paused run after an approval decision.

        If `approved`, the pending step is re-attempted and the workflow
        continues. If not, the run is marked `cancelled`.
        """
        with session_scope(self._sf) as session:
            run_row = repo.get_run(session, run_id)
            if run_row is None:
                raise ValueError(f"run {run_id!r} not found")
            if run_row.status != "paused":
                raise ValueError(
                    f"run {run_id!r} is {run_row.status!r}, not paused — cannot resume"
                )
            inputs = dict(run_row.inputs or {})
            snapshot = dict(run_row.context_snapshot or {})

            # Figure out where to resume from: the step the pause was recorded against.
            step_rows = list(repo.list_step_runs(session, run_id))
            pending = next(
                (r for r in reversed(step_rows) if r.status == "pending_approval"),
                None,
            )
            if pending is None:
                raise ValueError(
                    f"run {run_id!r} is paused but no pending_approval step row was found"
                )
            pending_step_id = pending.step_id
            dry_run = run_row.dry_run
            chat_triggered = run_row.trigger_kind == "chat"

        if not approved:
            with session_scope(self._sf) as session:
                run_row = repo.get_run(session, run_id)
                repo.update_run_status(
                    session,
                    run_row,
                    status="cancelled",
                    finished_at=_utc_now(),
                    error="rejected at approval prompt",
                )
            return RunnerResult(
                run_id=run_id,
                status="cancelled",
                error="rejected at approval prompt",
                last_step_id=pending_step_id,
            )

        # Approved → rebuild context, find resume index, drive from there.
        ctx = RunContext(
            inputs=inputs,
            secrets=dict(secrets or {}),
            settings=dict(snapshot.get("settings") or {}),
            run=dict(snapshot.get("run") or {"id": run_id}),
            steps=dict(snapshot.get("steps") or {}),
        )
        # Pending step has a recorded `pending_approval` entry in ctx.steps —
        # remove it so the resume cleanly re-records the real attempt.
        ctx.steps.pop(pending_step_id, None)

        try:
            start_index = next(
                i for i, s in enumerate(workflow.steps) if s.id == pending_step_id
            )
        except StopIteration as exc:
            raise ValueError(
                f"pending step {pending_step_id!r} not present in workflow {workflow.name!r}"
            ) from exc

        return self._drive(
            workflow=workflow,
            ctx=ctx,
            run_id=run_id,
            dry_run=dry_run,
            chat_triggered=chat_triggered,
            start_index=start_index,
            skip_approval_for=pending_step_id,
        )

    # --------------------------- internals ---------------------------

    def _drive(
        self,
        *,
        workflow: Workflow,
        ctx: RunContext,
        run_id: str,
        dry_run: bool,
        chat_triggered: bool,
        start_index: int,
        skip_approval_for: str | None,
    ) -> RunnerResult:
        with session_scope(self._sf) as session:
            run_row = repo.get_run(session, run_id)
            if run_row is None:
                raise ValueError(f"run {run_id!r} disappeared mid-flight")
            if run_row.started_at is None:
                repo.update_run_status(
                    session, run_row, status="running", started_at=_utc_now()
                )
            else:
                repo.update_run_status(session, run_row, status="running")

        last_step_id: str | None = None

        for defn in workflow.steps[start_index:]:
            last_step_id = defn.id
            step_cls = registry.get_step_class(defn.type)
            step = step_cls(defn)

            # --- Dry-run on destructive: don't execute, record describe_effect ---
            if dry_run and step.is_destructive:
                description = self._safe_describe(step, ctx)
                self._record_step(
                    run_id=run_id,
                    defn=defn,
                    ctx=ctx,
                    status="dry_run",
                    output={},
                    logs=[description],
                    error=None,
                    attempt=1,
                    started=_utc_now(),
                    finished=_utc_now(),
                )
                ctx.record_step(defn.id, status="dry_run", output={}, logs=[description])
                continue

            # --- Approval gate: pause and persist ---
            # Skipped in dry-run mode (there's nothing to actually approve)
            # and skipped for the one step that was just approved on resume.
            needs_approval = defn.requires_confirmation or (chat_triggered and step.is_destructive)
            if needs_approval and not dry_run and defn.id != skip_approval_for:
                description = self._safe_describe(step, ctx)
                self._record_step(
                    run_id=run_id,
                    defn=defn,
                    ctx=ctx,
                    status="pending_approval",
                    output={},
                    logs=[description],
                    error=None,
                    attempt=1,
                    started=_utc_now(),
                    finished=_utc_now(),
                )
                ctx.record_step(
                    defn.id, status="pending_approval", output={}, logs=[description]
                )
                with session_scope(self._sf) as session:
                    run_row = repo.get_run(session, run_id)
                    repo.update_run_status(
                        session,
                        run_row,
                        status="paused",
                        context_snapshot=ctx.snapshot(),
                    )
                return RunnerResult(
                    run_id=run_id, status="paused", last_step_id=defn.id
                )

            # --- Normal execution with retry/error policy ---
            last_result, last_error = self._run_with_retries(step, defn, ctx, run_id)

            ctx.record_step(
                defn.id,
                status=last_result.status,
                output=last_result.output,
                logs=last_result.logs,
                error=last_result.error,
            )

            if last_result.status == "failed":
                if defn.on_error == "stop" or defn.on_error == "retry":
                    # `retry` reaches here only after exhausting max_attempts.
                    with session_scope(self._sf) as session:
                        run_row = repo.get_run(session, run_id)
                        repo.update_run_status(
                            session,
                            run_row,
                            status="failed",
                            error=last_error or "step failed",
                            context_snapshot=ctx.snapshot(),
                            finished_at=_utc_now(),
                        )
                    return RunnerResult(
                        run_id=run_id,
                        status="failed",
                        error=last_error,
                        last_step_id=defn.id,
                    )
                # on_error == "continue" — workflow proceeds, this step's
                # failure is recorded but not fatal.

        # All steps completed (success, dry_run, or continue-on-fail).
        with session_scope(self._sf) as session:
            run_row = repo.get_run(session, run_id)
            repo.update_run_status(
                session,
                run_row,
                status="success",
                context_snapshot=ctx.snapshot(),
                finished_at=_utc_now(),
            )
        return RunnerResult(
            run_id=run_id, status="success", last_step_id=last_step_id
        )

    def _run_with_retries(
        self,
        step: Step,
        defn: StepDefinition,
        ctx: RunContext,
        run_id: str,
    ) -> tuple[StepResult, str | None]:
        """Run a step, honoring `on_error`/`max_attempts`/`backoff_seconds`.

        Records one `step_runs` row per attempt. Returns the final result
        plus the last error string (if any).
        """
        attempts = defn.max_attempts if defn.on_error == "retry" else 1
        last_result: StepResult | None = None
        last_error: str | None = None

        for attempt in range(1, attempts + 1):
            started = _utc_now()
            try:
                result = step.run(ctx)
            except Exception as exc:  # noqa: BLE001 — runner is the catch-all
                result = StepResult.failed(error=f"{type(exc).__name__}: {exc}")
            finished = _utc_now()

            self._record_step(
                run_id=run_id,
                defn=defn,
                ctx=ctx,
                status=result.status,
                output=result.output,
                logs=result.logs,
                error=result.error,
                attempt=attempt,
                started=started,
                finished=finished,
            )

            last_result = result
            last_error = result.error

            if result.status == "success":
                return result, None
            if attempt < attempts and defn.backoff_seconds > 0:
                time.sleep(defn.backoff_seconds)

        assert last_result is not None  # at least one iteration above
        return last_result, last_error

    def _record_step(
        self,
        *,
        run_id: str,
        defn: StepDefinition,
        ctx: RunContext,
        status: str,
        output: dict,
        logs: list[str],
        error: str | None,
        attempt: int,
        started: datetime,
        finished: datetime,
    ) -> StepRunRow:
        # Use the redacted form so persisted state never holds raw secrets.
        try:
            resolved_input = ctx.resolve_redacted(defn.config) if defn.config else {}
        except Exception:
            # If templates fail to resolve we still want a recorded row.
            resolved_input = dict(defn.config)

        with session_scope(self._sf) as session:
            return repo.record_step_run(
                session,
                run_id=run_id,
                step_id=defn.id,
                step_type=defn.type,
                status=status,
                resolved_input=resolved_input if isinstance(resolved_input, dict) else {},
                output=output if isinstance(output, dict) else {},
                logs=list(logs) if logs else [],
                error=error,
                attempt=attempt,
                started_at=started,
                finished_at=finished,
            )

    @staticmethod
    def _safe_describe(step: Step, ctx: RunContext) -> str:
        try:
            return step.describe_effect(ctx)
        except Exception as exc:  # noqa: BLE001
            return f"(describe_effect failed: {type(exc).__name__}: {exc})"
