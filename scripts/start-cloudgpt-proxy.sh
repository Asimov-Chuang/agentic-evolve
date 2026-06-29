#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${CLOUDGPT_PROXY_HOST:-127.0.0.1}"
PORT="${CLOUDGPT_PROXY_PORT:-8765}"
PID_FILE="${CLOUDGPT_PROXY_PID_FILE:-$ROOT/.cloudgpt-proxy.pid}"
LOG_FILE="${CLOUDGPT_PROXY_LOG_FILE:-$ROOT/.cloudgpt-proxy.log}"

health_url="http://${HOST}:${PORT}/health"

if curl -fsS "$health_url" >/dev/null 2>&1; then
  echo "CloudGPT proxy already running at http://${HOST}:${PORT}/v1"
  exit 0
fi

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "${old_pid:-}" ]] && kill -0 "$old_pid" 2>/dev/null; then
    echo "CloudGPT proxy process $old_pid is still starting..."
    exit 0
  fi
fi

# WSL long runs: prefer Azure CLI auth when available unless explicitly overridden.
if [[ -z "${CLOUDGPT_USE_AZURE_CLI:-}" ]] && command -v az >/dev/null 2>&1; then
  export CLOUDGPT_USE_AZURE_CLI=1
fi

cd "$ROOT"
nohup python3 cloudgpt_proxy.py --host "$HOST" --port "$PORT" >"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"

for _ in $(seq 1 30); do
  if curl -fsS "$health_url" >/dev/null 2>&1; then
    echo "CloudGPT proxy started at http://${HOST}:${PORT}/v1"
    echo "Logs: $LOG_FILE"
    exit 0
  fi
  sleep 1
done

echo "CloudGPT proxy failed to start. See $LOG_FILE" >&2
tail -n 40 "$LOG_FILE" >&2 || true
exit 1
