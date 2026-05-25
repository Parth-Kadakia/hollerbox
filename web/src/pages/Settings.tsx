import { useState } from "react";
import {
  deleteSecret,
  listProviders,
  listSecrets,
  setSecret,
} from "../api/client";
import type { ProviderStatus } from "../api/types";
import { useApi } from "../lib/useApi";
import { ErrorBox } from "./Dashboard";

const SUGGESTED_KEYS = [
  "ANTHROPIC_API_KEY",
  "OPENAI_API_KEY",
  "GEMINI_API_KEY",
];

export default function SettingsPage() {
  const providers = useApi(() => listProviders(), []);
  const secrets = useApi(() => listSecrets(), []);
  const [error, setError] = useState<string | null>(null);

  return (
    <div className="space-y-10">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="text-sm text-ink/60 mt-1">
          LLM providers, API keys, and engine defaults — all stored locally.
        </p>
      </header>

      {error && <ErrorBox error={error} />}

      <section className="space-y-3">
        <h2 className="text-lg font-medium">Providers</h2>
        {providers.error && <ErrorBox error={providers.error} />}
        {providers.loading && <p className="text-sm text-ink/50">loading…</p>}
        {providers.data && (
          <div className="grid md:grid-cols-2 gap-4">
            <ProviderColumn title="Text (llm step)" items={providers.data.text} />
            <ProviderColumn title="Image (image step)" items={providers.data.image} />
          </div>
        )}
      </section>

      <section className="space-y-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-lg font-medium">Secrets</h2>
          <span className="text-xs text-ink/40">
            stored encrypted · values never displayed
          </span>
        </div>

        {secrets.error && <ErrorBox error={secrets.error} />}

        <SecretsForm
          existing={(secrets.data ?? []).map((s) => s.name)}
          onSaved={() => {
            secrets.reload();
            providers.reload();
            setError(null);
          }}
          onError={setError}
        />

        {secrets.data && secrets.data.length > 0 && (
          <ul className="rounded-lg border border-ink/10 divide-y divide-ink/5">
            {secrets.data.map((s) => (
              <li key={s.name} className="flex items-center justify-between px-4 py-2 text-sm">
                <span className="font-mono">
                  {s.name} <span className="text-ink/40">····</span>
                </span>
                <button
                  onClick={async () => {
                    if (!confirm(`Delete secret ${s.name}?`)) return;
                    try {
                      await deleteSecret(s.name);
                      secrets.reload();
                      providers.reload();
                    } catch (e) {
                      setError(e instanceof Error ? e.message : String(e));
                    }
                  }}
                  className="text-xs text-red-600 hover:underline"
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function ProviderColumn({ title, items }: { title: string; items: ProviderStatus[] }) {
  return (
    <div className="rounded-lg border border-ink/10 overflow-hidden">
      <div className="bg-ink/[0.03] px-4 py-2 text-xs uppercase tracking-wider text-ink/50">
        {title}
      </div>
      <ul className="divide-y divide-ink/5">
        {items.map((p) => (
          <li key={p.name} className="px-4 py-2.5 flex items-center justify-between text-sm">
            <span className="font-medium">{p.name}</span>
            <span className="flex items-center gap-2">
              <StatusBadge status={p.status} />
              <span className="text-xs text-ink/50">{p.detail}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function StatusBadge({ status }: { status: ProviderStatus["status"] }) {
  const styles: Record<ProviderStatus["status"], string> = {
    ready: "bg-emerald-100 text-emerald-800",
    "missing-sdk": "bg-amber-100 text-amber-800",
    "no-key": "bg-ink/10 text-ink/60",
  };
  return (
    <span className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${styles[status]}`}>
      {status}
    </span>
  );
}

function SecretsForm({
  existing,
  onSaved,
  onError,
}: {
  existing: string[];
  onSaved: () => void;
  onError: (e: string) => void;
}) {
  const [name, setName] = useState(SUGGESTED_KEYS[0]);
  const [custom, setCustom] = useState("");
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const isCustom = name === "__custom__";
  const finalName = isCustom ? custom.trim() : name;
  const isOverwrite = existing.includes(finalName);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!finalName || !value) return;
    setBusy(true);
    try {
      await setSecret(finalName, value);
      setValue("");
      if (isCustom) setCustom("");
      onSaved();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="rounded-lg border border-ink/10 p-4 grid grid-cols-1 gap-3 md:grid-cols-[1fr_1fr_auto] md:items-end">
      <label className="text-xs uppercase tracking-wider text-ink/50 space-y-1">
        Name
        <select
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-full rounded-md border border-ink/15 px-3 py-1.5 text-sm font-mono normal-case tracking-normal focus:outline-none focus:ring-2 focus:ring-terracotta/40"
        >
          {SUGGESTED_KEYS.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
          <option value="__custom__">custom…</option>
        </select>
        {isCustom && (
          <input
            value={custom}
            onChange={(e) => setCustom(e.target.value)}
            placeholder="MY_SECRET"
            className="w-full mt-2 rounded-md border border-ink/15 px-3 py-1.5 text-sm font-mono normal-case tracking-normal focus:outline-none focus:ring-2 focus:ring-terracotta/40"
          />
        )}
      </label>
      <label className="text-xs uppercase tracking-wider text-ink/50 space-y-1">
        Value
        <input
          type="password"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="sk-…"
          className="w-full rounded-md border border-ink/15 px-3 py-1.5 text-sm font-mono normal-case tracking-normal focus:outline-none focus:ring-2 focus:ring-terracotta/40"
        />
      </label>
      <button
        type="submit"
        disabled={busy || !finalName || !value}
        className="rounded-md bg-terracotta px-4 py-1.5 text-sm font-medium text-white hover:bg-terracotta/90 disabled:opacity-40"
      >
        {busy ? "saving…" : isOverwrite ? "Rotate" : "Save"}
      </button>
    </form>
  );
}
