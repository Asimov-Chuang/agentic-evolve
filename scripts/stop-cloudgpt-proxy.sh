#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="${CLOUDGPT_PROXY_PID_FILE:-$ROOT/.cloudgpt-proxy.pid}"

if [[ ! -f "$PID_FILE" ]]; then
  echo "No CloudGPT proxy pid file found."
  exit 0
fi

pid="$(cat "$PID_FILE")"
if kill -0 "$pid" 2>/dev/null; then
  kill "$pid"
  echo "Stopped CloudGPT proxy (pid $pid)."
else
  echo "CloudGPT proxy process $pid is not running."
fi

rm -f "$PID_FILE"
