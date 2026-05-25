import { Link } from "react-router-dom";
import { listRuns, listWorkflows } from "../api/client";
import StatusChip from "../components/StatusChip";
import { formatDuration, formatTimestamp, shortId } from "../lib/format";
import { useApi } from "../lib/useApi";

export default function Dashboard() {
  const runs = useApi(() => listRuns({ limit: 10 }), []);
  const workflows = useApi(() => listWorkflows(), []);

  const total = runs.data?.length ?? 0;
  const successes =
    runs.data?.filter((r) => r.status === "success").length ?? 0;
  const failures = runs.data?.filter((r) => r.status === "failed").length ?? 0;

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
        <p className="text-sm text-ink/60 mt-1">
          Recent activity from the engine. Everything you see here is local.
        </p>
      </header>

      <section className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Stat label="Workflows" value={workflows.data?.length ?? "—"} />
        <Stat label="Runs (last 10)" value={total} />
        <Stat
          label="Success rate"
          value={total ? `${Math.round((successes / total) * 100)}%` : "—"}
          hint={total ? `${successes} success · ${failures} failed` : undefined}
        />
      </section>

      <section className="space-y-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-lg font-medium">Recent runs</h2>
          <Link
            to="/runs"
            className="text-xs text-terracotta hover:underline"
          >
            See all →
          </Link>
        </div>

        {runs.loading && <p className="text-sm text-ink/50">loading…</p>}
        {runs.error && <ErrorBox error={runs.error} />}
        {runs.data && runs.data.length === 0 && (
          <p className="text-sm text-ink/50">
            no runs yet — kick one off from the{" "}
            <Link to="/workflows" className="text-terracotta hover:underline">
              Workflows
            </Link>{" "}
            page
          </p>
        )}
        {runs.data && runs.data.length > 0 && (
          <div className="rounded-lg border border-ink/10 overflow-x-auto">
            <table className="w-full text-sm min-w-[640px]">
              <thead className="bg-ink/[0.03] text-xs uppercase tracking-wider text-ink/50">
                <tr>
                  <th className="text-left px-4 py-2 font-medium">ID</th>
                  <th className="text-left px-4 py-2 font-medium">Workflow</th>
                  <th className="text-left px-4 py-2 font-medium">Status</th>
                  <th className="text-left px-4 py-2 font-medium">Trigger</th>
                  <th className="text-left px-4 py-2 font-medium">Duration</th>
                  <th className="text-left px-4 py-2 font-medium">Started</th>
                </tr>
              </thead>
              <tbody>
                {runs.data.map((r) => (
                  <tr
                    key={r.id}
                    className="border-t border-ink/5 hover:bg-ink/[0.02]"
                  >
                    <td className="px-4 py-2 font-mono text-xs">
                      <Link
                        to={`/runs/${r.id}`}
                        className="text-terracotta hover:underline"
                      >
                        {shortId(r.id)}
                      </Link>
                    </td>
                    <td className="px-4 py-2">{r.workflow_name}</td>
                    <td className="px-4 py-2">
                      <StatusChip status={r.status} />
                    </td>
                    <td className="px-4 py-2 text-ink/60">{r.trigger_kind}</td>
                    <td className="px-4 py-2 text-ink/60">
                      {formatDuration(r.started_at, r.finished_at)}
                    </td>
                    <td className="px-4 py-2 text-ink/60">
                      {formatTimestamp(r.started_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | number;
  hint?: string;
}) {
  return (
    <div className="rounded-lg border border-ink/10 px-5 py-4">
      <div className="text-xs uppercase tracking-wider text-ink/50">
        {label}
      </div>
      <div className="text-2xl font-semibold mt-1">{value}</div>
      {hint && <div className="text-xs text-ink/50 mt-1">{hint}</div>}
    </div>
  );
}

export function ErrorBox({ error }: { error: string }) {
  return (
    <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
      {error}
    </div>
  );
}
