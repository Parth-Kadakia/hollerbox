import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { deleteWorkflow, enqueueRun, listWorkflows } from "../api/client";
import { ErrorBox } from "./Dashboard";
import { useApi } from "../lib/useApi";
import { formatTimestamp } from "../lib/format";

export default function Workflows() {
  const navigate = useNavigate();
  const workflows = useApi(() => listWorkflows(), []);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(name: string, dryRun: boolean) {
    setBusy(name);
    setError(null);
    try {
      const run = await enqueueRun(name, { dry_run: dryRun });
      navigate(`/runs/${run.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  async function remove(name: string) {
    if (!confirm(`Delete workflow ${name}? This only works if it has no run history.`)) return;
    setBusy(name);
    setError(null);
    try {
      await deleteWorkflow(name);
      workflows.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Workflows</h1>
          <p className="text-sm text-ink/60 mt-1">
            YAML-defined automations registered in this install.
          </p>
        </div>
        <Link
          to="/workflows/new"
          className="rounded-md bg-terracotta px-3 py-1.5 text-sm font-medium text-white hover:bg-terracotta/90"
        >
          + New workflow
        </Link>
      </header>

      {workflows.error && <ErrorBox error={workflows.error} />}
      {error && <ErrorBox error={error} />}

      {workflows.loading && <p className="text-sm text-ink/50">loading…</p>}

      {workflows.data && workflows.data.length === 0 && (
        <div className="rounded-lg border border-dashed border-ink/15 px-6 py-10 text-center">
          <p className="text-sm text-ink/60">No workflows yet.</p>
          <Link
            to="/workflows/new"
            className="inline-block mt-3 text-sm text-terracotta hover:underline"
          >
            Author your first one →
          </Link>
        </div>
      )}

      {workflows.data && workflows.data.length > 0 && (
        <div className="rounded-lg border border-ink/10 overflow-x-auto">
          <table className="w-full text-sm min-w-[640px]">
            <thead className="bg-ink/[0.03] text-xs uppercase tracking-wider text-ink/50">
              <tr>
                <th className="text-left px-4 py-2 font-medium">Name</th>
                <th className="text-left px-4 py-2 font-medium">Description</th>
                <th className="text-left px-4 py-2 font-medium">Updated</th>
                <th className="text-right px-4 py-2 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {workflows.data.map((w) => (
                <tr
                  key={w.name}
                  className="border-t border-ink/5 hover:bg-ink/[0.02]"
                >
                  <td className="px-4 py-2 font-medium">{w.name}</td>
                  <td className="px-4 py-2 text-ink/60 max-w-md truncate">
                    {w.description || <span className="italic">no description</span>}
                  </td>
                  <td className="px-4 py-2 text-ink/60">
                    {formatTimestamp(w.updated_at)}
                  </td>
                  <td className="px-4 py-2 text-right space-x-2">
                    <button
                      disabled={busy === w.name}
                      onClick={() => run(w.name, false)}
                      className="text-xs text-terracotta hover:underline disabled:opacity-50"
                    >
                      Run
                    </button>
                    <button
                      disabled={busy === w.name}
                      onClick={() => run(w.name, true)}
                      className="text-xs text-ink/60 hover:underline disabled:opacity-50"
                    >
                      Dry-run
                    </button>
                    <Link
                      to={`/workflows/${encodeURIComponent(w.name)}/edit`}
                      className="text-xs text-ink/60 hover:underline"
                    >
                      Edit
                    </Link>
                    <button
                      disabled={busy === w.name}
                      onClick={() => remove(w.name)}
                      className="text-xs text-red-600 hover:underline disabled:opacity-50"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
