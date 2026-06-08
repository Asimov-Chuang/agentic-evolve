from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class StuckConfig:
    consecutive_no_improvement: int = 10
    poll_interval_seconds: int = 30


@dataclass
class DiscoveryConfig:
    task_dir: Path
    rule_set_size: int = 8
    source_top_n: int = 30
    runs: int = 3
    max_improvements: int = 50
    fresh_each_run: bool = True
    agent_timeout_seconds: int = 3600
    evaluation_timeout_seconds: int = 600


@dataclass
class InjectionConfig:
    mode: str = "per_rule_variants"
    include_rule_weights: bool = False
    max_submissions: int = 8
    vague_rule_injection: bool = False


@dataclass
class LoopConfig:
    max_diagnosis_cycles: int = 5
    resume_after_injection: bool = True
    auto_resume_on_early_exit: bool = True


@dataclass
class PrimaryConfig:
    config_path: Path
    project_name: str | None = None


@dataclass
class AdapterConfig:
    task_id: str
    trajectory_format: str
    rule_description_source: str
    prompt_template: Path
    prompt_template_vague: Path | None = None
    factor_label_style: str = "numbered"


@dataclass
class WorkflowConfig:
    name: str
    adapter: AdapterConfig
    primary: PrimaryConfig
    stuck: StuckConfig = field(default_factory=StuckConfig)
    discovery: DiscoveryConfig | None = None
    injection: InjectionConfig = field(default_factory=InjectionConfig)
    loop: LoopConfig = field(default_factory=LoopConfig)
    alpha_diagnosis_root: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)


def _resolve(base: Path, relative: str | Path) -> Path:
    path = Path(relative)
    if path.is_absolute():
        return path
    return (base / path).resolve()


def load_adapter(path: Path, alpha_root: Path | None = None) -> AdapterConfig:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    root = path.parent
    alpha = alpha_root or root.parent
    tmpl = raw.get("prompt_template", "templates/rule_guided_prompt.md.j2")
    if not Path(tmpl).is_absolute():
        tmpl_path = alpha / tmpl
    else:
        tmpl_path = Path(tmpl)

    vague_tmpl = raw.get("prompt_template_vague", "templates/rule_guided_prompt_vague.md.j2")
    vague_tmpl_path: Path | None
    if vague_tmpl:
        vague_tmpl_path = (alpha / vague_tmpl).resolve() if not Path(vague_tmpl).is_absolute() else Path(vague_tmpl).resolve()
    else:
        vague_tmpl_path = None

    return AdapterConfig(
        task_id=str(raw["task_id"]),
        trajectory_format=str(raw.get("trajectory_format", "none")),
        rule_description_source=str(raw.get("rule_description_source", "metrics.rule_descriptions")),
        prompt_template=tmpl_path.resolve(),
        prompt_template_vague=vague_tmpl_path,
        factor_label_style=str(raw.get("factor_label_style", "numbered")),
    )


def load_workflow(path: Path) -> WorkflowConfig:
    with open(path, encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    root = path.parent
    alpha_root = path.parent.parent
    adapter_path = _resolve(alpha_root, raw["adapter"])
    adapter = load_adapter(adapter_path, alpha_root=alpha_root)

    primary_raw = raw.get("primary") or {}
    primary = PrimaryConfig(
        config_path=_resolve(alpha_root, primary_raw["config"]),
        project_name=primary_raw.get("project_name"),
    )

    stuck_raw = raw.get("stuck") or {}
    consecutive = stuck_raw.get("consecutive_no_improvement")
    if consecutive is None:
        # Backward compat: old workflows used `window` for the same idea.
        consecutive = stuck_raw.get("window", 10)
    stuck = StuckConfig(
        consecutive_no_improvement=int(consecutive),
        poll_interval_seconds=int(stuck_raw.get("poll_interval_seconds", 30)),
    )

    discovery = None
    if raw.get("discovery"):
        d = raw["discovery"]
        discovery = DiscoveryConfig(
            task_dir=_resolve(alpha_root, d["task_dir"]),
            rule_set_size=int(d.get("rule_set_size", 8)),
            source_top_n=int(d.get("source_top_n", 30)),
            runs=int(d.get("runs", 3)),
            max_improvements=int(d.get("max_improvements", 50)),
            fresh_each_run=bool(d.get("fresh_each_run", True)),
            agent_timeout_seconds=int(d.get("agent_timeout_seconds", 3600)),
            evaluation_timeout_seconds=int(d.get("evaluation_timeout_seconds", 600)),
        )

    injection_raw = raw.get("injection") or {}
    injection = InjectionConfig(
        mode=str(injection_raw.get("mode", "per_rule_variants")),
        include_rule_weights=bool(injection_raw.get("include_rule_weights", False)),
        max_submissions=int(injection_raw.get("max_submissions", 8)),
        vague_rule_injection=bool(injection_raw.get("vague_rule_injection", False)),
    )

    loop_raw = raw.get("loop") or {}
    loop = LoopConfig(
        max_diagnosis_cycles=int(loop_raw.get("max_diagnosis_cycles", 5)),
        resume_after_injection=bool(loop_raw.get("resume_after_injection", True)),
        auto_resume_on_early_exit=bool(loop_raw.get("auto_resume_on_early_exit", True)),
    )

    return WorkflowConfig(
        name=str(raw.get("name", path.stem)),
        adapter=adapter,
        primary=primary,
        stuck=stuck,
        discovery=discovery,
        injection=injection,
        loop=loop,
        alpha_diagnosis_root=alpha_root,
    )
