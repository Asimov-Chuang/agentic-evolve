"""Private ATSC ablation runner; not intended for agent workspaces."""

from __future__ import annotations

import importlib.util
import json
import pickle
import sys
import traceback
from pathlib import Path


def _load_module(module_path: Path):
    spec = importlib.util.spec_from_file_location("atsc_ablation_core", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: _private_runner.py evaluate|analyze ...", file=sys.stderr)
        return 2

    command = argv[1]
    try:
        core_path = Path(argv[2]).resolve()
        module = _load_module(core_path)
        if command == "evaluate":
            payload = module.evaluate(argv[3], argv[4])
        elif command == "analyze":
            program_path = argv[3]
            output_dir = argv[4]
            result = json.loads(argv[5])
            feedback_mode = argv[6]
            payload = module.analyze(program_path, output_dir, result, feedback_mode)
        else:
            raise ValueError(f"unknown command: {command}")
    except Exception:
        pickle.dump({"error": traceback.format_exc()}, sys.stdout.buffer)
        return 1

    pickle.dump({"ok": payload}, sys.stdout.buffer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))