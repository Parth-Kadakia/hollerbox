# HollerBox — Local-First AI Agent Workflow System (chat-driven)

> **This file is a build brief for an AI coding agent (Claude in VS Code).** Read the whole thing before writing code. Build it in the **phases** at the bottom — each phase must end in something runnable and tested. Do **not** scaffold all phases at once.

---

## 1. What we're building (and the one rule that governs every decision)

A **local-first system you talk to like a messaging app to get tasks done.** You text it ("summarize my unread email and draft replies", "run the nightly file sync now", "what did the news digest find this morning?"); it figures out which task you mean, runs it, asks for confirmation before anything destructive, and replies in the thread. Under the hood it's a **workflow engine** that runs typed, inspectable, AI-powered automations — on demand, on a schedule (cron), or from chat.

**We build our own chat app** (an installable web app / PWA that lives on your phone's home screen with push notifications). We are **not** integrating iMessage, SMS, or any third-party messenger to ship — Apple has no official iMessage API and every workaround needs a Mac awake 24/7 on your personal Apple ID. Owning the chat surface is simpler, works on every device, and is cleaner to sell later. A thin **channel abstraction** keeps the door open to add Telegram/iMessage/SMS as *optional* channels down the road, but nothing depends on them.

A workflow is a sequence (later: a graph) of typed **steps**: run a shell command, hit an HTTP endpoint, run Python, read/write files, call an LLM, or hand control to an **agent** (an LLM that loops with tools until a goal is met). Steps pass data through a shared run **context**. Everything runs on your machine; data leaves it only via the explicit LLM/HTTP calls you configured.

**The governing rule: build the _engine_ as a standalone, importable library with zero dependency on the API, the chat, or the UI.** The engine is the product. The API, the chat interface, and the web UI are all *clients* of it. This single discipline is what makes the system (a) dogfoodable from the CLI on day one, (b) testable offline, and (c) sellable later as a hosted product without a rewrite.

### Design priorities, in order
1. **Inspectable & deterministic by default.** Every run and every step is persisted with inputs, outputs, status, timing, and logs. You can always answer "what did it do and why." Agentic (nondeterministic) behavior is opt-in per task, never the default.
2. **Safe by default.** Destructive steps never fire silently. The approval mechanism (§5) doubles as the **"reply YES to confirm" flow in chat** — this is the heart of the product's trustworthiness.
3. **Conversational-first.** The chat loop is the primary interface, not a bonus feature. The web dashboard exists for authoring and deep inspection; day-to-day you talk to it.
4. **Local-first, provider-agnostic.** SQLite + filesystem, no cloud required. LLM calls go through an abstraction supporting Anthropic, OpenAI, and **Ollama (local models)**.
5. **Small, sharp surface.** No drag-and-drop node editor in v1 (see §7) — that's the commoditized part where projects die.

### Explicit non-goals (for now)
- No iMessage/SMS/Telegram integration in v1 (channel abstraction only; implementations are optional, later).
- No multi-user auth, teams, or billing (data model leaves room — see §11).
- No drag-and-drop visual workflow builder.
- No distributed execution / brokers / Kubernetes. Single machine, single worker.

---

## 2. Tech stack (use these — do not substitute without asking)

| Layer | Choice | Why |
|---|---|---|
| Engine + backend language | **Python 3.11+** | Best ecosystem for "do things" steps (subprocess, httpx, paramiko, pypdf, pandas). |
| Workflow schema / validation | **Pydantic v2** | Typed workflow + step models, free validation and JSON schema for the UI. |
| Persistence | **SQLite via SQLAlchemy 2.0** | Zero-config local-first; Postgres swap later is a connection-string change. |
| API | **FastAPI + Uvicorn** | Async, auto OpenAPI docs, pairs cleanly with React. |
| Live updates / streaming replies | **Server-Sent Events (SSE)** | Streams chat replies and live run traces; simpler than WebSockets. |
| Scheduling | **APScheduler** (in-process) + a cron-friendly CLI | UI-managed schedules *and* classic crontab both work. |
| Frontend | **React + TypeScript + Vite** | |
| Installable app + push | **vite-plugin-pwa + Web Push (VAPID)** | Home-screen icon + push notifications so it feels like a messenger. |
| Styling | **Tailwind CSS** | |
| Code editor (workflow authoring) | **Monaco** | YAML editor with validation. |
| Graph preview | **React Flow** (read-only) | Render the workflow DAG; not an editor in v1. |
| Tests | **pytest** (engine/api), **Vitest** (web) | The engine must have real unit tests. |

**Package managers:** `uv` (Python) and `pnpm` (Node) if available, else `pip`/`venv` and `npm`.

---

## 3. Repository layout

```
hollerbox/
├── backend/
│   ├── hollerbox/                  # THE ENGINE — importable, NO fastapi imports allowed in here
│   │   ├── core/
│   │   │   ├── context.py      # RunContext: shared dict + templating helpers
│   │   │   ├── workflow.py     # Workflow + Step pydantic models, YAML loader, validation
│   │   │   ├── runner.py       # executes a workflow; dry-run, approvals, error policy, resumable
│   │   │   └── templating.py   # ${...} resolution against context / secrets / settings
│   │   ├── steps/
│   │   │   ├── base.py         # Step ABC: run(ctx)->StepResult; declares `destructive`, describe_effect()
│   │   │   ├── shell.py  python_step.py  http.py  files.py  llm.py  branch.py
│   │   │   └── agent.py        # LLM tool-calling loop (Phase 7)
│   │   ├── providers/          # base.py + anthropic.py openai.py ollama.py mock.py
│   │   ├── conversation/       # THE CHAT BRAIN (engine-side, no HTTP)
│   │   │   ├── router.py       # message -> matched workflow + extracted inputs, OR agent fallback
│   │   │   ├── session.py      # conversation state, multi-turn context, clarifications
│   │   │   └── replies.py      # turns run results / approvals into chat messages
│   │   ├── channels/           # channel abstraction (our own app is the default channel)
│   │   │   ├── base.py         # Channel ABC: inbound event -> message; send(reply)
│   │   │   └── inapp.py        # our own chat app channel (the only one in v1)
│   │   ├── store/              # models.py db.py repo.py  (SQLAlchemy)
│   │   ├── scheduler/scheduler.py
│   │   ├── registry.py         # name -> Step / Provider / Channel
│   │   ├── secrets.py          # encrypted-at-rest secret store
│   │   └── cli.py              # hollerbox run / validate / ls / chat (local REPL)
│   ├── api/                    # FastAPI — imports hollerbox, exposes it over HTTP + SSE
│   │   ├── main.py  routes/  worker.py  push.py  schemas.py
│   ├── tests/
│   └── pyproject.toml  hollerbox.example.toml
├── web/                        # React + Vite + TS + Tailwind, PWA-enabled
│   └── src/
│       ├── pages/              # Chat (primary), Dashboard, Workflows, Editor, RunDetail, Schedules, Settings
│       ├── components/  api/  lib/  push/
├── workflows/                  # THE USER'S PERSONAL WORKFLOWS (yaml) — separate from engine
│   ├── hello.yaml  examples/
├── docker-compose.yml          # Phase 9 only
└── README.md
```

**Hard rule:** nothing under `backend/hollerbox/` may `import fastapi`. The engine runs from `cli.py` with the API never started; a test enforces this.

---

## 4. Workflow definition format

Workflows are **YAML**, validated by a Pydantic model. Steps run top-to-bottom (v1). Each step writes named outputs into the run context; later steps reference them with `${...}`. The `description` and `inputs` fields matter extra here — the **chat router reads them** to decide when a text message should trigger this workflow and what inputs to extract.

```yaml
# workflows/examples/digest.yaml
name: morning_news_digest
version: 1
description: Fetch headlines on a topic, summarize them, and save a markdown digest.
chat_examples:                 # sample phrasings that should trigger this (router hints)
  - "what's the news on {topic}"
  - "run my news digest"
inputs:
  topic: "AI infrastructure"   # default; router can override from the message
trigger:
  cron: "0 7 * * *"            # optional; real schedule lives in the schedules table/UI
steps:
  - id: fetch
    type: http
    config: { method: GET, url: "https://hn.algolia.com/api/v1/search?query=${inputs.topic}" }

  - id: summarize
    type: llm
    config:
      provider: ${settings.default_provider}
      model: claude-sonnet-4-6
      system: "You are a concise news summarizer."
      prompt: "Summarize the top items into 5 bullets:\n${steps.fetch.output.body}"

  - id: save
    type: write_file
    destructive: true              # NOT run in dry-run; logs intended write instead
    requires_confirmation: false   # set true to force an approval pause (and a chat 'reply YES')
    config:
      path: "~/Desktop/digest-${run.date}.md"
      content: ${steps.summarize.output.text}
```

### Templating (`templating.py`)
`${inputs.X}`, `${steps.<id>.output.<field>}`, `${secrets.<NAME>}` (never logged/persisted), `${settings.<key>}`, `${run.id|date|timestamp}`. Single-`${...}` values keep their native type. Unresolved static refs fail validation and surface in the UI/chat.

### Step contract (`steps/base.py`)
```python
class StepResult(BaseModel):
    status: Literal["success","failed","skipped","dry_run","pending_approval"]
    output: dict; logs: list[str]; error: str | None = None

class Step(ABC):
    type: ClassVar[str]                 # registry key, e.g. "http"
    destructive: bool = False
    requires_confirmation: bool = False
    @abstractmethod
    def run(self, ctx: RunContext) -> StepResult: ...
    def describe_effect(self, ctx: RunContext) -> str: ...   # what a dry-run / chat preview shows
```

---

## 5. Dry-run & approvals (first-class — and the chat confirmation flow)

The safety core. Also literally how chat confirmations work.

- **`dry_run`**: every `destructive` step is **not executed** — it records a `dry_run` result whose logs hold `describe_effect()` ("would write 1.2KB to ~/Desktop/digest-2026-05-24.md"). Non-destructive steps (HTTP GET, read_file, llm) **do** run, so dry-runs are realistic.
- **`requires_confirmation: true`** (or any destructive step in chat-triggered runs): the engine sets the step + run to `pending_approval` and **stops**, persisting state. It resumes only on `POST /runs/{id}/approve` (or `/reject`). In the **web UI** this is an inline Approve/Reject card. **In chat** the reply becomes: *"About to delete 8 files in ~/Temp older than 6 months. Reply YES to proceed, NO to cancel."* — the user's "yes" resolves the approval and the run continues. In CLI it's a `[y/N]` prompt (`--yes` to skip for cron).
- **Error policy** per step: `on_error: stop | continue | retry` (default `stop`); `retry` takes `max_attempts` + `backoff_seconds`.
- **Resumable**: run state is persisted after every step, so approval pauses (or crashes) resume from the last completed step.

---

## 6. Conversational layer (the chat brain)

Lives in `hollerbox/conversation/` — pure engine logic, no HTTP. The API/chat UI calls it.

**The loop**, per inbound message:
1. **Router** (`router.py`) gets the message + the catalog of workflows (each `name` + `description` + `chat_examples` + input schema) + recent conversation turns. An LLM call returns one of: `run_workflow(name, inputs)`, `ask_clarifying(question)`, `agent_task(goal)` (Phase 7 fallback for things no workflow covers), or `chitchat(reply)`.
2. **Session** (`session.py`) holds multi-turn state so follow-ups work ("now do the same for last week", answering a clarifying question). Conversation + messages persisted (§8).
3. If a workflow is chosen, enqueue a run with `trigger_kind=chat` and the extracted inputs. Stream progress back as chat messages.
4. **Replies** (`replies.py`) turn run lifecycle events into chat messages: a short "on it…" ack, the `pending_approval` confirmation prompt, and a final result summary (with a link/expander to the full run trace in the UI).

**Design notes:** the router is a single, swappable LLM prompt — keep it small and testable with the `mock` provider. Confidence threshold: if the router isn't reasonably sure, it asks a clarifying question rather than guessing (matches the safe-by-default stance). The agent fallback (Phase 7) is the only nondeterministic path and is clearly labeled as such in the trace.

---

## 7. UI (React + PWA) — scope it deliberately

Seven pages. The web app is a **PWA** (installable, push notifications). Consume the OpenAPI schema FastAPI generates.

1. **Chat (primary, default route).** Messenger-style thread: your messages + the system's. Streaming replies via SSE. "Running…" bubbles that expand into the live step trace. Inline **Approve / Reject** cards for `pending_approval`. Push notification when a long task finishes or needs confirmation. This is the page you'll live in.
2. **Dashboard** — recent runs with status chips, success/fail counts, next scheduled runs, quick "Run now".
3. **Workflows** — list (from `workflows/` dir + DB), enable/disable, schedule summary, last-run status; Run / Dry-run / Edit.
4. **Editor** — **Monaco YAML editor** with live schema validation + a **read-only React Flow DAG preview**. Save writes the YAML file and upserts the DB record. *(No drag-and-drop node editor in v1.)*
5. **Run detail** — vertical step-by-step trace: status, duration, resolved inputs, outputs, logs (collapsible), dry-run "would do" badges, inline approval cards. Live via SSE.
6. **Schedules** — create/edit cron or interval triggers bound to workflows; toggle active.
7. **Settings** — LLM providers + API keys (write-only: show "•••• set"), default provider/model, data directory, push-notification enrollment.

Aesthetic: clean dev-tool feel (Linear/Vercel), dark mode default, monospace for logs/IDs, minimal animation. The Chat page should feel like a real messenger (bubbles, timestamps, typing/working indicator).

---

## 8. Data model (SQLAlchemy)

```
workflows(id pk, name unique, version, description, yaml_source, enabled, created_at, updated_at, workspace_id NULL)
runs(id pk, workflow_id fk, status[queued|running|paused|success|failed|cancelled], dry_run,
     inputs json, context_snapshot json, started_at, finished_at, error,
     trigger_kind[manual|cron|schedule|chat], conversation_id NULL fk, workspace_id NULL)
step_runs(id pk, run_id fk, step_id, step_type, status[success|failed|skipped|dry_run|pending_approval],
          resolved_input json, output json, logs json[], error, started_at, finished_at, attempt)
schedules(id pk, workflow_id fk, cron NULL, interval_seconds NULL, active, next_run_at, last_run_at)
conversations(id pk, title, created_at, updated_at, workspace_id NULL)
messages(id pk, conversation_id fk, role[user|assistant|system], content text,
         run_id NULL fk, kind[text|ack|approval_request|result|error], created_at)
secrets(name pk, value_encrypted blob, created_at, updated_at)        # §10
settings(key pk, value json)
push_subscriptions(id pk, endpoint, keys json, created_at)            # Web Push
```
`workspace_id` is reserved for multi-tenant later (always NULL in v1). Secrets are **never** written into `runs.context_snapshot`, `step_runs.resolved_input`, `messages`, or logs — redact `${secrets.*}` to `••••` before persisting anything.

---

## 9. Execution, scheduling & triggers

- **Worker (`api/worker.py`):** a background asyncio task in the API process (v1) that polls for `queued` runs and executes them via the engine's `Runner`. Keep it thin — it pulls a run and calls `Runner.execute(run_id)`. Comment this as the seam where a real queue (Redis/RQ, Celery) plugs in for the hosted product.
- **Triggers:**
  - *Chat* — the primary path: message → router → enqueued run (`trigger_kind=chat`), replies streamed back (§6).
  - *Manual* — `POST /workflows/{id}/run` (UI button / curl).
  - *Schedule* — APScheduler reads the `schedules` table and enqueues runs (`trigger_kind=schedule`); managed from the Schedules UI.
  - *OS cron* — `hollerbox run <name> --yes` CLI entrypoint for crontab, bypassing the app entirely (talks to the engine directly).
- One run executes its steps sequentially in v1. Build the runner against an ordered *plan* (not hardcoded iteration) so a DAG executor can slot in later.

---

## 10. Secrets & security

- Secrets live in the `secrets` table, encrypted at rest with a master key generated on first run, stored at `~/.hollerbox/key` (`600` perms; document it). Use `cryptography.fernet`.
- API-key fields are **write-only** over the API: set or clear only; responses show presence (`{"set": true}`), never the value.
- Never log secret values; redact in all persisted records (§8).
- `shell` and `python_step` execute arbitrary local code by design (it's a personal automation tool). Surface that in the UI when a workflow uses them, and keep them behind a settings toggle (disabled by default) so a future hosted version can ship without them.

---

## 11. The personal → sellable path (honor now, build later)

Don't build these yet; don't preclude them:
- `workspace_id` columns present (NULL) → multi-tenant later. Engine has no auth/HTTP assumptions → wrap auth at the API layer.
- SQLAlchemy + single `db.py` → Postgres swap is config. Worker is a thin seam → real queue later.
- LLM provider abstraction → hosted version can meter/charge. Workflows are portable YAML → export/import + a template marketplace.
- **Channel abstraction** → add Telegram (easy, free, robust) first, then SMS, then iMessage via a cloud relay — all as optional channels, never required.

The sellable wedge is **not** "another n8n" (visual builders are commoditized). It's: *a chat-first assistant you own, running local-first, inspectable and safe-by-default, with bring-your-own-model (incl. local Ollama).* Keep that identity sharp.

---

## 12. Build phases — ship something runnable at the end of each

> Build strictly in order; write tests as you go (pytest for engine, a couple of Vitest render tests for key UI). Pause and confirm with me at the end of Phases 1, 4, and 5.

**Phase 0 — Scaffold.** Repo per §3; Python env; `hollerbox` importable; `hollerbox --help` works; web app boots to an empty shell. ✅ `pytest` runs and `vite` dev server starts.

**Phase 1 — Core engine + CLI.** Workflow model + YAML loader + validation; templating; `RunContext`; `Runner` (sequential, error policy, dry-run, approvals, resumable); steps `shell`, `python_step`, `http`, `read_file`, `write_file`; SQLite persistence; `mock` provider; CLI `hollerbox validate|run|runs|run-detail`. ✅ `workflows/hello.yaml` runs from CLI; a dry-run of a destructive step logs intent without executing; engine tests pass offline.

**Phase 2 — Real LLM + secrets.** `anthropic`, `openai`, `ollama` providers; `llm` step; encrypted secret store + `${secrets.*}` resolution + redaction. ✅ an `llm` step completes; a test asserts secrets never appear in any persisted record.

**Phase 3 — API + worker + SSE.** FastAPI wrapping the engine; background worker; REST (workflows CRUD, run, runs list/detail, approve/reject/cancel, settings, write-only secrets); SSE stream for live run traces. ✅ a workflow can be created, run, approved, and inspected over HTTP, with live updates.

**Phase 4 — Web UI core.** Dashboard, Workflows, Editor (Monaco + validation + React Flow preview), Run detail (live trace, dry-run badges, approval cards), Settings. ✅ a non-CLI user can author, dry-run, run, approve, and inspect a workflow in the browser.

**Phase 5 — Conversational interface (our own chat app).** `conversation/` router + session + replies; Chat page (streaming replies, working indicators, inline approval cards); chat-triggered runs end to end; **"reply YES to confirm"** for destructive steps. Router uses known workflows only (no agent yet). ✅ you can text the app a request, it picks the right workflow, runs it, asks for confirmation on destructive steps, and replies with the result.

**Phase 6 — Scheduling.** APScheduler + Schedules page; scheduled runs fire on their own and stream to the run detail. ✅ a scheduled workflow runs unattended.

**Phase 7 — Agent step + agent fallback.** `agent.py` tool-calling loop (toolset = configured subset of steps; `max_iterations` + budget guard; every turn traced). Router gains an `agent_task` fallback for requests no workflow covers. ✅ a chat request with no matching workflow is handled by the agent, and every agent turn is inspectable.

**Phase 8 — PWA + push (make it feel like a messenger) + optional external channels.** vite-plugin-pwa install flow; Web Push (VAPID) on task completion / confirmation-needed; implement the channel abstraction with one optional external channel (Telegram recommended). ✅ the app installs to a phone home screen, pushes a notification when a task needs you, and (optionally) the same loop works from Telegram.

**Phase 9 — Sellable hardening (optional, later).** Auth + workspaces, Postgres option, Docker Compose, workflow export/import.

---

## 13. Conventions for the building agent
- Engine first, always. If it can live in `hollerbox/` without FastAPI, it does.
- Type everything (Pydantic for data, hints throughout; `mypy` clean if configured).
- Every step type + the router ship with unit tests using the `mock` provider; **no network in the engine test suite**.
- Small commits per phase; never mix phases.
- New step types must declare `destructive` honestly and implement `describe_effect`.
- Ask before: adding a dependency not in §2, changing the §8 data model, or starting a phase whose predecessor isn't green.
- Ship `workflows/hello.yaml` plus 2–3 realistic examples (a file-pipeline job; a fetch→summarize→write digest; an agent task) by Phase 7.

*End of brief. Build Phase 0, then stop and confirm the scaffold before Phase 1.*
