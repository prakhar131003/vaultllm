#!/usr/bin/env bash
# VaultLLM one-time installer.
#   - creates data/ + data/uploads/
#   - creates a Python venv at .venv and installs backend deps
#   - copies .env.example -> .env if missing
#   - downloads the GGUF model (~771 MB) unless --no-model
#   - installs frontend npm dependencies
#
# Idempotent: safe to re-run. Existing artifacts are detected and reused.
#
# Usage:
#   ./setup.sh            # full install including the model
#   ./setup.sh --no-model # skip the ~771 MB GGUF download
set -euo pipefail
cd "$(dirname "$0")"
PROJECT_ROOT="$(pwd)"

SKIP_MODEL=0
for arg in "$@"; do
  case "$arg" in
    --no-model) SKIP_MODEL=1 ;;
    -h|--help)
      cat <<USAGE
Usage: ./setup.sh [--no-model]

  --no-model  Skip downloading the GGUF model file.
              Run ./scripts/download-model.sh later to fetch it.
USAGE
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $arg" >&2
      echo "Run with --help for usage." >&2
      exit 2
      ;;
  esac
done

step() { printf "\n[%s/6] %s\n" "$1" "$2"; }
ok()   { printf "  ✓ %s\n" "$1"; }
warn() { printf "  ! %s\n" "$1"; }

# ─────────────────────────── 1. data dirs ───────────────────────────
step 1 "Creating data/ + data/uploads/ …"
mkdir -p data data/uploads
ok "data/ and data/uploads/ ready"

# ─────────────────────────── 2. Python venv + deps ───────────────────────────
step 2 "Setting up Python virtualenv (.venv) …"
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found on PATH." >&2
  echo "       Install Python 3.10+ and retry." >&2
  exit 1
fi

# Marker tracks whether backend deps are installed at all (venv or fallback).
DEPS_MARKER=".venv/.deps-installed"
USING_VENV=0

if [ -f "$DEPS_MARKER" ]; then
  # Already installed under some mode (real venv or fallback). Detect which.
  if [ -x .venv/bin/python3 ]; then
    USING_VENV=1
    ok ".venv already exists — reusing"
  else
    warn "Marker $DEPS_MARKER present but no usable .venv — will reuse user-site deps."
  fi
elif [ -d .venv ] && [ -x .venv/bin/python3 ]; then
  USING_VENV=1
  ok ".venv already exists — reusing"
else
  echo "  Trying python3 -m venv .venv …"
  rm -rf .venv
  if python3 -m venv .venv >/tmp/setup-venv.log 2>&1 && [ -x .venv/bin/python3 ]; then
    USING_VENV=1
    ok "Created .venv"
  else
    warn "python3 -m venv failed (no ensurepip?). See /tmp/setup-venv.log."
    warn "Falling back to a user-site install: python3 -m pip install --user --break-system-packages …"
    rm -rf .venv
  fi
fi

if [ -f "$DEPS_MARKER" ]; then
  ok "Backend dependencies already installed (marker: $DEPS_MARKER) — skipping pip"
else
  if [ "$USING_VENV" = "1" ]; then
    echo "  Upgrading pip + installing backend/requirements.txt into .venv …"
    ./.venv/bin/pip install --upgrade pip
    ./.venv/bin/pip install -r backend/requirements.txt
    touch "$DEPS_MARKER"
    ok "Backend dependencies installed (vendored in .venv)"
  else
    # Manually create a "synthetic" .venv marker dir so start.sh can keep
    # preferring a real venv later; the marker still lives next to it.
    mkdir -p .venv
    touch "$DEPS_MARKER"
    echo "  Installing backend/requirements.txt into the user site-packages …"
    python3 -m pip install --user --break-system-packages -r backend/requirements.txt
    ok "Backend dependencies installed (user site-packages)"
    warn "No local .venv — ./start.sh will fall back to 'uvicorn' on PATH."
  fi
fi

# ─────────────────────────── 3. .env ───────────────────────────
step 3 "Ensuring .env exists …"
if [ -f .env ]; then
  warn ".env already exists — leaving it untouched."
  warn "Edit it manually (or delete and re-run) to change settings."
else
  cp .env.example .env
  ok "Created .env from .env.example — tweak EMBEDDING_DIM etc. as needed."
fi

# ─────────────────────────── 4. Model ───────────────────────────
step 4 "Ensuring Llama-3.2-1B-Instruct-Q4_K_M.gguf is present …"
MODEL_PATH="$PROJECT_ROOT/models/Llama-3.2-1B-Instruct-Q4_K_M.gguf"
if [ -f "$MODEL_PATH" ]; then
  ok "Model already present: $MODEL_PATH"
elif [ "$SKIP_MODEL" = "1" ]; then
  warn "Skipped model download (--no-model)."
  warn "Run ./scripts/download-model.sh before ./start.sh or embedding will fail."
else
  if [ ! -x scripts/download-model.sh ]; then
    chmod +x scripts/download-model.sh
  fi
  if [ ! -d models ]; then mkdir -p models; fi
  echo "  Auto-downloading the GGUF model (~771 MB)…"
  ./scripts/download-model.sh
  ok "Model downloaded: $MODEL_PATH"
fi

# ─────────────────────────── 5. Frontend deps ───────────────────────────
step 5 "Installing frontend dependencies (npm install) …"
if [ ! -d frontend ]; then
  warn "frontend/ directory missing — skipping npm install."
  warn "Run with --dev requires the frontend; rerun setup after restoring it."
else
  if [ -d frontend/node_modules ]; then
    ok "frontend/node_modules already exists — skipping npm install"
  else
    if ! command -v npm >/dev/null 2>&1; then
      echo "ERROR: 'npm' not found on PATH." >&2
      echo "       Install Node.js 18+ (https://nodejs.org/) and retry." >&2
      exit 1
    fi
    echo "  Running npm install in frontend/ (may take a minute)…"
    (cd frontend && npm install --no-audit --no-fund)
    ok "Frontend dependencies installed"
  fi
fi

# ─────────────────────────── 6. Summary ───────────────────────────
step 6 "Setup complete"
cat <<STATUS

VaultLLM is ready to launch.

  Run:  ./start.sh --dev
  Open: http://localhost:5173

  Logs: /tmp/llama-server.log  /tmp/rag-kb.log  /tmp/frontend.log
  Stop: pkill -f llama-server ; pkill -f 'uvicorn backend.app.main'
        pkill -f vite

Re-running this script is safe; existing artifacts are reused.
STATUS
