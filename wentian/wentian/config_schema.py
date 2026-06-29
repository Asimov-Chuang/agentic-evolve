from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class TaskConfig:
    base_config: Path
    project_name: str | None = None


@dataclass
class HubConfig:
    max_rounds: int = 10
    agent_timeout_seconds: int = 1800
    prompt_template: Path = field(default_factory=lambda: Path("templates/hub_prompt.md.j2"))
    max_plan_retries: int = 2


@dataclass
class SubtaskDefaults:
    max_improvements: int = 50
    agent_timeout_seconds: int = 3600


@dataclass
class SubtasksConfig:
    defaults: SubtaskDefaults = field(default_factory=SubtaskDefaults)
    max_parallel: int = 3
    sequential: bool = True


@dataclass
class GlobalArchiveConfig:
    top_n: int = 50


@dataclass
class LoopConfig:
    resume: bool = True
    auto_resume_on_early_exit: bool = True


@dataclass
class WenTianConfig:
    name: str
    task: TaskConfig
    hub: HubConfig = field(default_factory=HubConfig)
    subtasks: SubtasksConfig = field(default_factory=SubtasksConfig)
    global_archive: GlobalArchiveConfig = field(default_factory=GlobalArchiveConfig)
    loop: LoopConfig = field(default_factory=LoopConfig)
    wentian_root: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)

    @property
    def output_root(self) -> Path:
        if self.task.project_name:
            return self.wentian_root / "outputs" / self.task.project_name
        return self.wentian_root / "outputs" / self.name

    @property
    def global_archive_dir(self) -> Path:
        return self.output_root / "global_archive"

    @property
    def hub_dir(self) -> Path:
        return self.output_root / "hub"

    @property
    def state_path(self) -> Path:
        return self.output_root / "wentian" / "state.json"

    @property
    def score_trajectory_path(self) -> Path:
        return self.output_root / "wentian" / "score_trajectory.jsonl"

    @property
    def subtasks_root(self) -> Path:
        return self.output_root / "subtasks"


def _resolve(base: Path, relative: str | Path) -> Path:
    path = Path(relative)
    if path.is_absolute():
        return path
    return (base / path).resolve()


def load_wentian_config(path: Path) -> WenTianConfig:
    with open(path, encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    root = path.parent
    wentian_pkg_root = path.parent.parent if path.parent.name == "workflows" else path.parent
    agentic_evolve_root = wentian_pkg_root.parent

    task_raw = raw.get("task") or {}
    if not task_raw.get("base_config"):
        raise ValueError("task.base_config is required")

    base_config_path = task_raw["base_config"]
    base_path = Path(base_config_path)
    if base_path.is_absolute():
        resolved_base = base_path
    elif str(base_config_path).startswith("examples/"):
        resolved_base = _resolve(agentic_evolve_root, base_config_path)
    else:
        resolved_base = _resolve(root, base_config_path)

    hub_raw = raw.get("hub") or {}
    tmpl = hub_raw.get("prompt_template", "templates/hub_prompt.md.j2")
    tmpl_path = _resolve(wentian_pkg_root, tmpl)

    subtasks_raw = raw.get("subtasks") or {}
    defaults_raw = subtasks_raw.get("defaults") or {}
    defaults = SubtaskDefaults(
        max_improvements=int(defaults_raw.get("max_improvements", 50)),
        agent_timeout_seconds=int(defaults_raw.get("agent_timeout_seconds", 3600)),
    )
    max_parallel = int(subtasks_raw.get("max_parallel", 3))
    if max_parallel < 1:
        raise ValueError("subtasks.max_parallel must be >= 1")
    sequential = bool(subtasks_raw.get("sequential", True))

    ga_raw = raw.get("global_archive") or {}
    loop_raw = raw.get("loop") or {}

    return WenTianConfig(
        name=str(raw.get("name", path.stem)),
        task=TaskConfig(
            base_config=resolved_base,
            project_name=task_raw.get("project_name"),
        ),
        hub=HubConfig(
            max_rounds=int(hub_raw.get("max_rounds", 10)),
            agent_timeout_seconds=int(hub_raw.get("agent_timeout_seconds", 1800)),
            prompt_template=tmpl_path,
            max_plan_retries=int(hub_raw.get("max_plan_retries", 2)),
        ),
        subtasks=SubtasksConfig(defaults=defaults, max_parallel=max_parallel, sequential=sequential),
        global_archive=GlobalArchiveConfig(top_n=int(ga_raw.get("top_n", 50))),
        loop=LoopConfig(
            resume=bool(loop_raw.get("resume", True)),
            auto_resume_on_early_exit=bool(loop_raw.get("auto_resume_on_early_exit", True)),
        ),
        wentian_root=wentian_pkg_root,
    )
