#!/usr/bin/env bash
# Stage Ollama portably (no admin, no service, no autostart) and pull the coder models.
# Everything is logged to tools/install.log; tools/READY means it finished.
set -u

cd "$(dirname "$0")/.." || exit 1
mkdir -p tools
exec >>tools/install.log 2>&1

echo
echo "=== stage start: $(date) ==="

EXE="tools/ollama/ollama.exe"

if [ ! -f "$EXE" ]; then
  echo "--- downloading ollama-windows-amd64.zip (~1.49 GB) ---"
  curl -L --retry 3 --retry-delay 2 -o tools/ollama.zip \
    "https://github.com/ollama/ollama/releases/latest/download/ollama-windows-amd64.zip"
  echo "curl exit: $?"
  ls -lh tools/ollama.zip 2>/dev/null

  echo "--- extracting ---"
  powershell -NoProfile -Command "Expand-Archive -Path 'tools\\ollama.zip' -DestinationPath 'tools\\ollama' -Force"
  echo "expand exit: $?"
fi

if [ ! -f "$EXE" ]; then
  echo "FATAL: ollama.exe is not present after extraction"
  exit 1
fi

echo "--- version ---"
"$EXE" --version

echo "--- starting server detached so it outlives this script ---"
WEXE="$(cygpath -w "$PWD/$EXE" 2>/dev/null || echo "$PWD/$EXE")"
powershell -NoProfile -Command "\$p = Start-Process -FilePath '$WEXE' -ArgumentList 'serve' -WindowStyle Hidden -PassThru; \$p.Id | Set-Content 'tools\\ollama.pid'; 'server pid ' + \$p.Id"

for i in $(seq 1 30); do
  if curl -s -m 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    echo "server answering after ${i}s"
    break
  fi
  sleep 1
done

echo "--- pull qwen2.5-coder:3b (~1.9 GB) ---"
"$EXE" pull qwen2.5-coder:3b
echo "pull 3b exit: $?"
"$EXE" list

echo "--- pull qwen2.5-coder:7b (~4.7 GB) ---"
"$EXE" pull qwen2.5-coder:7b
echo "pull 7b exit: $?"
"$EXE" list

echo "=== stage done: $(date) ==="
touch tools/READY
