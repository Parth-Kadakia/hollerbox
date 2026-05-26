// First-run + reauth prompt. Probes /api/health on mount; if it 401s and
// no token is stored (or the stored one is wrong), shows a fullscreen
// modal asking the user to paste the bearer token printed by the server
// on startup.

import { useEffect, useState } from "react";

import { API_BASE, getApiToken, setApiToken } from "../api/client";

interface Probe {
  state: "checking" | "ok" | "needs-token";
}

export default function TokenGate({ children }: { children: React.ReactNode }) {
  const [probe, setProbe] = useState<Probe>({ state: "checking" });
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function check(): Promise<void> {
    const token = getApiToken();
    try {
      const resp = await fetch(`${API_BASE}/health`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (resp.ok) {
        setProbe({ state: "ok" });
        return;
      }
      if (resp.status === 401) {
        setProbe({ state: "needs-token" });
        return;
      }
      // Anything else (5xx, network) — let the app render and surface
      // its own errors instead of blocking the whole UI.
      setProbe({ state: "ok" });
    } catch {
      // Server probably not running — let the app try too.
      setProbe({ state: "ok" });
    }
  }

  useEffect(() => {
    void check();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const trimmed = input.trim();
    if (!trimmed) return;
    // Try the token before saving so a wrong paste doesn't lock the user out.
    try {
      const resp = await fetch(`${API_BASE}/health`, {
        headers: { Authorization: `Bearer ${trimmed}` },
      });
      if (resp.ok) {
        setApiToken(trimmed);
        setProbe({ state: "ok" });
        setInput("");
        return;
      }
      if (resp.status === 401) {
        setError("That token didn't work. Double-check the server logs.");
        return;
      }
      setError(`Unexpected response (${resp.status}).`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  if (probe.state === "checking") {
    return (
      <div className="min-h-dvh bg-bone flex items-center justify-center">
        <div className="text-sm text-ink/50">connecting…</div>
      </div>
    );
  }

  if (probe.state === "needs-token") {
    return (
      <div className="min-h-dvh bg-bone flex items-center justify-center px-4">
        <form
          onSubmit={submit}
          className="w-full max-w-md rounded-lg border border-ink/10 bg-white/40 p-6 space-y-4"
        >
          <header className="space-y-1">
            <h1 className="text-xl font-semibold tracking-tight">HollerBox</h1>
            <p className="text-sm text-ink/60">
              The API is auth-protected. Paste the token from the server
              startup log — it'll only ask once per browser.
            </p>
          </header>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            type="password"
            placeholder="paste API token"
            autoFocus
            className="w-full rounded-md border border-ink/15 px-3 py-2 text-sm font-mono"
          />
          {error && (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">
              {error}
            </div>
          )}
          <button
            type="submit"
            className="w-full rounded-md bg-terracotta px-3 py-2 text-sm font-medium text-white hover:bg-terracotta/90"
          >
            Unlock
          </button>
          <p className="text-[11px] text-ink/40">
            The server logs the token at startup. Look for: <br />
            <code className="font-mono">HollerBox API is auth-protected. Token: ...</code>
          </p>
        </form>
      </div>
    );
  }

  return <>{children}</>;
}
