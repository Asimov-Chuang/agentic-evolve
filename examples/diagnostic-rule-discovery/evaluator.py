"""Backward-compatible root evaluator; delegates to sustaindc/evaluator.py."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_sustaindc_evaluator():
    path = Path(__file__).resolve().parent / "sustaindc" / "evaluator.py"
    spec = importlib.util.spec_from_file_location("sustaindc_evaluator", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_mod = _load_sustaindc_evaluator()
evaluate = _mod.evaluate
_evaluate_core = _mod._evaluate_core

if __name__ == "__main__":
    program = sys.argv[1] if len(sys.argv) > 1 else "initial_program.py"
    out = sys.argv[2] if len(sys.argv) > 2 else "."
    print(json.dumps(evaluate(program, out), indent=2))
