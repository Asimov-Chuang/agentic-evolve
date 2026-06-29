#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/setup-path.sh" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/setup-path.sh"
fi

export OPENCODE_CONFIG="${OPENCODE_CONFIG:-$ROOT/opencode.cloudgpt.json}"
export CLOUDGPT_MODEL="${CLOUDGPT_MODEL:-cloudgpt-codex/gpt-5.3-codex-20260224}"
export CLOUDGPT_SMALL_MODEL="${CLOUDGPT_SMALL_MODEL:-cloudgpt/gpt-4o-mini-20240718}"

"$ROOT/scripts/start-cloudgpt-proxy.sh"

if [[ $# -lt 1 ]]; then
  cat <<EOF
Usage:
  ./scripts/run-with-cloudgpt.sh agentic-evolve run [-v] <config.yaml>
  ./scripts/run-with-cloudgpt.sh alpha-diagnosis run <workflow.yaml>

Environment:
  CLOUDGPT_MODEL              Default: cloudgpt-codex/gpt-5.3-codex-20260224
  CLOUDGPT_USE_AZURE_CLI=1    Use az login auth (recommended in WSL)
  CLOUDGPT_PROXY_PORT=8765    Local proxy port

Current model: $CLOUDGPT_MODEL
OpenCode config: $OPENCODE_CONFIG
EOF
  exit 1
fi

tool="$1"
shift

case "$tool" in
  agentic-evolve)
    exec agentic-evolve "$@"
    ;;
  alpha-diagnosis)
    if ! command -v alpha-diagnosis >/dev/null 2>&1; then
      echo "alpha-diagnosis not found. Install with: pip install -e alpha-diagnosis/" >&2
      exit 1
    fi
    exec alpha-diagnosis "$@"
    ;;
  opencode)
    if [[ "${1:-}" == "run" ]]; then
      shift
      exec opencode run -m "$CLOUDGPT_MODEL" "$@"
    fi
    exec opencode "$@"
    ;;
  *)
    echo "Unsupported tool: $tool" >&2
    exit 1
    ;;
esac
