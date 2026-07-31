#!/usr/bin/env bash
# Downloads the Llama-3.2-1B-Instruct GGUF model into models/.
set -euo pipefail
cd "$(dirname "$0")/.."
MODEL=models/Llama-3.2-1B-Instruct-Q4_K_M.gguf
URL="https://huggingface.co/bartowski/Llama-3.2-1B-Instruct-GGUF/resolve/main/Llama-3.2-1B-Instruct-Q4_K_M.gguf"
if [ -f "$MODEL" ]; then echo "Model already present: $MODEL"; exit 0; fi
mkdir -p models
echo "Downloading Llama-3.2-1B-Instruct-Q4_K_M.gguf (~771 MB)…"
curl -L -C - --progress-bar -o "$MODEL" "$URL"
echo "Done: $MODEL"