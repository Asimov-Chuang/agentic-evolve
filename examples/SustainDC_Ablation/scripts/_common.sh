#!/usr/bin/env bash
# Shared helpers for SustainDC ablation replicate runs.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
AE_ROOT="$(cd "$EXAMPLE_DIR/../.." && pwd)"

REPLICATE_START="${REPLICATE_START:-2}"
REPLICATE_END="${REPLICATE_END:-8}"

USE_CLOUDGPT="${USE_CLOUDGPT:-1}"
USE_BLIND_PERMISSIONS="${USE_BLIND_PERMISSIONS:-1}"
CLOUDGPT_MODEL="${CLOUDGPT_MODEL:-cloudgpt/DeepSeek-V4-Pro}"
CLOUDGPT_SMALL_MODEL="${CLOUDGPT_SMALL_MODEL:-cloudgpt/gpt-4o-mini-20240718}"
DEFAULT_OPENCODE_CONFIG="$AE_ROOT/opencode.cloudgpt.json"
BLIND_OPENCODE_CONFIG="$EXAMPLE_DIR/opencode.blind_ablation.json"

if [[ "$USE_BLIND_PERMISSIONS" == "1" ]]; then
  python3 "$SCRIPT_DIR/build_blind_opencode_config.py"
  OPENCODE_CONFIG="${OPENCODE_CONFIG:-$BLIND_OPENCODE_CONFIG}"
else
  OPENCODE_CONFIG="${OPENCODE_CONFIG:-$DEFAULT_OPENCODE_CONFIG}"
fi

if [[ -f "$AE_ROOT/activate-env.sh" ]]; then
  # shellcheck disable=SC1091
  source "$AE_ROOT/activate-env.sh"
fi

if [[ -f "$AE_ROOT/setup-path.sh" ]]; then
  # shellcheck disable=SC1091
  source "$AE_ROOT/setup-path.sh"
fi

setup_cloudgpt() {
  if [[ "$USE_CLOUDGPT" != "1" ]]; then
    return 0
  fi

  export OPENCODE_CONFIG
  export CLOUDGPT_MODEL
  export CLOUDGPT_SMALL_MODEL

  if [[ -z "${CLOUDGPT_USE_AZURE_CLI:-}" ]] && command -v az >/dev/null 2>&1 && az account show >/dev/null 2>&1; then
    export CLOUDGPT_USE_AZURE_CLI=1
  fi

  echo "CloudGPT enabled"
  echo "  OPENCODE_CONFIG=$OPENCODE_CONFIG"
  echo "  USE_BLIND_PERMISSIONS=$USE_BLIND_PERMISSIONS"
  echo "  CLOUDGPT_MODEL=$CLOUDGPT_MODEL"
  echo "  CLOUDGPT_SMALL_MODEL=$CLOUDGPT_SMALL_MODEL"

  bash "$AE_ROOT/scripts/start-cloudgpt-proxy.sh"

  if ! curl -fsS "http://${CLOUDGPT_PROXY_HOST:-127.0.0.1}:${CLOUDGPT_PROXY_PORT:-8765}/health" >/dev/null; then
    echo "error: CloudGPT proxy health check failed" >&2
    echo "  See $AE_ROOT/.cloudgpt-proxy.log" >&2
    return 1
  fi
}

run_agentic_evolve() {
  setup_cloudgpt
  agentic-evolve "$@"
}

write_replicate_config() {
  local base_config="$1"
  local tmp_config="$2"
  local project_name="$3"

  python3 - "$base_config" "$tmp_config" "$project_name" <<'PY'
import sys
from pathlib import Path

base = Path(sys.argv[1])
out = Path(sys.argv[2])
project_name = sys.argv[3]
path_keys = ("problem:", "initial_program:", "evaluator:", "analyzer:", "opencode_config:")

lines_out: list[str] = []
for raw in base.read_text(encoding="utf-8").splitlines():
    if raw.startswith("project_name:"):
        lines_out.append(f"project_name: {project_name}")
        continue
    matched = False
    for key in path_keys:
        if raw.startswith(key):
            value = raw.split(":", 1)[1].strip()
            if value and not value.startswith("../") and not Path(value).is_absolute():
                lines_out.append(f"{key} ../{value}")
            else:
                lines_out.append(raw)
            matched = True
            break
    if not matched:
        lines_out.append(raw)

out.write_text("\n".join(lines_out) + "\n", encoding="utf-8")
PY
}

run_replicates() {
  local base_config="$1"
  local project_prefix="$2"

  if [[ ! -f "$base_config" ]]; then
    echo "error: config not found: $base_config" >&2
    return 1
  fi

  local run_config_dir="$EXAMPLE_DIR/.run_configs"
  mkdir -p "$run_config_dir"

  local output_group=""
  if output_group="$(grep -E '^output_group:' "$base_config" | head -1 | awk '{print $2}')"; then
    :
  fi

  cd "$AE_ROOT"

  local i project_name tmp_config config_stem workspace_hint
  for ((i = REPLICATE_START; i <= REPLICATE_END; i++)); do
    project_name="${project_prefix}_${i}"
    if [[ -n "$output_group" ]]; then
      config_stem="${output_group}_${project_name}"
    else
      config_stem="$project_name"
    fi
    tmp_config="$run_config_dir/${config_stem}.yaml"
    write_replicate_config "$base_config" "$tmp_config" "$project_name"

    if [[ -n "$output_group" ]]; then
      workspace_hint="${EXAMPLE_DIR}/.run_configs/outputs/${output_group}/${project_name}"
    else
      workspace_hint="${EXAMPLE_DIR}/.run_configs/outputs/${project_name}"
    fi

    echo "============================================================"
    echo "Running replicate ${i}/${REPLICATE_END}: ${project_name}"
    echo "Config: ${tmp_config}"
    echo "Workspace: ${workspace_hint}"
    echo "============================================================"

    run_agentic_evolve run --fresh "$tmp_config"
  done

  echo ""
  echo "Finished replicates ${REPLICATE_START}-${REPLICATE_END} for prefix: ${project_prefix}"
}