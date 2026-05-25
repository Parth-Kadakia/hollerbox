<p align="center">
  <img src="assets/logo.png" alt="HollerBox" width="120" />
</p>

<h1 align="center">HollerBox</h1>

<p align="center">
  <em>Local-first, chat-driven AI workflow engine.</em><br/>
  <em>Open source. Runs on your machine. Always yours.</em>
</p>

---

> **Status:** Phase 2 complete — engine + CLI run YAML workflows end-to-end with dry-run, approval pauses, retry, persistence, an encrypted secret store, and an `llm` step that drives Anthropic / OpenAI / Ollama (plus a deterministic `mock` for tests). HTTP API, web UI, chat, and scheduling are still ahead. See [Roadmap](#roadmap).

## What is it?

HollerBox is a local-first system you talk to — like a messaging app — to get
things done. You text it ("summarize my unread email", "run my nightly file
sync", "what did the news digest find this morning?"); it figures out which
workflow you mean, runs it, asks for confirmation before anything destructive
("reply **YES** to proceed"), and replies in the thread.

Under the hood it's a workflow engine that runs typed, inspectable,
AI-powered automations — on demand, on a schedule, or from chat. Everything
runs on your machine; data only leaves it via the LLM/HTTP calls you
explicitly configure. Bring your own model — Anthropic, OpenAI, or local
Ollama.

## Quick start

You need **Python 3.11+** (with [`uv`](https://docs.astral.sh/uv/) recommended)
and **Node 20+** for the web app.

```bash
# Clone
git clone https://github.com/Parth-Kadakia/hollerbox.git
cd hollerbox

# Backend
cd backend
uv sync --extra dev
uv run hollerbox --help
uv run pytest          # 194 tests, all green

# Try a workflow
uv run hollerbox validate ../workflows/hello.yaml
uv run hollerbox run ../workflows/hello.yaml --input who=you
uv run hollerbox runs
uv run hollerbox run-detail <run-id-prefix>

# Want LLM steps? Install the SDKs and set a key, then check what's wired:
uv sync --extra dev --extra llm
uv run hollerbox secret set ANTHROPIC_API_KEY
uv run hollerbox providers list

# Web
cd ../web
npm install
npm run dev            # http://127.0.0.1:5173
```

## Design principles

1. **Inspectable & deterministic by default.** Every run and every step is
   persisted with inputs, outputs, status, timing, and logs. You can always
   answer *"what did it do and why."*
2. **Safe by default.** Destructive steps never fire silently. The
   approval mechanism doubles as the *"reply YES to confirm"* flow in chat.
3. **Conversational-first.** The chat loop is the primary interface, not a
   bonus feature. The web dashboard exists for authoring and deep inspection.
4. **Local-first, provider-agnostic.** SQLite + filesystem. No cloud required.
   LLM calls are pluggable: Anthropic, OpenAI, or local Ollama.
5. **Small surface.** No drag-and-drop visual builder — that's the
   commoditized part where projects die.

## Roadmap

HollerBox is built in phases. Each phase ships something runnable and tested
before the next one starts.

| Phase | Scope | Status |
|---|---|---|
| 0 | Repo scaffold, package installs, web shell boots | ✅ |
| 1 | Core engine: YAML workflows, 5 step types, dry-run + approvals + retry, SQLite persistence, CLI | ✅ |
| 2 | LLM providers (Anthropic, OpenAI, Ollama) + `llm` step + encrypted secret store + `secret` / `providers` CLI | ✅ |
| 3 | HTTP API + SSE for live run traces | ⏳ |
| 4 | Web UI: dashboard, YAML editor, run trace, approvals | — |
| 5 | Conversational chat interface (the primary UX) | — |
| 6 | Scheduling (cron + interval) | — |
| 7 | Agent step + agent fallback in chat | — |
| 8 | PWA + push notifications + optional external channels | — |

## License

MIT — see [LICENSE](LICENSE). Copyright © 2026 Parth Kadakia / Brand Box LLC.

---

A [Brand Box LLC](https://brandboxlabs.app/) project.
