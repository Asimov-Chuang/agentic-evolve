from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


EVOLUTION_MODES = frozenset({"standard", "pro"})
AUTO_RESUME_MODES = frozenset({"continue", "new_session"})


DEFAULT_OPENCODE_ARGS = ["run", "--dangerously-skip-permissions"]


@dataclass
class OpenCodeConfig:
    command: str = "opencode"
    args: list[str] = field(default_factory=list)
    model: str | None = None
    small_model: str | None = None

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
    target_score: float | None = None
    opencode_config: Path | None = None
    testdata_dir: Path | None = None
    hidden_testdata: bool = False
    agent_readable_evaluator: bool = True
    verbose: bool = False
    source_archive: Path | None = None
    source_archive_top_n: int | None = None
    rule_set_size: int | None = None
    prompt_history_top_n: int = 20
    prompt_history_recent_n: int = 20
    prompt_history_max_feedback_chars: int = 400
    analyzer_max_feedback_lines: int | None = None
    store_raw_artifacts: bool = True
    discovery_sample_type: str = "trajectory"
    mechanism: dict[str, Any] | None = None
    mode: str = "standard"
    auto_resume_on_early_exit: bool = True
    auto_resume_mode: str = "continue"
    output_group: str | None = None

    @property
    def output_root(self) -> Path:
        base = self.config_dir / "outputs"
        if self.output_group:
            return base / self.output_group / self.project_name
        return base / self.project_name

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
    opencode_config = (
        resolve_path(config_dir, raw["opencode_config"])
        if raw.get("opencode_config")
        else None
    )

    max_improvements = raw.get("max_improvements")
    if max_improvements is None and "iterations" in raw:
        max_improvements = raw["iterations"]
    if max_improvements is None:
        max_improvements = 10

    target_score = None
    if raw.get("target_score") is not None:
        target_score = float(raw["target_score"])

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

    prompt_history_top_n = int(raw.get("prompt_history_top_n", 20))
    prompt_history_recent_n = int(raw.get("prompt_history_recent_n", 20))
    prompt_history_max_feedback_chars = int(raw.get("prompt_history_max_feedback_chars", 400))
    for name, value in (
        ("prompt_history_top_n", prompt_history_top_n),
        ("prompt_history_recent_n", prompt_history_recent_n),
        ("prompt_history_max_feedback_chars", prompt_history_max_feedback_chars),
    ):
        if value < 0:
            raise ValueError(f"{name} must be >= 0")

    analyzer_max_feedback_lines = None
    if raw.get("analyzer_max_feedback_lines") is not None:
        analyzer_max_feedback_lines = int(raw["analyzer_max_feedback_lines"])
        if analyzer_max_feedback_lines < 1:
            raise ValueError("analyzer_max_feedback_lines must be >= 1")

    discovery_sample_type = str(raw.get("discovery_sample_type", "trajectory"))
    if discovery_sample_type not in ("trajectory", "code"):
        raise ValueError(
            "discovery_sample_type must be 'trajectory' or 'code', "
            f"got {discovery_sample_type!r}"
        )

    mode = str(raw.get("mode", "standard"))
    if mode not in EVOLUTION_MODES:
        raise ValueError(f"mode must be one of {sorted(EVOLUTION_MODES)}, got {mode!r}")

    analyzer = resolve_path(config_dir, raw["analyzer"]) if raw.get("analyzer") else None
    if mode == "pro" and analyzer is None:
        raise ValueError("mode: pro requires an analyzer (set analyzer: in config.yaml)")

    store_raw_artifacts = bool(raw.get("store_raw_artifacts", True))
    if mode == "pro" and not store_raw_artifacts:
        print(
            "warning: mode: pro requires raw artifacts; forcing store_raw_artifacts: true",
            file=sys.stderr,
        )
        store_raw_artifacts = True

    auto_resume_mode = str(raw.get("auto_resume_mode", "continue"))
    if auto_resume_mode not in AUTO_RESUME_MODES:
        raise ValueError(
            f"auto_resume_mode must be one of {sorted(AUTO_RESUME_MODES)}, "
            f"got {auto_resume_mode!r}"
        )

    return Config(
        project_name=str(raw["project_name"]),
        maximize=bool(raw.get("maximize", True)),
        problem=resolve_path(config_dir, raw["problem"]),
        initial_program=resolve_path(config_dir, raw["initial_program"]),
        evaluator=resolve_path(config_dir, raw["evaluator"]),
        analyzer=analyzer,
        max_improvements=int(max_improvements),
        agent_timeout_seconds=int(raw.get("agent_timeout_seconds", 3600)),
        evaluation_timeout_seconds=int(raw.get("evaluation_timeout_seconds", 60)),
        opencode=OpenCodeConfig(
            command=str(opencode_raw.get("command", "opencode")),
            args=list(opencode_raw.get("args") or []),
            model=str(opencode_raw["model"]) if opencode_raw.get("model") else None,
            small_model=str(opencode_raw["small_model"])
            if opencode_raw.get("small_model")
            else None,
        ),
        config_dir=config_dir,
        target_score=target_score,
        opencode_config=opencode_config,
        testdata_dir=testdata_dir,
        hidden_testdata=bool(raw.get("hidden_testdata", False)),
        agent_readable_evaluator=bool(raw.get("agent_readable_evaluator", True)),
        verbose=bool(raw.get("verbose", False)),
        source_archive=source_archive,
        source_archive_top_n=source_archive_top_n,
        rule_set_size=rule_set_size,
        prompt_history_top_n=prompt_history_top_n,
        prompt_history_recent_n=prompt_history_recent_n,
        prompt_history_max_feedback_chars=prompt_history_max_feedback_chars,
        analyzer_max_feedback_lines=analyzer_max_feedback_lines,
        store_raw_artifacts=store_raw_artifacts,
        discovery_sample_type=discovery_sample_type,
        mechanism=dict(raw["mechanism"]) if raw.get("mechanism") else None,
        mode=mode,
        auto_resume_on_early_exit=bool(raw.get("auto_resume_on_early_exit", True)),
        auto_resume_mode=auto_resume_mode,
        output_group=str(raw["output_group"]) if raw.get("output_group") else None,
    )


def resolve_path(config_dir: Path, relative: str | Path) -> Path:
    p = Path(relative)
    if p.is_absolute():
        return p
    return (config_dir / p).resolve()
