#!/usr/bin/env bash
# One-step dev environment setup for WSL.
#
# Usage (from anywhere):
#   source /path/to/agentic-evolve/activate-env.sh
#
# Or from Evaluator-Discovery root:
#   source agentic-evolve/activate-env.sh

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$_SCRIPT_DIR" || return 1

source setup-path.sh || return 1
source .venv/bin/activate || return 1
source env.sh

echo "agentic-evolve environment ready. ($(pwd))"