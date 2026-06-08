"""Standalone testdata registry (copied into workspaces; no package install required)."""

from __future__ import annotations

import json
import os
from pathlib import Path

REGISTRY_FILENAME = ".registry.json"
TESTDATA_ENV_VAR = "AGENTIC_EVOLVE_TESTDATA_DIR"
HIDDEN_TESTDATA_ENV_VAR = "AGENTIC_EVOLVE_HIDDEN_TESTDATA"


def find_registry_file(start: Path | None = None) -> Path | None:
    if start is None:
        return None
    for parent in [start.resolve(), *start.resolve().parents]:
        if (parent / "agentic_evolve").is_dir() and (parent / "pyproject.toml").is_file():
            reg = parent / REGISTRY_FILENAME
            if reg.is_file():
                return reg
    return None


def lookup_testdata_dir(project_name: str, start: Path | None = None) -> Path | None:
    reg = find_registry_file(start)
    if reg is None:
        return None
    with open(reg, encoding="utf-8") as f:
        data = json.load(f) or {}
    entry = data.get(project_name) or {}
    raw = entry.get("testdata_dir")
    if not raw:
        return None
    resolved = Path(raw)
    return resolved if resolved.is_dir() else None


def evaluation_env(
    project_name: str,
    *,
    hidden_testdata: bool = False,
    start: Path | None = None,
    base: dict[str, str] | None = None,
) -> dict[str, str]:
    env = dict(base or os.environ)
    testdata = lookup_testdata_dir(project_name, start=start)
    if testdata is not None:
        env[TESTDATA_ENV_VAR] = str(testdata)
    if hidden_testdata:
        env[HIDDEN_TESTDATA_ENV_VAR] = "1"
    return env
