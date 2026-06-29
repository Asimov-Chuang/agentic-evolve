#!/usr/bin/env bash
# Run all SustainDC feedback-ablation conditions with the configured replicate range.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bash "$SCRIPT_DIR/run_score_only_replicates.sh"
bash "$SCRIPT_DIR/run_feedback_meanings_replicates.sh"

echo ""
echo "All replicate batches finished."