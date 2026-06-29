"""Workspace analyzer delegate; calls private ATSC feedback logic."""

from __future__ import annotations

import json
import os
import pickle
import subprocess
import sys
from pathlib import Path

DEFAULT_TIMEOUT_SECONDS = 120
ENV_ROOT = "ATSC_ABLATION_EXAMPLE_ROOT"


def _example_root() -> Path:
    env_root = os.environ.get(ENV_ROOT)
    if env_root:
        return Path(env_root).resolve()
    here = Path(__file__).resolve().parent
    for candidate in (here, *here.parents):
        if (candidate / "evaluator_core.py").is_file():
            return candidate
    raise RuntimeError("Cannot locate atsc_ablation example root")


def _timeout_seconds() -> int:
    meta_path = Path(__file__).resolve().parent / "workspace_meta.json"
    if meta_path.is_file():
        with open(meta_path, encoding="utf-8") as f:
            return int(json.load(f).get("evaluation_timeout_seconds", DEFAULT_TIMEOUT_SECONDS))
    return DEFAULT_TIMEOUT_SECONDS


def _run_analyze(program_path: str, output_dir: str, result: dict, feedback_mode: str) -> dict:
    example_root = _example_root()
    runner = example_root / "_private_runner.py"
    core = example_root / "evaluator_core.py"
    if not runner.is_file() or not core.is_file():
        raise RuntimeError("Private analyzer runner is unavailable")

    env = dict(os.environ)
    env[ENV_ROOT] = str(example_root)

    completed = subprocess.run(
        [
            sys.executable,
            str(runner),
            "analyze",
            str(core),
            program_path,
            output_dir,
            json.dumps(result, default=str),
            feedback_mode,
        ],
        capture_output=True,
        timeout=_timeout_seconds(),
        env=env,
    )
    if completed.returncode != 0:
        err = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(err or "Private analyzer runner failed")

    payload = pickle.loads(completed.stdout)
    if "error" in payload:
        raise RuntimeError(payload["error"])
    return payload["ok"]