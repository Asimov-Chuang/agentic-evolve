#!/usr/bin/env bash
# Re-run Cycle 1 rule injection in Pro mode from the first stuck point (no post-injection leakage).
set -eu

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT/agentic-evolve"

source activate-env.sh

AD2_WS="$ROOT/agentic-evolve/examples/adaptive_temporal_smooth_control/outputs/optics_temporal_smooth_AD2"
RULES_JSON="$AD2_WS/alpha-diagnosis/discovery_cycle_01.json"
RULES_PROGRAM="$AD2_WS/alpha-diagnosis/discovery_configs/cycle_01/outputs/optics_temporal_smooth_AD2_drd_c01_r00/archive/attempt_0005/code.py"
WORKFLOW="$ROOT/agentic-evolve/alpha-diagnosis/workflows/optics_temporal_smooth_pro_reinject_c1.yaml"
PRO_WS="$ROOT/agentic-evolve/examples/adaptive_temporal_smooth_control/outputs/optics_temporal_smooth_AD2_pro_c1"

echo "=== Pro injection replay (Cycle 1, fork at stuck #1) ==="
echo "Source: $AD2_WS"
echo "Target: $PRO_WS"

python alpha-diagnosis/scripts/run_manual_injection.py \
  "$WORKFLOW" \
  --rules-json "$RULES_JSON" \
  --rules-program "$RULES_PROGRAM" \
  --fork-from "$AD2_WS" \
  --fork-at-stuck 1 \
  --cycle 1 \
  --save-prompt "$PRO_WS/injection_pro_prompt.md" \
  -v

echo ""
echo "=== Results ==="
python - <<'PY'
import json
from pathlib import Path

ws = Path("examples/adaptive_temporal_smooth_control/outputs/optics_temporal_smooth_AD2_pro_c1")
baseline = 0.8417287314609242
best_score = baseline
best_id = "attempt_0032"
for p in sorted((ws / "archive").glob("attempt_*/result.json")):
    r = json.loads(p.read_text())
    if r.get("is_valid") and r.get("score", float("-inf")) > best_score:
        best_score = r["score"]
        best_id = p.parent.name
print(f"Baseline (pre-injection): {baseline:.6f} (attempt_0032)")
print(f"Best after Pro injection:   {best_score:.6f} ({best_id})")
print(f"Delta: {best_score - baseline:+.6f}")
print(f"Beat stuck baseline: {best_score > baseline}")
traj = ws / "score_trajectory.jsonl"
if traj.is_file():
    print(f"Trajectory: {traj}")
PY
