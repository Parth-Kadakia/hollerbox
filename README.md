<p align="center">
  <img src="assets/logo.png" alt="HollerBox" width="120" />
</p>

<h1 align="center">HollerBox</h1>

<p align="center">
  <em>Local-first, chat-driven AI workflow engine.</em><br/>
  <em>Open source. Runs on your machine. Always yours.</em>
</p>

<p align="center">
  <a href="https://github.com/Parth-Kadakia/hollerbox/actions"><img src="https://github.com/Parth-Kadakia/hollerbox/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/status-phase%205%20complete-green.svg" alt="Status">
</p>

---

> **HollerBox is a workflow engine you talk to.** You text it; it figures out
> which workflow you mean, runs it, asks for confirmation before anything
> destructive, and replies in the thread. Every run is typed, inspectable,
> and persisted locally. Bring your own model — Anthropic, OpenAI, Gemini,
> or local Ollama. Generate images too.

---

## Table of contents

- [Why HollerBox](#why-hollerbox)
- [What works today](#what-works-today)
- [Try it in 60 seconds](#try-it-in-60-seconds)
- [Chat: how it works](#chat-how-it-works)
- [A workflow looks like this](#a-workflow-looks-like-this)
- [Architecture](#architecture)
- [Install](#install)
- [Native macOS launcher (menu bar app)](#native-macos-launcher-menu-bar-app)
- [CLI reference](#cli-reference)
- [Remote access](#remote-access)
- [HTTP API](#http-api)
- [LLM providers + secrets](#llm-providers--secrets)
- [Design principles](#design-principles)
- [Non-goals](#non-goals)
- [Roadmap](#roadmap)
- [Project layout](#project-layout)
- [Contributing](#contributing)
- [License](#license)

## Why HollerBox

Most "AI workflow" tools push you into someone else's cloud, an opaque chat
window, or a drag-and-drop builder that breaks the moment you need real
logic. HollerBox is the opposite:

- **You own the engine.** It's a Python library that runs your workflows
  locally. The API, web UI, and chat surface are all clients of that
  library. No cloud required.
- **Typed steps, not prompts-all-the-way-down.** A workflow is a YAML file
  with explicit step types — shell, http, file, python, llm, agent. The
  AI parts are scoped, not load-bearing.
- **Safe by default.** Destructive steps don't run silently. They pause for
  approval — in the CLI that's a `[y/N]`, in chat it's "reply YES to
  proceed", in the web UI it's an inline Approve/Reject card. Same gate,
  three faces.
- **Inspectable.** Every run, every step, every retry is in your local
  SQLite with full input/output/logs. Answer "what did it do and why" by
  reading.
- **Bring your own model.** Anthropic, OpenAI, and local Ollama out of the
  box. A `mock` provider keeps the test suite fast and offline.

## What works today

| | |
|---|---|
| ✅ | YAML workflow models, validation, templating with `${inputs.X}` / `${steps.X.output.Y}` / `${secrets.X}` / `${settings.X}` / `${run.id\|date\|timestamp}` |
| ✅ | 7 step types: `shell`, `python_step`, `http`, `read_file`, `write_file`, `llm`, `image` |
| ✅ | Sequential Runner with dry-run mode, approval pauses, error policy (stop / continue / retry with backoff), persisted resumability |
| ✅ | Full SQLite persistence — workflows, runs, step_runs, settings, schedules, conversations, messages, secrets, push_subscriptions |
| ✅ | Encrypted secret store (Fernet, key at `~/.hollerbox/key`, 0600). Secrets resolved at runtime, redacted from every persisted record |
| ✅ | Text LLM providers: Anthropic, OpenAI, Ollama (lazy SDK imports + auto-registration based on stored keys), plus a deterministic `mock` |
| ✅ | Image providers: OpenAI (`gpt-image-1`) + Gemini (`gemini-3.1-flash-image-preview`, aka "Nano Banana"). Same auto-registration story |
| ✅ | One-shot bootstrap: `./setup.sh` (installs `uv` if missing, syncs deps, runs tests, builds web) + `Makefile` for day-2 shortcuts |
| ✅ | CLI: `validate`, `run`, `runs`, `run-detail`, `approve`, `reject`, `secret` group, `providers list` |
| ✅ | **HTTP API + background worker + SSE** (Phase 3) — FastAPI server wraps the engine: workflows CRUD, run enqueue, approve / reject / cancel, run list & detail, write-only secrets, settings, providers, live SSE event stream. OpenAPI docs at `/docs`. |
| ✅ | **Web UI core** (Phase 4) — Dashboard / Workflows / Editor (Monaco + live validation) / Runs / Run detail (live SSE trace + approve / reject / cancel) / Settings (providers + secrets). React + TS + Tailwind v4 + react-router + Monaco. |
| ✅ | **Conversational interface** (Phase 5) — chat router (LLM-driven), session manager, "reply YES to confirm" approval flow, inline approval cards, chat history sidebar with auto-named threads + delete. Text the engine and it picks the right workflow, asks before destructive steps, and replies with the result. |
| ✅ | **Inline file output** — when a chat or run produces a file (`image`, `write_file`, etc.) the UI fetches it through a sandboxed `/files` endpoint and renders images inline; everything else gets a 📎 download chip. Only paths a real step recorded are served (everything else is 403). |
| ✅ | 301 backend tests + 8 web tests, all green, all offline. CI on every push (pytest + ruff for backend, Vite build + Vitest for web) |
| ⏳ | Workflow authoring UX (templates + form builder — YAML is fine but only for devs), scheduling, agent step, PWA (Phases 6–8) |

## Try it in 60 seconds

After [installing](#install), one command builds the web UI and starts
everything on a single port:

```bash
make app          # http://127.0.0.1:8787 — API, worker, and web UI together
```

Or if you're actively editing the web app, two-terminal dev mode:

```bash
make api          # http://127.0.0.1:8787 — API + worker
make dev          # http://127.0.0.1:5173 — Vite dev server with hot reload
```

Then in the browser:

1. **Settings** → drop in your `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY`). The
   value never leaves your machine and is stored encrypted in
   `~/.hollerbox/`.
2. **Chat** (the default route) → type *"run the hello workflow"*. The
   router picks `hello`, the worker drives it, the result lands as a
   message. If a step is destructive, you'll see an **Approve / Reject**
   card — or just reply `YES` / `NO`.
3. **Workflows / Editor** → YAML lives on disk, with Monaco syntax
   highlighting and live validation. *(A form-based builder lands next so
   you don't have to write YAML for the common case.)*
4. **Runs** → every run, every step. Files the run produced render inline
   (images as `<img>`, other files as a download chip).

### Prefer the terminal?

The CLI talks to the same engine. Nothing requires the API to be running.

```bash
cd backend
uv run hollerbox run ../workflows/hello.yaml --input who=you
uv run hollerbox runs
uv run hollerbox run-detail <8-char-prefix>
```

For a destructive step that pauses:

```bash
uv run hollerbox run ../workflows/examples/file_pipeline.yaml
# → status=paused. Reply with:
uv run hollerbox approve <run-id>
```

## Chat: how it works

The chat page is HollerBox's primary surface. Under the hood, every
message goes through the **conversation router** (an LLM call) which
returns exactly one of four decisions:

| Decision | What happens |
|---|---|
| `run_workflow(name, inputs)` | The matching workflow is enqueued with `trigger_kind=chat`. The worker drives it. A `pending_approval` step pauses and surfaces as an inline card — or, if you'd rather type, replying **YES** / **NO** has the same effect. |
| `ask_clarifying(question)` | The router isn't confident — it asks you a follow-up rather than guessing. Safe-by-default beats picking the wrong workflow. |
| `chitchat(reply)` | Greetings, thanks, out-of-scope chat. Short reply, no engine action. |
| `agent_task(goal)` | A request no workflow covers. The agent fallback lands in Phase 7; for now you'll get a polite "nothing matches" reply restating the goal. |

A few details worth knowing:

- **Auto-named threads.** Each thread's title is the first user message
  (truncated). The sidebar shows your history with `New chat` for empty
  ones; hover any row → small `×` to delete (the runs that thread
  triggered stay in `/runs` either way).
- **The router never fabricates workflow names.** If the LLM picks a name
  not in your catalog, the response is rejected and the user sees a
  clarifying reply instead.
- **Workflow catalog is read from your `workflows/` directory + DB.** The
  `description:` and `chat_examples:` fields are what the router reads
  to decide. Better hints → better routing.
- **Mid-approval, the router is bypassed.** If a thread has a paused run,
  your next message is interpreted as `yes` / `no` / "please clarify"
  rather than as a new request. Click the approval card or type the word
  — same effect.

## A workflow looks like this

[workflows/hello.yaml](workflows/hello.yaml):

```yaml
name: hello
version: 1
description: Smoke test — greets you and reports the moment it ran.
chat_examples:
  - "say hi"
  - "run hello"
inputs:
  who: "world"
steps:
  - id: greet
    type: shell
    config:
      command: "echo 'Hello, ${inputs.who}! — HollerBox'"

  - id: stamp
    type: python_step
    config:
      code: |
        import datetime as dt
        output = {
          "greeting": steps["greet"]["output"]["stdout"].strip(),
          "ran_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        }
```

A few things to notice:
- Every step has an `id`, a `type`, and a typed `config`. The `type` maps to
  a Python class via the registry; the `config` is validated against that
  class's pydantic schema at runtime.
- `${inputs.who}` resolves against the run's input dict. `--input who=you`
  on the CLI overrides the default `world`.
- `steps["greet"]["output"]["stdout"]` reads the prior step's output inside
  a `python_step`. The same data is available as `${steps.greet.output.stdout}`
  in templates.
- `chat_examples` hints (Phase 5) tell the chat router which natural-language
  phrasings should trigger this workflow.

Destructive steps work the same but pause:

```yaml
- id: save
  type: write_file
  requires_confirmation: true     # forces an approval pause
  config:
    path: "${inputs.out_path}"
    content: "${steps.compose.output.report}"
```

Or use the `llm` step:

```yaml
- id: summarize
  type: llm
  config:
    provider: anthropic
    system: "You are a concise editor. Reply with bullets only."
    prompt: |
      Summarize this into 5 bullet points:
      ${inputs.text}
    max_tokens: 800
```

Or generate an image (always destructive — pauses for approval by default):

```yaml
- id: render
  type: image
  requires_confirmation: true
  config:
    provider: openai
    prompt: "A children's book drawing of a vet listening to a baby otter."
    save_to: "${inputs.out_path}"
    size: "1024x1024"
    n: 1
```

The `${secrets.ANTHROPIC_API_KEY}` you'd expect to see here is **invisible**
by design — secrets live in the encrypted store and are loaded into the run
context automatically. You'd never put a key in YAML.

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│   YOU                                                            │
│     │                                                            │
│     ├── hollerbox CLI (you are here)                             │
│     ├── HTTP API + SSE          (Phase 3)                        │
│     ├── Web UI                  (Phase 4)                        │
│     └── Chat / PWA / push       (Phase 5 + Phase 8)              │
│                          │                                       │
│                          ▼                                       │
│               ┌──────────────────────┐                           │
│               │      ENGINE          │  hollerbox/ Python pkg    │
│               │  Runner, Steps,      │  Zero web/HTTP imports.   │
│               │  Templating,         │  Importable, testable     │
│               │  Providers,          │  offline.                 │
│               │  SecretStore         │                           │
│               └─────────┬────────────┘                           │
│                         ▼                                        │
│              SQLite + ~/.hollerbox/  (filesystem)                │
└──────────────────────────────────────────────────────────────────┘
```

The hard rule (enforced by a test): nothing under `backend/hollerbox/` may
`import fastapi`. The engine has to run from the CLI with the API never
started. That's what makes it dogfoodable on day one, testable offline, and
sellable later as a hosted product without a rewrite.

## Install

You need:
- **Python 3.11+** — [`uv`](https://docs.astral.sh/uv/) (auto-installed by the
  bootstrap if missing)
- **Node 20+** for the web app (optional — engine works without it)

### One-shot bootstrap (recommended)

```bash
git clone https://github.com/Parth-Kadakia/hollerbox.git
cd hollerbox
./setup.sh
```

`setup.sh` is safe to re-run. It checks prerequisites, installs `uv` if you
don't have it, syncs backend deps (including the LLM SDKs), runs the test
suite, installs web deps, builds the web app once to catch any TS / Vite
regressions, and prints a list of things to try.

Skip flags (set as env vars before running):
- `HOLLERBOX_SKIP_LLM=1` — don't install the anthropic / openai SDKs
- `HOLLERBOX_SKIP_WEB=1` — don't touch `web/` at all
- `HOLLERBOX_SKIP_TESTS=1` — install only, don't run pytest / npm test

### Day-2 commands (Makefile shortcuts)

```bash
make help          # list all targets
make test          # run backend + web tests
make ci            # run exactly what CI runs (ruff + pytest + npm build + vitest)
make dev           # start the web dev server
make ruff          # auto-fix lint issues in backend
make clean         # remove .venv, node_modules, caches
```

### Manual install (if you don't want the script)

```bash
cd backend
uv sync --extra dev --extra llm
uv run hollerbox --help
```

```bash
cd web
npm install
npm run dev
```

## CLI reference

| Command | What it does |
|---|---|
| `hollerbox validate <path>` | Parse + validate a workflow YAML file or every YAML in a directory. `--show-refs` lists every `${...}` reference. |
| `hollerbox run <workflow>` | Run a workflow (file path or DB-registered name). `--input KEY=VAL` overrides inputs, `--secret KEY=VAL` adds runtime secrets, `--dry-run` simulates destructive steps, `--trigger chat` auto-pauses on any destructive step. |
| `hollerbox runs` | List recent runs. `--workflow NAME` filters, `--limit N` caps. |
| `hollerbox run-detail <id>` | Show the full per-step trace of a run. Accepts an 8-char id prefix. `--no-logs` hides per-step log lines. |
| `hollerbox approve <id>` | Resume a paused run with approval. |
| `hollerbox reject <id>` | Cancel a paused run. |
| `hollerbox secret set NAME` | Store an encrypted secret. Prompts for the value with hidden input + confirmation. |
| `hollerbox secret list` | List secret names (values never displayed). |
| `hollerbox secret rm NAME` | Delete a stored secret. `--yes` skips the confirmation prompt. |
| `hollerbox secret check NAME` | Exit 0 if set, 1 if not. For scripting. |
| `hollerbox providers list` | Show which LLM providers are wired up + how to enable the ones that aren't. |
| `hollerbox version` | Print the HollerBox version. |

Environment overrides:
- `HOLLERBOX_DB_URL` — SQLite URL (default `sqlite:///~/.hollerbox/hollerbox.sqlite`)
- `HOLLERBOX_KEY_PATH` — Fernet key file (default `~/.hollerbox/key`)

## Native macOS launcher (menu bar app)

For an Ollama-style "live in the menu bar" experience, the `app/`
folder ships a `rumps`-based launcher that:

1. Generates a stable API token (one per install, stored at
   `~/.hollerbox/launcher_token`, 0600).
2. Boots `hollerbox-api` as a subprocess.
3. Opens the browser to the local URL with the token already in the
   query string — no copy/paste needed on first launch.
4. Shows a menu bar item with **Open HollerBox**, **Copy server
   token**, **Reveal data folder**, **Show logs**, **Quit**.

Two ways to use it:

```bash
# Dev mode — runs the launcher from source. Quickest to iterate on.
make app-run

# Production bundle — builds HollerBox.app via PyInstaller.
# Output: app/dist/HollerBox.app, drag into /Applications.
make app-build
```

The PyInstaller bundle is unsigned. For personal use you can run
`xattr -d com.apple.quarantine app/dist/HollerBox.app` to bypass
Gatekeeper. Notarization for redistribution needs an Apple developer
account and is out of scope for the open-source build.

## Remote access

By default HollerBox listens on `127.0.0.1` and has no authentication —
it assumes localhost-only. To reach it from another machine or network,
do two things:

### 1. Turn on auth

Set a random token before starting the server:

```bash
export HOLLERBOX_API_KEY="$(openssl rand -hex 16)"
make app
```

The server logs the token on startup. The web UI will prompt you for it
once on first load and store it in localStorage. Every API call sends it
as `Authorization: Bearer <token>`.

### 2. Pick an access path

**Option A — Tailscale (recommended for personal use).**
Install [Tailscale](https://tailscale.com/) on the host *and* the device
you want to reach it from. Both sit on a private mesh; HollerBox is
accessible at your machine's Tailscale hostname, e.g.
`http://my-mac.tailnet-name.ts.net:8787`. No router config, no public
URL, automatic mTLS. Free for personal use.

```bash
# On the host running HollerBox:
HOLLERBOX_API_HOST=0.0.0.0 HOLLERBOX_API_KEY=$YOUR_TOKEN make app
```

**Option B — Cloudflare Tunnel (public URL, free).**
For when you want to share a link or hit the server from a device that
can't run Tailscale.

```bash
# Install once (macOS):
brew install cloudflared

# Run alongside HollerBox:
cloudflared tunnel --url http://127.0.0.1:8787
```

Cloudflare prints a `https://random-words.trycloudflare.com` URL that
proxies to your local server. The token gate stops random visitors from
doing anything; rotate the token if a URL leaks.

> ⚠️ Never expose a token-less HollerBox. The `shell` and `python_step`
> step types run arbitrary code; treat the token as you would an SSH key.

## HTTP API

The API wraps the same engine the CLI uses — workflows, runs, and secrets
are shared. Start it with:

```bash
make api                                    # http://127.0.0.1:8787
# or:  cd backend && uv run hollerbox-api
```

Interactive OpenAPI docs at [http://127.0.0.1:8787/docs](http://127.0.0.1:8787/docs).

| Method & Path | Purpose |
|---|---|
| `GET /health` | Liveness + version |
| `GET /workflows` | List registered workflows (summary) |
| `GET /workflows/{name}` | Workflow detail incl. raw YAML |
| `PUT /workflows/{name}` | Upsert from raw YAML (`{"yaml_source": "..."}`) |
| `POST /workflows/validate` | Lint YAML without saving — for editor live-checks |
| `DELETE /workflows/{name}` | Delete (409 if any run history exists) |
| `POST /workflows/{name}/run` | Enqueue a run (`202 Accepted`); worker dispatches |
| `GET /runs` | List runs, `?workflow=NAME&limit=N` |
| `GET /runs/{id}` | Run detail with per-step trace |
| `GET /runs/{id}/events` | **SSE** stream — `status`, `step`, `done` events |
| `POST /runs/{id}/approve` | Resume a paused run |
| `POST /runs/{id}/reject` | Cancel a paused run |
| `POST /runs/{id}/cancel` | Cancel queued / paused / running |
| `GET /conversations` | List chat conversations |
| `POST /conversations` | Start a new conversation |
| `GET /conversations/{id}/messages` | Full message thread |
| `POST /conversations/{id}/messages` | Send a user message; returns updated thread |
| `GET /conversations/{id}/events` | **SSE** stream — `message`, `done` events |
| `GET /providers` | Active text + image providers + status |
| `GET /secrets` | List names only — values are **never** returned |
| `PUT /secrets/{name}` | Write/rotate a secret value |
| `DELETE /secrets/{name}` | Remove a stored secret |
| `GET /settings` | Read all `${settings.*}` values |
| `PUT /settings/{key}` | Upsert a setting (JSON-typed) |

Environment overrides for the API:
- `HOLLERBOX_API_HOST` / `HOLLERBOX_API_PORT` — listen address (default `127.0.0.1:8787`)
- `HOLLERBOX_WORKER_ENABLED=0` — disable the background worker (tests use this)

Quick try-it from the shell once the server is up:

```bash
# Register a workflow over HTTP
curl -X PUT http://127.0.0.1:8787/workflows/hello \
  -H 'Content-Type: application/json' \
  -d "$(jq -Rs '{yaml_source: .}' < workflows/hello.yaml)"

# Kick off a run
curl -X POST http://127.0.0.1:8787/workflows/hello/run -H 'Content-Type: application/json' -d '{}'

# Watch it live (SSE — Ctrl-C to detach)
curl -N http://127.0.0.1:8787/runs/<run-id>/events
```

The engine package never imports `fastapi` — the API is purely a wrapper,
enforced by `tests/test_engine_imports_clean.py`. Replace the HTTP layer
with anything (gRPC, MCP server, a CLI daemon) and the engine doesn't move.

## LLM providers + secrets

HollerBox auto-registers providers based on what's installed and what's in
your secret store. To enable Anthropic:

```bash
uv sync --extra llm
```

```bash
uv run hollerbox secret set ANTHROPIC_API_KEY
```

The prompt is hidden — paste your key and press Enter, then confirm. Then:

```bash
uv run hollerbox providers list
```

```
  mock       ready  (deterministic test responses)
  ollama     ready  host=http://localhost:11434
  anthropic  ready  secret=ANTHROPIC_API_KEY
  openai     no-key  set with: hollerbox secret set OPENAI_API_KEY
```

OpenAI text works the same way (`OPENAI_API_KEY`). Ollama is always "ready" —
calls fail at run time if no Ollama daemon is listening on `localhost:11434`.

For the `image` step, image providers are auto-registered the same way:
- **OpenAI** image: enabled when `OPENAI_API_KEY` is set (same key as text)
- **Gemini** image: enabled when `GEMINI_API_KEY` is set

Defaults per provider (overrideable per step via `model: <id>`):

| | Text | Image |
|---|---|---|
| **Anthropic** | `claude-opus-4-7` | — (no image API yet) |
| **OpenAI** | `gpt-4o-mini` | `gpt-image-1` |
| **Gemini** | — (text TBD) | `gemini-3.1-flash-image-preview` |
| **Ollama** | `llama3.1` | — |

**Secret hygiene.** Real secret values exist in three places only: the
encrypted SQLite row, the in-memory `secrets` dict during a run, and the
network request you authorized. The `step_runs.resolved_input` column —
which records everything a step actually saw — replaces `${secrets.*}` with
`••••` before persistence. There's a test that fails if any code path
accidentally writes a plaintext secret to the database.

Try a text summary:

```bash
uv run hollerbox run ../workflows/examples/summarize_text.yaml --input provider=anthropic --input text="HollerBox is a local-first workflow engine. Workflows are YAML files. Steps include shell, python, http, files, llm, and image. Destructive steps pause for approval." --input out_path=/tmp/hb-summary.md
```

Approve the paused `save` step, then `cat /tmp/hb-summary.md`.

Or generate an image:

```bash
uv run hollerbox run ../workflows/examples/generate_image.yaml --input prompt="A children's book drawing of a vet listening to a baby otter." --input out_path=/tmp/otter.png
```

Approve the paused `render` step, then `open /tmp/otter.png`. To use Gemini
instead, add `--input provider=gemini`.

## Design principles

1. **Inspectable & deterministic by default.** Every run and every step is
   persisted with inputs, outputs, status, timing, and logs. You can always
   answer *"what did it do and why."* Agentic (nondeterministic) behavior
   is opt-in per task, never the default.
2. **Safe by default.** Destructive steps never fire silently. The
   approval mechanism doubles as the *"reply YES to confirm"* flow in chat —
   this is the heart of the product's trustworthiness.
3. **Conversational-first.** The chat loop is the primary interface; the
   web dashboard exists for authoring and deep inspection.
4. **Local-first, provider-agnostic.** SQLite + filesystem. No cloud
   required. LLM calls go through a small abstraction supporting Anthropic,
   OpenAI, and **Ollama (local models)**.
5. **Small, sharp surface.** No drag-and-drop visual builder — that's the
   commoditized part where projects die.

## Non-goals

For honesty about what HollerBox is *not* trying to be:

- ❌ A multi-user SaaS. The data model leaves room (`workspace_id NULL`
  columns are already present) but v1 is single-user.
- ❌ A drag-and-drop workflow builder. Authoring is YAML + Monaco editor;
  no node graph.
- ❌ A distributed task runner. Single machine, single worker. The seam
  for a real queue is documented; the implementation is for later.
- ❌ A messenger integration. The chat lives in HollerBox's own PWA, not
  iMessage / SMS / Slack. A channel abstraction keeps the door open for
  optional Telegram / SMS later, but nothing depends on them.

## Roadmap

HollerBox ships in phases. Each phase ends in something runnable and
tested. Status as of the latest commit:

| Phase | Scope | Status |
|---|---|---|
| 0 | Repo scaffold, package installs, web shell boots | ✅ |
| 1 | Core engine: YAML workflows, 5 step types, dry-run + approvals + retry, SQLite persistence, CLI | ✅ |
| 2 | LLM providers (Anthropic / OpenAI / Ollama) + `llm` step + encrypted secret store + `secret` / `providers` CLI | ✅ |
| 2c | Image step + OpenAI (`gpt-image-1`) and Gemini (`gemini-3.1-flash-image-preview`) image providers — bonus extension to Phase 2 | ✅ |
| 3 | HTTP API + background worker + SSE — workflows CRUD, run enqueue, approve/reject/cancel, providers/secrets/settings, live event stream | ✅ |
| 4 | Web UI: Dashboard / Workflows / Editor (Monaco + live validation) / Run detail (SSE trace + approvals) / Settings | ✅ |
| 5 | Conversational chat interface — router / session / replies, "reply YES" flow, inline approval cards | ✅ |
| 6 | Scheduling (cron + interval) | — |
| 7 | Agent step + agent fallback in chat | — |
| 8 | PWA + push notifications + optional external channels | — |

## Project layout

```
hollerbox/
├── backend/
│   ├── hollerbox/          ← the engine (Python package, no web deps)
│   │   ├── core/           ← Runner, RunContext, templating, workflow models
│   │   ├── steps/          ← shell, python, http, files, llm, image step types
│   │   ├── providers/      ← text: anthropic / openai / ollama / mock
│   │   │                      image: openai / gemini (separate ABC)
│   │   ├── store/          ← SQLAlchemy models + repo functions
│   │   ├── secrets.py      ← Fernet-encrypted secret store
│   │   ├── registry.py     ← step-type registry
│   │   └── cli.py          ← `hollerbox …` CLI entry point
│   ├── api/                ← FastAPI app + background worker (Phase 3)
│   │   ├── main.py         ← app factory + lifespan
│   │   ├── deps.py         ← EngineSurface dependency
│   │   ├── routes/         ← workflows, runs, approvals, providers, secrets, settings
│   │   └── worker.py       ← polls `queued` runs, drives via Runner
│   ├── tests/              ← pytest suite (265 tests, all offline)
│   └── pyproject.toml
├── web/                    ← Vite + React + TS + Tailwind v4 + PWA
├── workflows/              ← YOUR workflow YAML files
│   ├── hello.yaml
│   └── examples/
│       ├── file_pipeline.yaml
│       ├── summarize_text.yaml
│       └── generate_image.yaml
├── assets/                 ← brand assets (logo master)
├── .github/workflows/ci.yml
└── README.md               ← you are here
```

## Contributing

This is a personal project that may grow into something more. Issues and
PRs are welcome:

- **Bug reports** — describe what you ran, what happened, what you
  expected. A `hollerbox run-detail <id>` output usually has everything I
  need.
- **New step types** — must subclass `Step`, declare a `ConfigModel`
  (pydantic), implement `run()` and `describe_effect()`, and declare
  `default_destructive` honestly. Add a test in `backend/tests/`.
- **New providers** — subclass `Provider`. Use lazy SDK imports so the
  package stays installable on machines without your SDK.

Before submitting a PR:

```bash
cd backend
uv run ruff check .
uv run pytest
```

```bash
cd ../web
npm run build
npm test
```

CI runs the same on every push.

## License

MIT — see [LICENSE](LICENSE). Copyright © 2026 Parth Kadakia / Brand Box LLC.

---

A [Brand Box LLC](https://brandboxlabs.app/) project.
