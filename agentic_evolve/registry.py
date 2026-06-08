"""Registry for evaluation assets kept outside agent workspaces."""

from __future__ import annotations

import json
import os
from pathlib import Path

from agentic_evolve._registry import (
    HIDDEN_TESTDATA_ENV_VAR,
    TESTDATA_ENV_VAR,
    evaluation_env as _evaluation_env,
    find_registry_file,
)

REGISTRY_FILENAME = ".registry.json"


def _package_root() -> Path:
    found = find_registry_file(Path(__file__).resolve().parent)
    if found is not None:
        return found.parent
    return Path(__file__).resolve().parent.parent


def registry_file() -> Path:
    return _package_root() / REGISTRY_FILENAME


def register_testdata(project_name: str, testdata_dir: Path) -> None:
    path = registry_file()
    data: dict[str, dict[str, str]] = {}
    if path.is_file():
        with open(path, encoding="utf-8") as f:
            data = json.load(f) or {}
    data[project_name] = {"testdata_dir": str(testdata_dir.resolve())}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def lookup_testdata_dir(project_name: str) -> Path | None:
    from agentic_evolve._registry import lookup_testdata_dir as _lookup

    return _lookup(project_name, start=Path(__file__).resolve().parent)


def evaluation_env(
    project_name: str,
    *,
    hidden_testdata: bool = False,
    base: dict[str, str] | None = None,
) -> dict[str, str]:
    return _evaluation_env(
        project_name,
        hidden_testdata=hidden_testdata,
        start=Path(__file__).resolve().parent,
        base=base,
    )


__all__ = [
    "REGISTRY_FILENAME",
    "TESTDATA_ENV_VAR",
    "HIDDEN_TESTDATA_ENV_VAR",
    "registry_file",
    "register_testdata",
    "lookup_testdata_dir",
    "evaluation_env",
]
