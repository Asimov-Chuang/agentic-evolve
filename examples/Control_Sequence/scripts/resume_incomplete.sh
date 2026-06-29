#!/usr/bin/env bash
# Resume incomplete feedback-noise ablation runs one at a time until all reach
# 100 submissions. Uses existing workspaces under .run_configs/outputs/.
#
# Usage (from agentic-evolve repo root):
#   bash examples/feedback_noise_ablation/scripts/resume_incomplete.sh
#
# Optional env:
#   DRY_RUN=1              Print planned runs without executing
#   ORDER=remaining        Sort by remaining submissions (default)
#   ORDER=round_robin      Alternate across settings each iteration
#   ORDER=setting          Finish one setting before moving to the next
#   SETTING_FILTER=0pct    Only resume runs for one setting (0pct|50pct|80pct|score_only)
#   CONTINUE_ON_ERROR=1    Keep going if a run fails
#   USE_CLOUDGPT=1         Same as replicate scripts (default in _common.sh)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/_common.sh"

OUTPUTS_DIR="$EXAMPLE_DIR/.run_configs/outputs"
RUN_CONFIG_DIR="$EXAMPLE_DIR/.run_configs"
ORDER="${ORDER:-remaining}"
DRY_RUN="${DRY_RUN:-0}"
CONTINUE_ON_ERROR="${CONTINUE_ON_ERROR:-0}"

declare -A BASE_CONFIG=(
  [score_only]="$EXAMPLE_DIR/config_score_only.yaml"
  [0pct]="$EXAMPLE_DIR/config_0pct_noise.yaml"
  [50pct]="$EXAMPLE_DIR/config_50pct_noise.yaml"
  [80pct]="$EXAMPLE_DIR/config_80pct_noise.yaml"
)

declare -A PROJECT_PREFIX=(
  [score_only]="ablation_run"
  [0pct]="ablation_run"
  [50pct]="ablation_run"
  [80pct]="ablation_run"
)

declare -A BLIND_GROUP=(
  [score_only]="cond_a"
  [0pct]="cond_b"
  [50pct]="cond_c"
  [80pct]="cond_d"
)

list_incomplete_runs() {
  python3 - "$OUTPUTS_DIR" "$ORDER" "${SETTING_FILTER:-}" "$EXAMPLE_DIR" <<'PY'
import json
import sys
from collections import defaultdict
from pathlib import Path

outputs = Path(sys.argv[1])
order = sys.argv[2]
setting_filter = sys.argv[3].strip()
example_dir = Path(sys.argv[4])
sys.path.insert(0, str(example_dir))
from outputs_layout import SETTING_ORDER, iter_project_dirs, resolve_project_setting


def load_status(project_dir: Path) -> dict | None:
    traj = project_dir / "score_trajectory.jsonl"
    if not traj.is_file():
        return None

    attempt_count = 0
    remaining = 100
    completed = False
    best = None

    for line in traj.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("event") == "session_end":
            completed = (
                row.get("status") == "completed"
                and row.get("remaining", 1) == 0
            )
            if "remaining" in row:
                remaining = int(row["remaining"])
            if "attempt_count" in row:
                attempt_count = int(row["attempt_count"])
        if "best_so_far" in row:
            best = row["best_so_far"]
        if "attempt_count" in row:
            attempt_count = int(row["attempt_count"])
            remaining = max(0, 101 - attempt_count)

    if not completed and attempt_count >= 101:
        completed = True
        remaining = 0

    if completed:
        return None

    parsed = resolve_project_setting(project_dir.parent.name, project_dir.name)
    if parsed is None:
        return None
    setting, run_id = parsed
    if setting_filter and setting != setting_filter:
        return None

    return {
        "project_name": project_dir.name,
        "setting": setting,
        "run_id": run_id,
        "attempt_count": attempt_count,
        "remaining": remaining,
        "best_so_far": best,
        "workspace_rel": str(project_dir.relative_to(outputs)),
    }


incomplete: list[dict] = []
for setting, project_dir in iter_project_dirs(outputs):
    status = load_status(project_dir)
    if status:
        incomplete.append(status)

if order == "round_robin":
    by_setting: dict[str, list[dict]] = defaultdict(list)
    for item in incomplete:
        by_setting[item["setting"]].append(item)
    for setting in by_setting:
        by_setting[setting].sort(key=lambda x: (x["remaining"], x["run_id"]))
    ordered: list[dict] = []
    while True:
        progressed = False
        for setting in SETTING_ORDER:
            bucket = by_setting.get(setting)
            if bucket:
                ordered.append(bucket.pop(0))
                progressed = True
        if not progressed:
            break
    incomplete = ordered
elif order == "setting":
    incomplete.sort(key=lambda x: (SETTING_ORDER.index(x["setting"]), x["run_id"]))
else:
    incomplete.sort(key=lambda x: (x["remaining"], SETTING_ORDER.index(x["setting"]), x["run_id"]))

for item in incomplete:
    print(
        f"{item['project_name']}\t{item['setting']}\t{item['run_id']}\t"
        f"{item['attempt_count']}\t{item['remaining']}\t{item.get('best_so_far', '')}\t"
        f"{item['workspace_rel']}"
    )
PY
}

