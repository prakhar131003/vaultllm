#!/usr/bin/env bash
# VaultLLM launcher.
#   - starts llama.cpp server (port 8080)
#   - starts FastAPI backend  (port 8000)
#   - with --dev: also starts Vite frontend (port 5173)
set -euo pipefail
cd "$(dirname "$0")"

PROJECT_ROOT="$(pwd)"

# ─────────────────────────── env ───────────────────────────
mkdir -p data data/uploads
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example — review/tweak it as needed."
fi
# shellcheck disable=SC1091
set -a; source ./.env; set +a

# ─────────────────────────── model gate ───────────────────────────
MODEL_PATH="$PROJECT_ROOT/models/Llama-3.2-1B-Instruct-Q4_K_M.gguf"
if [ ! -f "$MODEL_PATH" ]; then
  echo "ERROR: model file not found: $MODEL_PATH" >&2
  echo "Hint: run ./scripts/download-model.sh (downloads ~771 MB from Hugging Face)." >&2
  exit 1
fi

# ─────────────────────────── helpers ───────────────────────────
port_listening() {
  # portable-ish check; ss preferred, fall back to /dev/tcp probe.
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -ltn "sport = :$port" 2>/dev/null | awk 'NR>1{exit 0}END{exit 1}' && return 0 || return 1
  fi
  (echo >"/dev/tcp/127.0.0.1/$port") >/dev/null 2>&1
}

wait_for_url() {
  local url="$1" max="${2:-30}"
  for _ in $(seq 1 "$max"); do
    if curl -fsS -o /dev/null "$url"; then return 0; fi
    sleep 1
  done
  return 1
}

resolve_llama_server() {
  if command -v llama-server >/dev/null 2>&1; then command -v llama-server; return 0; fi
  for candidate in \
    "$HOME/.local/llama.cpp/build/bin/llama-server" \
    "$HOME/.local/bin/llama-server" \
    "/usr/local/bin/llama-server"; do
    [ -x "$candidate" ] && { echo "$candidate"; return 0; }
  done
  return 1
}

# ─────────────────────────── llama.cpp ───────────────────────────
if port_listening 8080; then
  echo "llama-server already listening on :8080 — skipping launch."
else
  LLAMA_BIN="$(resolve_llama_server || true)"
  if [ -z "${LLAMA_BIN:-}" ]; then
    echo "ERROR: llama-server binary not found." >&2
    echo "Hint: build llama.cpp (https://github.com/ggml-org/llama.cpp)" >&2
    echo "      and put 'llama-server' on PATH OR install to ~/.local/bin/." >&2
    exit 1
  fi
  echo "Starting llama-server on :8080 (logs: /tmp/llama-server.log)…"
  nohup "$LLAMA_BIN" \
    --host 127.0.0.1 --port 8080 \
    --model "$MODEL_PATH" \
    --embedding --pooling mean --embd-normalize 2 \
    --threads 8 --no-webui \
    --ubatch-size 2048 --batch-size 2048 \
    > /tmp/llama-server.log 2>&1 < /dev/null &
  if ! wait_for_url "http://127.0.0.1:8080/v1/models" 30; then
    echo "ERROR: llama-server did not become ready within 30 s." >&2
    echo "Tail of /tmp/llama-server.log:" >&2
    tail -n 40 /tmp/llama-server.log >&2 || true
    exit 1
  fi
  echo "llama-server ready."
fi

# ─────────────────────────── backend ───────────────────────────
if port_listening 8000; then
  echo "uvicorn already listening on :8000 — skipping launch."
else
  # Prefer the project-local .venv (created by ./setup.sh) over a global install.
  UVICORN_BIN=""
  if [ -x .venv/bin/uvicorn ]; then
    UVICORN_BIN=".venv/bin/uvicorn"
  elif command -v uvicorn >/dev/null 2>&1; then
    UVICORN_BIN="$(command -v uvicorn)"
  fi
  if [ -z "${UVICORN_BIN:-}" ]; then
    echo "ERROR: uvicorn not found." >&2
    echo "Hint: run ./setup.sh to create .venv and install backend/requirements.txt," >&2
    echo "      or 'pip install -r backend/requirements.txt' on your PATH." >&2
    exit 1
  fi
  echo "Using uvicorn: $UVICORN_BIN"
  echo "Starting FastAPI backend on :8000 (logs: /tmp/rag-kb.log)…"
  nohup "$UVICORN_BIN" backend.app.main:app --host 0.0.0.0 --port 8000 \
    > /tmp/rag-kb.log 2>&1 < /dev/null &
  if ! wait_for_url "http://127.0.0.1:8000/api/health" 20; then
    echo "WARNING: backend did not respond on /api/health within 20 s." >&2
    echo "Tail of /tmp/rag-kb.log:" >&2
    tail -n 40 /tmp/rag-kb.log >&2 || true
  else
    echo "backend ready."
  fi
fi

# ─────────────────────────── optional frontend ───────────────────────────
if [ "${1:-}" = "--dev" ]; then
  if port_listening 5173; then
    echo "Vite already listening on :5173 — skipping launch."
  else
    if [ ! -d frontend ]; then
      echo "ERROR: --dev requested but frontend/ directory missing." >&2
      exit 1
    fi
    echo "Starting Vite dev server on :5173 (logs: /tmp/frontend.log)…"
    (cd frontend && nohup npm run dev > /tmp/frontend.log 2>&1 < /dev/null &)
    if wait_for_url "http://127.0.0.1:5173" 30; then
      echo "frontend ready."
    else
      echo "WARNING: Vite did not respond on :5173 within 30 s." >&2
      tail -n 40 /tmp/frontend.log >&2 || true
    fi
  fi
fi

# ─────────────────────────── status ───────────────────────────
cat <<'STATUS'

VaultLLM is up:
  • backend   http://localhost:8000     (logs: /tmp/rag-kb.log)
  • llama.cpp http://127.0.0.1:8080     (logs: /tmp/llama-server.log)
STATUS
if [ "${1:-}" = "--dev" ]; then
  echo "  • frontend http://localhost:5173     (logs: /tmp/frontend.log)"
fi
echo
echo "Stop with:  pkill -f llama-server ; pkill -f 'uvicorn backend.app.main'"
[ "${1:-}" = "--dev" ] && echo "                  pkill -f 'vite'"
