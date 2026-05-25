import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  approveRun,
  cancelRun,
  getRun,
  rejectRun,
  streamRunEvents,
} from "../api/client";
import type { RunDetail, RunStatus, StepRunDetail } from "../api/types";
import Attachment from "../components/Attachment";
import StatusChip from "../components/StatusChip";
import { formatDuration, formatTimestamp } from "../lib/format";
import { ErrorBox } from "./Dashboard";

const TERMINAL: RunStatus[] = ["success", "failed", "cancelled"];

export default function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>();
  const [run, setRun] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Initial fetch.
  useEffect(() => {
    if (!runId) return;
    setRun(null);
    setError(null);
    getRun(runId).then(setRun).catch((e: unknown) =>
      setError(e instanceof Error ? e.message : String(e)),
    );
  }, [runId]);

  // Live SSE while the run is non-terminal. Each event refetches the
  // detail — simpler than reconciling partial state, and the round-trip
  // is sub-millisecond against local SQLite.
  useEffect(() => {
    if (!runId || !run) return;
    if (TERMINAL.includes(run.status)) return;
    const es = streamRunEvents(runId, () => {
      getRun(runId).then(setRun).catch(() => {});
    });
    return () => es.close();
  }, [runId, run]);

  async function decide(action: "approve" | "reject" | "cancel") {
    if (!runId) return;
    setBusy(true);
    setError(null);
    try {
      if (action === "approve") await approveRun(runId);
      else if (action === "reject") await rejectRun(runId);
      else await cancelRun(runId);
      const fresh = await getRun(runId);
      setRun(fresh);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (error && !run) return <ErrorBox error={error} />;
  if (!run) return <p className="text-sm text-ink/50">loading run…</p>;

  const isPaused = run.status === "paused";
  const isLive = !TERMINAL.includes(run.status);
  const hasPendingStep = run.steps.some(
    (s) => s.status === "pending_approval",
  );

  return (
    <div className="space-y-6">
      <header className="space-y-3">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-semibold tracking-tight">
            {run.workflow_name}
          </h1>
          <StatusChip status={run.status} />
          {run.dry_run && (
            <span className="text-xs uppercase tracking-wider px-2 py-0.5 rounded bg-cyan-100 text-cyan-800">
              dry-run
            </span>
          )}
          {isLive && (
            <span className="text-xs text-ink/50">
              <Pulse /> live
            </span>
          )}
        </div>
        <div className="font-mono text-xs text-ink/50">{run.id}</div>
        <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-ink/60">
          <Meta label="started" value={formatTimestamp(run.started_at)} />
          <Meta label="finished" value={formatTimestamp(run.finished_at)} />
          <Meta
            label="duration"
            value={formatDuration(run.started_at, run.finished_at)}
          />
          <Meta label="trigger" value={run.trigger_kind} />
        </div>
        {run.error && (
          <p className="text-sm text-red-700">error: {run.error}</p>
        )}
      </header>

      {error && <ErrorBox error={error} />}

      {isPaused && hasPendingStep && (
        <ApprovalCard
          step={run.steps.find((s) => s.status === "pending_approval")!}
          busy={busy}
          onApprove={() => decide("approve")}
          onReject={() => decide("reject")}
        />
      )}

      {(run.status === "queued" || run.status === "running") && (
        <div className="rounded-md border border-ink/10 px-4 py-2 text-xs text-ink/60 flex items-center gap-3">
          <Pulse /> waiting for the worker to finish this run…
          <button
            disabled={busy}
            onClick={() => decide("cancel")}
            className="ml-auto text-red-600 hover:underline disabled:opacity-50"
          >
            Cancel
          </button>
        </div>
      )}

      <section className="space-y-3">
        <h2 className="text-lg font-medium">Steps</h2>
        {run.steps.length === 0 && (
          <p className="text-sm text-ink/50">no steps recorded yet</p>
        )}
        <ol className="space-y-3">
          {run.steps.map((s, i) => (
            <StepCard key={`${s.step_id}-${s.attempt}-${i}`} index={i + 1} step={s} />
          ))}
        </ol>
      </section>

      <section className="rounded-lg border border-ink/10 p-4">
        <div className="text-[10px] uppercase tracking-wider text-ink/50 mb-2">
          Inputs
        </div>
        <pre className="text-xs font-mono whitespace-pre-wrap break-all text-ink/70">
          {JSON.stringify(run.inputs, null, 2)}
        </pre>
      </section>
    </div>
  );
}

function Pulse() {
  return (
    <span className="relative inline-flex w-2 h-2 mr-1 align-middle">
      <span className="absolute inset-0 rounded-full bg-blue-500 opacity-75 animate-ping" />
      <span className="relative inline-flex w-2 h-2 rounded-full bg-blue-500" />
    </span>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <span>
      <span className="text-ink/40">{label}:</span> {value}
    </span>
  );
}

function ApprovalCard({
  step,
  busy,
  onApprove,
  onReject,
}: {
  step: StepRunDetail;
  busy: boolean;
  onApprove: () => void;
  onReject: () => void;
}) {
  const effect = step.logs[0] ?? "(no preview available)";
  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50 p-5 space-y-3">
      <div className="flex items-center gap-2">
        <span className="text-amber-900 font-medium">
          Approval required for step <code>{step.step_id}</code>
        </span>
      </div>
      <p className="text-sm text-amber-900/90">{effect}</p>
      <div className="flex gap-2">
        <button
          disabled={busy}
          onClick={onApprove}
          className="rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
        >
          Approve & continue
        </button>
        <button
          disabled={busy}
          onClick={onReject}
          className="rounded-md border border-amber-300 px-3 py-1.5 text-sm font-medium text-amber-900 hover:bg-amber-100 disabled:opacity-50"
        >
          Reject
        </button>
      </div>
    </div>
  );
}

function StepCard({ index, step }: { index: number; step: StepRunDetail }) {
  const dur = formatDuration(step.started_at, step.finished_at);
  return (
    <li className="rounded-lg border border-ink/10">
      <header className="flex items-center justify-between px-4 py-2 bg-ink/[0.02]">
        <div className="flex items-center gap-3">
          <span className="text-xs text-ink/40 w-5">{index}.</span>
          <span className="font-medium">{step.step_id}</span>
          <span className="text-xs text-ink/50">{step.step_type}</span>
          <StatusChip status={step.status} />
          {step.attempt > 1 && (
            <span className="text-xs text-ink/50">attempt {step.attempt}</span>
          )}
        </div>
        <span className="text-xs text-ink/50">{dur}</span>
      </header>
      <div className="px-4 py-3 space-y-3 text-xs">
        {step.error && (
          <p className="text-red-700">error: {step.error}</p>
        )}
        {(step.attachments ?? []).length > 0 && (
          <div className="space-y-2">
            {(step.attachments ?? []).map((a) => (
              <Attachment key={a.path} att={a} />
            ))}
          </div>
        )}
        {step.logs.length > 0 && (
          <details>
            <summary className="cursor-pointer text-ink/60 hover:text-ink">
              logs ({step.logs.length})
            </summary>
            <pre className="mt-2 font-mono text-[11px] whitespace-pre-wrap break-all text-ink/70">
              {step.logs.join("\n")}
            </pre>
          </details>
        )}
        {Object.keys(step.output ?? {}).length > 0 && (
          <details open>
            <summary className="cursor-pointer text-ink/60 hover:text-ink">
              output
            </summary>
            <pre className="mt-2 font-mono text-[11px] whitespace-pre-wrap break-all text-ink/70">
              {JSON.stringify(step.output, null, 2)}
            </pre>
          </details>
        )}
      </div>
    </li>
  );
}
