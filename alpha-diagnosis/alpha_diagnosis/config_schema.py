from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class StuckConfig:
    consecutive_no_improvement: int = 10
    poll_interval_seconds: int = 30
    # Do not declare stuck until this many submissions in the current evolution session.
    min_attempts_before_stuck: int = 0


DISCOVERY_MODES = frozenset({"regression", "agent_review", "algorithm_based_rule"})


@dataclass
class DiscoveryConfig:
    mode: str = "regression"
    task_dir: Path | None = None
    rule_set_size: int = 8
    source_top_n: int = 30
    runs: int = 3
    max_improvements: int = 50
    fresh_each_run: bool = True
    agent_timeout_seconds: int = 3600
    evaluation_timeout_seconds: int = 600
    # When set, discovery stops early once archive best R² reaches this value
    # (skips remaining max_improvements and proceeds to injection).
    early_injection_r2_threshold: float | None = None


@dataclass
class ForkConfig:
    source_workspace: Path
    at_stuck_cycle: int | None = None
    at_attempt: int | None = None
    # When True, skip re-evolving to stuck and run diagnosis immediately after fork.
    start_at_diagnosis: bool = False


INJECTION_MODES = frozenset({"per_rule_variants", "pro", "counterfactual"})


@dataclass
class InjectionConfig:
    mode: str = "per_rule_variants"
    include_rule_weights: bool = False
    max_submissions: int = 8
    vague_rule_injection: bool = False
    # Hard-stop injection after quota target + quota_tolerance submissions (default +2 slack).
    quota_tolerance: int = 2
    # Pro mode: exemplars per rule, top-K coverage, synthesis proposal count.
    pro_exemplars_per_rule: int = 2
    pro_top_k_attempts: int = 10
    pro_max_proposals: int = 3
    pro_rule_program: Path | None = None
    pro_max_code_lines: int = 35
    pro_exclude_baseline_from_exemplars: bool = True
    pro_cooccurrence_top_n: int = 5
    pro_cooccurrence_min_rules: int = 2
    pro_cooccurrence_max_rules: int = 3
    pro_synthesis_seed_count: int = 3
    pro_min_new_positive_rules: int = 2
    # Counterfactual mode: trajectory pairs from raw-artifact.json (mode detection).
    cf_top_k_attempts: int = 15
    cf_max_code_lines: int = 40
    cf_rule_program: Path | None = None


@dataclass
class LoopConfig:
    max_diagnosis_cycles: int = 5
    resume_after_injection: bool = True
    auto_resume_on_early_exit: bool = True
    shared_opencode_session: bool = True


