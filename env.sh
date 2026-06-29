#!/usr/bin/env bash
# Frontier-Engineering + agentic-evolve environment for WSL.
# Usage (from agentic-evolve repo root):
#   source .venv/bin/activate
#   source setup-path.sh
#   source env.sh

export FRONTIER_ENGINEERING_ROOT="/mnt/c/Users/v-shuhazhang/projects/Evaluator-Discovery/Frontier-Engineering"
export FRONTIER_EVAL_UV_ENVS_DIR="${HOME}/.venvs/frontier-engineering"
export UV_LINK_MODE="copy"

export GENERAL_MEIO_PYTHON="${FRONTIER_EVAL_UV_ENVS_DIR}/frontier-v1-main/bin/python"
export OPTICS_PYTHON="${GENERAL_MEIO_PYTHON}"
export FRONTIER_EVAL_DRIVER_PYTHON="${FRONTIER_EVAL_UV_ENVS_DIR}/frontier-eval-driver/bin/python"
export HIGH_RELIABLE_SIM_PYTHON="${FRONTIER_EVAL_DRIVER_PYTHON}"
export SUSTAINDC_PYTHON="${FRONTIER_EVAL_UV_ENVS_DIR}/frontier-v1-sustaindc/bin/python"
export EV2GYM_PYTHON="${FRONTIER_EVAL_DRIVER_PYTHON}"
export PID_TUNING_PYTHON="${FRONTIER_EVAL_DRIVER_PYTHON}"
