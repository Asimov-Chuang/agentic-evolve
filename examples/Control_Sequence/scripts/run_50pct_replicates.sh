#!/usr/bin/env bash
# Run 50% noise replicates: ablation_run_1 .. _N
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/_common.sh"

run_replicates \
  "$EXAMPLE_DIR/config_50pct_noise.yaml" \
  "ablation_run"
