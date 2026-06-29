#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bash "$SCRIPT_DIR/run_score_only_replicates.sh"
bash "$SCRIPT_DIR/run_feedback_meanings_replicates.sh"