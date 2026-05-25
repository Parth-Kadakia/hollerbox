import { Link } from "react-router-dom";
import { useState } from "react";
import { listRuns } from "../api/client";
import StatusChip from "../components/StatusChip";
import { formatDuration, formatTimestamp, shortId } from "../lib/format";
import { useApi } from "../lib/useApi";
import { ErrorBox } from "./Dashboard";

export default function RunsPage() {
  const [filter, setFilter] = useState("");
  const runs = useApi(() => listRuns({ workflow: filter || undefined, limit: 100 }), [filter]);

  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Runs</h1>
          <p className="text-sm text-ink/60 mt-1">
            Most recent first. Click any run id to see the step trace.
          </p>
        </div>
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="filter by workflow name"
          className="rounded-md border border-ink/15 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-terracotta/40"
        />
      </header>

      {runs.error && <ErrorBox error={runs.error} />}
      {runs.loading && <p className="text-sm text-ink/50">loading…</p>}

      {runs.data && runs.data.length === 0 && (
        <p className="text-sm text-ink/50">no runs match</p>
      )}

      {runs.data && runs.data.length > 0 && (
        <div className="rounded-lg border border-ink/10 overflow-hidden">
          <table className="w-full text-sm">
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
                <tr key={r.id} className="border-t border-ink/5 hover:bg-ink/[0.02]">
                  <td className="px-4 py-2 font-mono text-xs">
                    <Link to={`/runs/${r.id}`} className="text-terracotta hover:underline">
                      {shortId(r.id)}
                    </Link>
                  </td>
                  <td className="px-4 py-2">{r.workflow_name}</td>
                  <td className="px-4 py-2"><StatusChip status={r.status} /></td>
                  <td className="px-4 py-2 text-ink/60">{r.trigger_kind}</td>
                  <td className="px-4 py-2 text-ink/60">{formatDuration(r.started_at, r.finished_at)}</td>
                  <td className="px-4 py-2 text-ink/60">{formatTimestamp(r.started_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
