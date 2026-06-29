#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
AE_ROOT="$(cd "$EXAMPLE_DIR/../.." && pwd)"

export OPENCODE_CONFIG="$AE_ROOT/opencode.cloudgpt.json"
export CLOUDGPT_MODEL="${CLOUDGPT_MODEL:-cloudgpt/DeepSeek-V4-Pro}"
export CLOUDGPT_SMALL_MODEL="${CLOUDGPT_SMALL_MODEL:-cloudgpt/DeepSeek-V4-Pro}"

bash "$AE_ROOT/scripts/start-cloudgpt-proxy.sh"

cd "$AE_ROOT"
echo "OPENCODE_CONFIG=$OPENCODE_CONFIG"
echo "CLOUDGPT_MODEL=$CLOUDGPT_MODEL"
echo "CLOUDGPT_SMALL_MODEL=$CLOUDGPT_SMALL_MODEL"
agentic-evolve run examples/manned_lunar_landing/config_pro.yaml "$@"
