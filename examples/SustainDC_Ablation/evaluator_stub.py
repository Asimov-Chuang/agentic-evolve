"""Workspace evaluator stub; delegates private SustainDC scoring."""

from __future__ import annotations

import json
import os
import pickle
import subprocess
import sys
from pathlib import Path

DEFAULT_TIMEOUT_SECONDS = 300
ENV_ROOT = "SUSTAINDC_ABLATION_EXAMPLE_ROOT"


def _example_root() -> Path:
    env_root = os.environ.get(ENV_ROOT)
    if env_root:
        return Path(env_root).resolve()
    here = Path(__file__).resolve().parent
    for candidate in (here, *here.parents):
        if (candidate / "evaluator_core.py").is_file():
            return candidate
    raise RuntimeError("Cannot locate SustainDC_Ablation example root")


def _timeout_seconds() -> int:
    meta_path = Path(__file__).resolve().parent / "workspace_meta.json"
    if meta_path.is_file():
        with open(meta_path, encoding="utf-8") as f:
            return int(json.load(f).get("evaluation_timeout_seconds", DEFAULT_TIMEOUT_SECONDS))
    return DEFAULT_TIMEOUT_SECONDS


def _run_private(command: str, *args: str) -> dict:
    example_root = _example_root()
    runner = example_root / "_private_runner.py"
    core = example_root / "evaluator_core.py"
    if not runner.is_file() or not core.is_file():
        raise RuntimeError("Private evaluation runner is unavailable")

    env = dict(os.environ)
    env[ENV_ROOT] = str(example_root)

    completed = subprocess.run(
        [sys.executable, str(runner), command, str(core), *args],
        capture_output=True,
        timeout=_timeout_seconds(),
        env=env,
    )
    if completed.returncode != 0:
        err = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(err or "Private evaluation runner failed")

    payload = pickle.loads(completed.stdout)
    if "error" in payload:
        raise RuntimeError(payload["error"])
    return payload["ok"]


def evaluate(program_path: str, output_dir: str) -> dict:
    return _run_private("evaluate", program_path, output_dir)