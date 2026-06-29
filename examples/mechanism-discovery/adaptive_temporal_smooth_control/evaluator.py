"""Adaptive temporal smooth control mechanism discovery evaluator."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _import_base():
    candidates = [
        Path(__file__).resolve().parent.parent / "_shared",
        Path(__file__).resolve().parent / "_shared",
    ]
    for shared in candidates:
        base_path = shared / "evaluator_base.py"
        if base_path.is_file():
            import importlib.util

            spec = importlib.util.spec_from_file_location("evaluator_base", base_path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return module
    raise ImportError("Cannot find _shared/evaluator_base.py")


_base = _import_base()
strip_policy_visible_optics = _base.strip_policy_visible_optics
FORBIDDEN_OPTICS_ROOT_KEYS = _base.FORBIDDEN_OPTICS_ROOT_KEYS


def _evaluate_core(program_path: str, output_dir: str, workspace: Path) -> dict:
    return _base.evaluate_core(
        program_path,
        output_dir,
        workspace,
        strip_fn=strip_policy_visible_optics,
        extra_forbidden=FORBIDDEN_OPTICS_ROOT_KEYS,
    )


def evaluate(program_path: str, output_dir: str) -> dict:
    workspace = Path(__file__).resolve().parent
    evaluator_path = workspace / "evaluator.py"
    try:
        return _base.run_in_subprocess(program_path, output_dir, workspace, evaluator_path)
    except subprocess.TimeoutExpired:
        return _base._failure_result("Evaluation timed out")
    except Exception as exc:
        return _base._failure_result(f"Evaluation failed: {exc}")


if __name__ == "__main__":
    program = sys.argv[1] if len(sys.argv) > 1 else "initial_program.py"
    out = sys.argv[2] if len(sys.argv) > 2 else "."
    result = evaluate(program, out)
    print(json.dumps(result, indent=2))