@dataclass
class PrimaryConfig:
    config_path: Path
    project_name: str | None = None
    store_raw_artifacts: bool | None = None


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
    fork: ForkConfig | None = None
    alpha_diagnosis_root: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)
    store_raw_artifacts: bool | None = None


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
        store_raw_artifacts=(
            bool(primary_raw["store_raw_artifacts"])
            if primary_raw.get("store_raw_artifacts") is not None
            else None
        ),
    )

    stuck_raw = raw.get("stuck") or {}
    consecutive = stuck_raw.get("consecutive_no_improvement")
    if consecutive is None:
        # Backward compat: old workflows used `window` for the same idea.
        consecutive = stuck_raw.get("window", 10)
    stuck = StuckConfig(
        consecutive_no_improvement=int(consecutive),
        poll_interval_seconds=int(stuck_raw.get("poll_interval_seconds", 30)),
        min_attempts_before_stuck=int(stuck_raw.get("min_attempts_before_stuck", 0)),
    )
    if stuck.min_attempts_before_stuck < 0:
        raise ValueError("stuck.min_attempts_before_stuck must be >= 0")

    discovery = None
    if raw.get("discovery"):
        d = raw["discovery"]
        mode = str(d.get("mode", "regression"))
        if mode not in DISCOVERY_MODES:
            raise ValueError(f"discovery.mode must be one of {sorted(DISCOVERY_MODES)}, got {mode!r}")
        task_dir: Path | None = None
        if d.get("task_dir"):
            task_dir = _resolve(alpha_root, d["task_dir"])
        if mode in ("regression", "algorithm_based_rule") and task_dir is None:
            raise ValueError(
                f"discovery.task_dir is required when discovery.mode is {mode!r}"
            )
        early_r2_raw = d.get("early_injection_r2_threshold")
        early_r2: float | None = None
        if early_r2_raw is not None:
            early_r2 = float(early_r2_raw)
            if not (0.0 <= early_r2 <= 1.0):
                raise ValueError("discovery.early_injection_r2_threshold must be between 0 and 1")
        discovery = DiscoveryConfig(
            mode=mode,
            task_dir=task_dir,
            rule_set_size=int(d.get("rule_set_size", 8)),
            source_top_n=int(d.get("source_top_n", 30)),
            runs=int(d.get("runs", 3)),
            max_improvements=int(d.get("max_improvements", 50)),
            fresh_each_run=bool(d.get("fresh_each_run", True)),
            agent_timeout_seconds=int(d.get("agent_timeout_seconds", 3600)),
            evaluation_timeout_seconds=int(d.get("evaluation_timeout_seconds", 600)),
            early_injection_r2_threshold=early_r2,
        )

    fork = None
    if raw.get("fork"):
        f = raw["fork"]
        at_stuck = f.get("at_stuck_cycle")
        at_attempt = f.get("at_attempt")
        if at_stuck is not None and at_attempt is not None:
            raise ValueError("fork: specify at_stuck_cycle or at_attempt, not both")
        if at_stuck is None and at_attempt is None:
            raise ValueError("fork: at_stuck_cycle or at_attempt is required")
        start_raw = f.get("start_at_diagnosis")
        if start_raw is None:
            start_at_diagnosis = at_stuck is not None
        else:
            start_at_diagnosis = bool(start_raw)
        fork = ForkConfig(
            source_workspace=_resolve(alpha_root, f["source_workspace"]),
            at_stuck_cycle=int(at_stuck) if at_stuck is not None else None,
            at_attempt=int(at_attempt) if at_attempt is not None else None,
            start_at_diagnosis=start_at_diagnosis,
        )

    injection_raw = raw.get("injection") or {}
    quota_tol = int(injection_raw.get("quota_tolerance", injection_raw.get("tol", 2)))
    if quota_tol < 0:
        raise ValueError("injection.quota_tolerance must be >= 0")
    inj_mode = str(injection_raw.get("mode", "per_rule_variants"))
    if inj_mode not in INJECTION_MODES:
        raise ValueError(f"injection.mode must be one of {sorted(INJECTION_MODES)}, got {inj_mode!r}")
    pro_rule_raw = injection_raw.get("pro_rule_program")
    pro_rule_program = (
        _resolve(alpha_root, pro_rule_raw) if pro_rule_raw else None
    )
    cf_rule_raw = injection_raw.get("cf_rule_program")
    cf_rule_program = _resolve(alpha_root, cf_rule_raw) if cf_rule_raw else None
    injection = InjectionConfig(
        mode=inj_mode,
        include_rule_weights=bool(injection_raw.get("include_rule_weights", False)),
        max_submissions=int(injection_raw.get("max_submissions", 8)),
        vague_rule_injection=bool(injection_raw.get("vague_rule_injection", False)),
        quota_tolerance=quota_tol,
        pro_exemplars_per_rule=int(injection_raw.get("pro_exemplars_per_rule", 2)),
        pro_top_k_attempts=int(injection_raw.get("pro_top_k_attempts", 10)),
        pro_max_proposals=int(injection_raw.get("pro_max_proposals", 3)),
        pro_rule_program=pro_rule_program,
        pro_max_code_lines=int(injection_raw.get("pro_max_code_lines", 35)),
        pro_exclude_baseline_from_exemplars=bool(
            injection_raw.get("pro_exclude_baseline_from_exemplars", True)
        ),
        pro_cooccurrence_top_n=int(injection_raw.get("pro_cooccurrence_top_n", 5)),
        pro_cooccurrence_min_rules=int(injection_raw.get("pro_cooccurrence_min_rules", 2)),
        pro_cooccurrence_max_rules=int(injection_raw.get("pro_cooccurrence_max_rules", 3)),
        pro_synthesis_seed_count=int(injection_raw.get("pro_synthesis_seed_count", 3)),
        pro_min_new_positive_rules=int(injection_raw.get("pro_min_new_positive_rules", 2)),
        cf_top_k_attempts=int(injection_raw.get("cf_top_k_attempts", 15)),
        cf_max_code_lines=int(injection_raw.get("cf_max_code_lines", 40)),
        cf_rule_program=cf_rule_program,
    )

    loop_raw = raw.get("loop") or {}
    loop = LoopConfig(
        max_diagnosis_cycles=int(loop_raw.get("max_diagnosis_cycles", 5)),
        resume_after_injection=bool(loop_raw.get("resume_after_injection", True)),
        auto_resume_on_early_exit=bool(loop_raw.get("auto_resume_on_early_exit", True)),
        shared_opencode_session=bool(loop_raw.get("shared_opencode_session", True)),
    )

    return WorkflowConfig(
        name=str(raw.get("name", path.stem)),
        adapter=adapter,
        primary=primary,
        stuck=stuck,
        discovery=discovery,
        injection=injection,
        loop=loop,
        fork=fork,
        alpha_diagnosis_root=alpha_root,
        store_raw_artifacts=(
            bool(raw["store_raw_artifacts"])
            if raw.get("store_raw_artifacts") is not None
            else None
        ),
    )
