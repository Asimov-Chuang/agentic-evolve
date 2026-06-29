#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/setup-path.sh" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/setup-path.sh"
fi

echo "== CloudGPT + OpenCode one-time setup =="
echo

if ! command -v opencode >/dev/null 2>&1; then
  echo "OpenCode not found. Install first:"
  echo "  curl -fsSL https://opencode.ai/install | bash"
  echo "  source setup-path.sh"
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found."
  exit 1
fi

echo "1) Ensure dependencies are installed in your active venv:"
echo "   pip install openai azure-identity-broker requests"
echo

echo "2) Authenticate to CloudGPT (pick one):"
echo "   WSL headless: az login --use-device-code && export CLOUDGPT_USE_AZURE_CLI=1"
echo "   Interactive (default): unset CLOUDGPT_USE_AZURE_CLI and run proxy once"
echo

echo "3) Register OpenCode provider credentials (one-time):"
echo "   opencode auth login --provider cloudgpt"
echo "   opencode auth login --provider cloudgpt-codex"
echo "   When prompted for API key, enter any non-empty string, e.g. local-proxy"
echo

read -r -p "Press Enter to start proxy and run checks (or Ctrl+C to stop)..."

export OPENCODE_CONFIG="$ROOT/opencode.cloudgpt.json"
export CLOUDGPT_MODEL="${CLOUDGPT_MODEL:-cloudgpt-codex/gpt-5.3-codex-20260224}"
export CLOUDGPT_SMALL_MODEL="${CLOUDGPT_SMALL_MODEL:-cloudgpt/gpt-4o-mini-20240718}"

if [[ -z "${CLOUDGPT_USE_AZURE_CLI:-}" ]] && command -v az >/dev/null 2>&1 && az account show >/dev/null 2>&1; then
  export CLOUDGPT_USE_AZURE_CLI=1
fi

"$ROOT/scripts/start-cloudgpt-proxy.sh"

echo
echo "4) OpenCode provider models:"
if opencode models cloudgpt && opencode models cloudgpt-codex; then
  echo "OpenCode provider check passed."
else
  echo "If models are missing, run:"
  echo "  opencode auth login --provider cloudgpt"
  echo "  opencode auth login --provider cloudgpt-codex"
fi

echo
echo "5) Quick completion test:"
opencode run -m "$CLOUDGPT_MODEL" "Reply with exactly: cloudgpt-ok"

echo
echo "Setup complete. For long runs use:"
echo "  ./scripts/run-with-cloudgpt.sh alpha-diagnosis run alpha-diagnosis/workflows/sustaindc_rich_feedback.yaml"
