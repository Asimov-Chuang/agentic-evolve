"""Private evaluation runner (example source only — not copied to workspace)."""

from __future__ import annotations

import importlib.util
import json
import pickle
import sys
import traceback
from pathlib import Path


def _load_module(module_path: Path):
    spec = importlib.util.spec_from_file_location("fb_evaluator_core", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cmd_evaluate(core_path: Path, program_path: str, output_dir: str) -> dict:
    module = _load_module(core_path)
    return module.evaluate(program_path, output_dir)


def cmd_analyze(core_path: Path, program_path: str, result: dict, noise_ratio: float) -> dict:
    module = _load_module(core_path)
    return module._analyze_with_noise_ratio(program_path, result, noise_ratio)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: _private_runner.py evaluate|analyze ...", file=sys.stderr)
        return 2

    command = argv[1]
    try:
        if command == "evaluate":
            core_path = Path(argv[2]).resolve()
            program_path = argv[3]
            output_dir = argv[4]
            payload = cmd_evaluate(core_path, program_path, output_dir)
        elif command == "analyze":
            core_path = Path(argv[2]).resolve()
            program_path = argv[3]
            result = json.loads(argv[4])
            noise_ratio = float(argv[5])
            payload = cmd_analyze(core_path, program_path, result, noise_ratio)
        else:
            raise ValueError(f"unknown command: {command}")
    except Exception:
        pickle.dump({"error": traceback.format_exc()}, sys.stdout.buffer)
        return 1

    pickle.dump({"ok": payload}, sys.stdout.buffer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
