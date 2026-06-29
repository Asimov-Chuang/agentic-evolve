#!/usr/bin/env bash
# Run all three causal-filter feedback conditions with the configured replicate range.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bash "$SCRIPT_DIR/run_score_only_replicates.sh"
bash "$SCRIPT_DIR/run_0pct_replicates.sh"
bash "$SCRIPT_DIR/run_0pct_metric_meanings_replicates.sh"

echo ""
echo "All replicate batches finished."