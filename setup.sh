#!/usr/bin/env bash
# HollerBox one-shot bootstrap. Safe to re-run.
#
# What it does:
#   1. Verifies Python 3.11+ and Node 20+
#   2. Installs `uv` if missing
#   3. Syncs backend deps (with --extra dev + --extra llm by default)
#   4. Runs the backend test suite
#   5. Installs web deps + builds once
#   6. Prints next-steps
#
# Run from anywhere:  ./setup.sh
# Skip the LLM SDKs:  HOLLERBOX_SKIP_LLM=1 ./setup.sh
# Skip the web app:   HOLLERBOX_SKIP_WEB=1 ./setup.sh
# Skip tests:         HOLLERBOX_SKIP_TESTS=1 ./setup.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# --- styling --------------------------------------------------------------

if [[ -t 1 ]]; then
  BOLD=$'\033[1m'; DIM=$'\033[2m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'
  RED=$'\033[31m'; BLUE=$'\033[34m'; RESET=$'\033[0m'
else
  BOLD=""; DIM=""; GREEN=""; YELLOW=""; RED=""; BLUE=""; RESET=""
fi

step()  { printf "\n${BOLD}==>${RESET} %s\n" "$*"; }
ok()    { printf "  ${GREEN}✓${RESET} %s\n" "$*"; }
warn()  { printf "  ${YELLOW}!${RESET} %s\n" "$*"; }
fail()  { printf "  ${RED}✗${RESET} %s\n" "$*" >&2; exit 1; }
note()  { printf "    ${DIM}%s${RESET}\n" "$*"; }

# --- prerequisites --------------------------------------------------------

step "Checking prerequisites"

if ! command -v python3 >/dev/null 2>&1; then
  fail "python3 not found. Install Python 3.11+ from https://www.python.org/downloads/"
fi
PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PY_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
if [[ "$PY_MAJOR" -lt 3 ]] || { [[ "$PY_MAJOR" -eq 3 ]] && [[ "$PY_MINOR" -lt 11 ]]; }; then
  fail "Python ${PY_VERSION} is too old. HollerBox needs Python 3.11+."
fi
ok "python3 ${PY_VERSION}"

if ! command -v git >/dev/null 2>&1; then
  fail "git not found. Install from https://git-scm.com/"
fi
ok "git $(git --version | awk '{print $3}')"

NODE_OK=1
if [[ "${HOLLERBOX_SKIP_WEB:-0}" != "1" ]]; then
  if ! command -v node >/dev/null 2>&1; then
    warn "node not found — skipping the web app. Install Node 20+ to enable it."
    NODE_OK=0
  else
    NODE_MAJOR=$(node --version | sed 's/^v//' | cut -d. -f1)
    if [[ "$NODE_MAJOR" -lt 20 ]]; then
      warn "Node $(node --version) is older than v20 — web may misbehave. Continuing anyway."
    fi
    if [[ "$NODE_OK" -eq 1 ]]; then
      ok "node $(node --version)"
    fi
  fi
else
  note "HOLLERBOX_SKIP_WEB=1 — skipping the web app"
  NODE_OK=0
fi

# --- uv -------------------------------------------------------------------

step "Ensuring uv is installed"

if ! command -v uv >/dev/null 2>&1; then
  note "uv not found — installing via the official script"
  if ! curl -LsSf https://astral.sh/uv/install.sh | sh; then
    fail "uv install failed. Install manually: https://docs.astral.sh/uv/getting-started/installation/"
  fi
  # uv installer drops a hint about restarting the shell; source the env
  # file so the rest of this script can find it.
  if [[ -f "$HOME/.local/bin/env" ]]; then
    # shellcheck disable=SC1091
    source "$HOME/.local/bin/env"
  fi
  export PATH="$HOME/.local/bin:$PATH"
  if ! command -v uv >/dev/null 2>&1; then
    fail "uv installed but isn't on PATH. Open a new shell and re-run ./setup.sh"
  fi
fi
ok "uv $(uv --version | awk '{print $2}')"

# --- backend --------------------------------------------------------------

step "Installing backend dependencies"

cd "$SCRIPT_DIR/backend"

EXTRAS="--extra dev"
if [[ "${HOLLERBOX_SKIP_LLM:-0}" != "1" ]]; then
  EXTRAS="$EXTRAS --extra llm"
  note "Including --extra llm (anthropic + openai SDKs). Set HOLLERBOX_SKIP_LLM=1 to skip."
else
  note "HOLLERBOX_SKIP_LLM=1 — skipping anthropic / openai SDKs"
fi

# shellcheck disable=SC2086
uv sync $EXTRAS >/dev/null
ok "backend deps synced into backend/.venv/"

if [[ "${HOLLERBOX_SKIP_TESTS:-0}" != "1" ]]; then
  step "Running backend tests"
  if uv run pytest --quiet; then
    ok "backend tests pass"
  else
    fail "backend tests failed — fix above output, then re-run ./setup.sh"
  fi
else
  note "HOLLERBOX_SKIP_TESTS=1 — skipping tests"
fi

step "Smoke-testing the CLI"
if uv run hollerbox --version >/dev/null; then
  ok "hollerbox CLI runs ($(uv run hollerbox version 2>/dev/null))"
else
  fail "hollerbox CLI failed to run"
fi

# --- web ------------------------------------------------------------------

if [[ "$NODE_OK" -eq 1 ]]; then
  step "Installing web dependencies"
  cd "$SCRIPT_DIR/web"
  npm install --no-audit --no-fund --silent
  ok "web deps installed into web/node_modules/"

  if [[ "${HOLLERBOX_SKIP_TESTS:-0}" != "1" ]]; then
    step "Building the web app"
    if npm run build --silent >/dev/null 2>&1; then
      ok "web app builds (Vite + TS clean)"
    else
      warn "web build failed — engine still works; run 'npm run build' inside web/ for details"
    fi
  fi
fi

# --- done -----------------------------------------------------------------

cd "$SCRIPT_DIR"

step "${GREEN}Setup complete.${RESET} Try one of these:"

cat <<EOF

  ${BOLD}Run the hello workflow${RESET}
    cd backend
    uv run hollerbox run ../workflows/hello.yaml --input who=you

  ${BOLD}Inspect what just happened${RESET}
    uv run hollerbox runs
    uv run hollerbox run-detail <8-char-prefix>

  ${BOLD}Add an LLM key (Anthropic or OpenAI)${RESET}
    uv run hollerbox secret set ANTHROPIC_API_KEY
    uv run hollerbox providers list

  ${BOLD}Run something that needs approval${RESET}
    uv run hollerbox run ../workflows/examples/file_pipeline.yaml
    uv run hollerbox approve <8-char-prefix>

  ${BOLD}Start the HTTP API${RESET} (Phase 3 — same engine, over REST + SSE)
    make api                                  # http://127.0.0.1:8787
    curl http://127.0.0.1:8787/health
    open http://127.0.0.1:8787/docs           # interactive OpenAPI

EOF

if [[ "$NODE_OK" -eq 1 ]]; then
  cat <<EOF
  ${BOLD}Start the web dev server (Phase 0 shell for now)${RESET}
    cd web
    npm run dev

EOF
fi

cat <<EOF
  ${BOLD}Day-2 shortcuts${RESET}
    make test     # backend + web tests
    make ci       # what CI runs
    make help     # full list

${DIM}Full README: ${RESET}https://github.com/Parth-Kadakia/hollerbox
EOF
