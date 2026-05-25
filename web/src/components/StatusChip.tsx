import type { RunStatus, StepStatus } from "../api/types";

const COLORS: Record<RunStatus | StepStatus, string> = {
  queued: "bg-ink/10 text-ink/70",
  running: "bg-blue-100 text-blue-800",
  paused: "bg-amber-100 text-amber-800",
  success: "bg-emerald-100 text-emerald-800",
  failed: "bg-red-100 text-red-800",
  cancelled: "bg-fuchsia-100 text-fuchsia-800",
  skipped: "bg-ink/10 text-ink/60",
  dry_run: "bg-cyan-100 text-cyan-800",
  pending_approval: "bg-amber-100 text-amber-800",
};

export default function StatusChip({
  status,
}: {
  status: RunStatus | StepStatus;
}) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
        COLORS[status] ?? "bg-ink/10 text-ink/60"
      }`}
    >
      {status}
    </span>
  );
}