ensure_config() {
  local project_name="$1"
  local setting="$2"
  local blind_group="${BLIND_GROUP[$setting]:-}"
  local config_path=""

  if [[ -n "$blind_group" ]]; then
    config_path="$RUN_CONFIG_DIR/${blind_group}_${project_name}.yaml"
    if [[ -f "$config_path" ]]; then
      echo "$config_path"
      return 0
    fi
  fi

  config_path="$RUN_CONFIG_DIR/${project_name}.yaml"
  if [[ -f "$config_path" ]]; then
    echo "$config_path"
    return 0
  fi

  local base="${BASE_CONFIG[$setting]:-}"
  if [[ -z "$base" || ! -f "$base" ]]; then
    echo "error: missing base config for setting '$setting'" >&2
    return 1
  fi

  if [[ -n "$blind_group" ]]; then
    config_path="$RUN_CONFIG_DIR/${blind_group}_${project_name}.yaml"
  fi
  write_replicate_config "$base" "$config_path" "$project_name"
  echo "$config_path"
}

main() {
  if [[ ! -d "$OUTPUTS_DIR" ]]; then
    echo "error: outputs directory not found: $OUTPUTS_DIR" >&2
    return 1
  fi

  mapfile -t rows < <(list_incomplete_runs)
  local total="${#rows[@]}"

  if [[ "$total" -eq 0 ]]; then
    echo "All runs under $OUTPUTS_DIR are complete (100 submissions)."
    return 0
  fi

  echo "Found $total incomplete run(s) (ORDER=$ORDER)."
  echo ""
  printf "%-32s %-12s %5s %10s %10s %12s\n" "project" "setting" "run" "attempts" "remaining" "best_so_far"
  printf "%-32s %-12s %5s %10s %10s %12s\n" "-------" "-------" "---" "--------" "---------" "-----------"
  local row project_name setting run_id attempt_count remaining best_so_far workspace_rel config_path
  for row in "${rows[@]}"; do
    IFS=$'\t' read -r project_name setting run_id attempt_count remaining best_so_far workspace_rel <<<"$row"
    printf "%-32s %-12s %5s %10s %10s %12s\n" \
      "$project_name" "$setting" "$run_id" "$attempt_count/101" "$remaining" "$best_so_far"
  done
  echo ""

  if [[ "$DRY_RUN" == "1" ]]; then
    echo "DRY_RUN=1 — no runs started."
    return 0
  fi

  cd "$AE_ROOT"

  local idx=0
  for row in "${rows[@]}"; do
    idx=$((idx + 1))
    IFS=$'\t' read -r project_name setting run_id attempt_count remaining best_so_far workspace_rel <<<"$row"

    config_path="$(ensure_config "$project_name" "$setting")"

    echo "============================================================"
    echo "[$idx/$total] Resuming: $project_name"
    echo "  setting=$setting run_id=$run_id progress=${attempt_count}/101 remaining=$remaining"
    echo "  config: $config_path"
    echo "  workspace: $OUTPUTS_DIR/$workspace_rel"
    echo "============================================================"

    if ! run_agentic_evolve run --resume "$config_path"; then
      echo "error: resume failed for $project_name" >&2
      if [[ "$CONTINUE_ON_ERROR" != "1" ]]; then
        return 1
      fi
      echo "CONTINUE_ON_ERROR=1 — continuing with next run."
    fi
    echo ""
  done

  echo "Finished resume batch ($total run(s))."
}

main "$@"
