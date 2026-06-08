from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


DEFAULT_OPENCODE_ARGS = ["run", "--dangerously-skip-permissions"]


@dataclass
class OpenCodeConfig:
    command: str = "opencode"
    args: list[str] = field(default_factory=list)

    def resolved_args(self) -> list[str]:
        return self.args if self.args else list(DEFAULT_OPENCODE_ARGS)


@dataclass
class Config:
    project_name: str
    maximize: bool
    problem: Path
    initial_program: Path
    evaluator: Path
    analyzer: Path | None
    max_improvements: int
    agent_timeout_seconds: int
    evaluation_timeout_seconds: int
    opencode: OpenCodeConfig
    config_dir: Path
    testdata_dir: Path | None = None
    hidden_testdata: bool = False
    agent_readable_evaluator: bool = True
    verbose: bool = False
    source_archive: Path | None = None
    source_archive_top_n: int | None = None
    rule_set_size: int | None = None

    @property
    def output_root(self) -> Path:
        return self.config_dir / "outputs" / self.project_name

    @property
    def workspace_dir(self) -> Path:
        return self.output_root

    @property
    def archive_dir(self) -> Path:
        return self.workspace_dir / "archive"

    @property
    def best_program_path(self) -> Path:
        return self.output_root / "best_program.py"


def load_config(config_path: str | Path) -> Config:
    path = Path(config_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Config not found: {path}")

    with open(path, encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    config_dir = path.parent
    opencode_raw = raw.get("opencode") or {}

    max_improvements = raw.get("max_improvements")
    if max_improvements is None and "iterations" in raw:
        max_improvements = raw["iterations"]
    if max_improvements is None:
        max_improvements = 10

    testdata_dir = None
    if raw.get("testdata"):
        testdata_dir = resolve_path(config_dir, raw["testdata"])

    source_archive = None
    if raw.get("source_archive"):
        source_archive = resolve_path(config_dir, raw["source_archive"])

    rule_set_size = None
    if raw.get("rule_set_size") is not None:
        rule_set_size = int(raw["rule_set_size"])

    source_archive_top_n = None
    if raw.get("source_archive_top_n") is not None:
        source_archive_top_n = int(raw["source_archive_top_n"])
        if source_archive_top_n < 1:
            raise ValueError("source_archive_top_n must be >= 1")

    return Config(
        project_name=str(raw["project_name"]),
        maximize=bool(raw.get("maximize", True)),
        problem=resolve_path(config_dir, raw["problem"]),
        initial_program=resolve_path(config_dir, raw["initial_program"]),
        evaluator=resolve_path(config_dir, raw["evaluator"]),
        analyzer=resolve_path(config_dir, raw["analyzer"]) if raw.get("analyzer") else None,
        max_improvements=int(max_improvements),
        agent_timeout_seconds=int(raw.get("agent_timeout_seconds", 3600)),
        evaluation_timeout_seconds=int(raw.get("evaluation_timeout_seconds", 60)),
        opencode=OpenCodeConfig(
            command=str(opencode_raw.get("command", "opencode")),
            args=list(opencode_raw.get("args") or []),
        ),
        config_dir=config_dir,
        testdata_dir=testdata_dir,
        hidden_testdata=bool(raw.get("hidden_testdata", False)),
        agent_readable_evaluator=bool(raw.get("agent_readable_evaluator", True)),
        verbose=bool(raw.get("verbose", False)),
        source_archive=source_archive,
        source_archive_top_n=source_archive_top_n,
        rule_set_size=rule_set_size,
    )


def resolve_path(config_dir: Path, relative: str | Path) -> Path:
    p = Path(relative)
    if p.is_absolute():
        return p
    return (config_dir / p).resolve()
