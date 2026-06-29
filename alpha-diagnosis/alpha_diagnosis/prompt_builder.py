from __future__ import annotations

from pathlib import Path
from typing import List

from jinja2 import Template

from agentic_evolve.archive import Archive
from agentic_evolve.prompt_builder import build_prompt

from alpha_diagnosis.config_schema import InjectionConfig, WorkflowConfig
from alpha_diagnosis.injection_counterfactual import build_counterfactual_injection_context
from alpha_diagnosis.injection_pro import (
    build_pro_injection_context,
    load_rule_functions,
    resolve_rule_program_path,
)
from alpha_diagnosis.rule_extract import RuleSpec
from alpha_diagnosis.vague_rule import vagueify_rule_description

INJECTION_MODES = frozenset({"per_rule_variants", "pro", "counterfactual"})

CONTINUATION_PHASE_INTRO = """Continue in the SAME OpenCode session. Do not restart from scratch.

Primary evolution plateaued; alpha-diagnosis produced the rule-guided injection below.
Apply these directions while keeping your prior evolution context.

"""


def _maybe_continuation_prompt(base: str, injection: str, *, continuation: bool) -> str:
    if continuation:
        return CONTINUATION_PHASE_INTRO + injection
    return base + "\n" + injection


def injection_quota_target(injection: InjectionConfig, rule_count: int) -> int:
    if injection.mode == "pro":
        return injection.max_submissions
    return rule_count


def build_rule_guided_prompt(
    workflow: WorkflowConfig,
    archive: Archive,
    workspace_dir: Path,
    max_improvements: int,
    rules: List[RuleSpec],
    *,
    resumed: bool = True,
    agent_readable_evaluator: bool = True,
    hidden_testdata: bool = False,
    prompt_history_top_n: int = 20,
    prompt_history_recent_n: int = 20,
    prompt_history_max_feedback_chars: int = 400,
    cycle: int = 1,
    rule_program_path: Path | None = None,
    continuation: bool = False,
) -> str:
    if workflow.injection.mode == "pro":
        return build_rule_guided_pro_prompt(
            workflow,
            archive,
            workspace_dir,
            max_improvements,
            rules,
            cycle=cycle,
            resumed=resumed,
            agent_readable_evaluator=agent_readable_evaluator,
            hidden_testdata=hidden_testdata,
            prompt_history_top_n=prompt_history_top_n,
            prompt_history_recent_n=prompt_history_recent_n,
            prompt_history_max_feedback_chars=prompt_history_max_feedback_chars,
            rule_program_path=rule_program_path,
            continuation=continuation,
        )

    if workflow.injection.mode == "counterfactual":
        return build_rule_guided_counterfactual_prompt(
            workflow,
            archive,
            workspace_dir,
            max_improvements,
            rules,
            cycle=cycle,
            resumed=resumed,
            agent_readable_evaluator=agent_readable_evaluator,
            hidden_testdata=hidden_testdata,
            prompt_history_top_n=prompt_history_top_n,
            prompt_history_recent_n=prompt_history_recent_n,
            prompt_history_max_feedback_chars=prompt_history_max_feedback_chars,
            rule_program_path=rule_program_path,
            continuation=continuation,
        )

    base = build_prompt(
        archive,
        workspace_dir,
        max_improvements,
        resumed=resumed,
        hidden_testdata=hidden_testdata,
        agent_readable_evaluator=agent_readable_evaluator,
        prompt_history_top_n=prompt_history_top_n,
        prompt_history_recent_n=prompt_history_recent_n,
        prompt_history_max_feedback_chars=prompt_history_max_feedback_chars,
    )
    best = archive.best()
    best_id = best.attempt_id if best else "none"

    vague = workflow.injection.vague_rule_injection
    if vague:
        template_path = workflow.adapter.prompt_template_vague or (
            workflow.alpha_diagnosis_root / "templates/rule_guided_prompt_vague.md.j2"
        )
        display_rules = [
            RuleSpec(
                index=r.index,
                name=r.name,
                description=vagueify_rule_description(r.name, r.description),
                score_effect=r.score_effect,
            )
            for r in rules
        ]
    else:
        template_path = workflow.adapter.prompt_template
        display_rules = rules

    if not template_path.is_absolute():
        template_path = workflow.alpha_diagnosis_root / template_path
    template = Template(template_path.read_text(encoding="utf-8"))
    injection = template.render(
        rules=display_rules,
        best_attempt_id=best_id,
        include_rule_weights=workflow.injection.include_rule_weights,
    )
    return _maybe_continuation_prompt(base, injection, continuation=continuation)


def build_rule_guided_pro_prompt(
    workflow: WorkflowConfig,
    archive: Archive,
    workspace_dir: Path,
    max_improvements: int,
    rules: List[RuleSpec],
    *,
    cycle: int = 1,
    resumed: bool = True,
    agent_readable_evaluator: bool = True,
    hidden_testdata: bool = False,
    prompt_history_top_n: int = 20,
    prompt_history_recent_n: int = 20,
    prompt_history_max_feedback_chars: int = 400,
    rule_program_path: Path | None = None,
    continuation: bool = False,
) -> str:
    base = build_prompt(
        archive,
        workspace_dir,
        max_improvements,
        resumed=resumed,
        hidden_testdata=hidden_testdata,
        agent_readable_evaluator=agent_readable_evaluator,
        prompt_history_top_n=prompt_history_top_n,
        prompt_history_recent_n=prompt_history_recent_n,
        prompt_history_max_feedback_chars=prompt_history_max_feedback_chars,
    )
    best = archive.best()
    best_id = best.attempt_id if best else "none"
    best_score = best.score if best else None

    inj = workflow.injection
    program_path = resolve_rule_program_path(
        explicit=rule_program_path or inj.pro_rule_program,
        workspace_dir=workspace_dir,
        cycle=cycle,
        fallback_task_dir=(
            workflow.discovery.task_dir if workflow.discovery is not None else None
        ),
    )
    rule_fns, rule_names = load_rule_functions(program_path)

    ctx = build_pro_injection_context(
        archive.archive_dir,
        rules,
        rule_fns,
        rule_names,
        exemplars_per_rule=inj.pro_exemplars_per_rule,
        top_k=inj.pro_top_k_attempts,
        max_code_lines=inj.pro_max_code_lines,
        maximize=archive.maximize,
        best_attempt_id=best_id,
        best_score=best_score,
        exclude_baseline_from_exemplars=inj.pro_exclude_baseline_from_exemplars,
        cooccurrence_top_n=inj.pro_cooccurrence_top_n,
        cooccurrence_min_rules=inj.pro_cooccurrence_min_rules,
        cooccurrence_max_rules=inj.pro_cooccurrence_max_rules,
        synthesis_seed_count=inj.pro_synthesis_seed_count,
    )

    baseline_gaps = ctx.baseline_gaps
    baseline_satisfied = baseline_gaps.satisfied_positive if baseline_gaps else []
    baseline_missing = baseline_gaps.missing_positive if baseline_gaps else []
    baseline_missing_desc = baseline_gaps.missing_positive_descriptions if baseline_gaps else []

    template_path = workflow.alpha_diagnosis_root / "templates/rule_guided_prompt_pro.md.j2"
    template = Template(template_path.read_text(encoding="utf-8"))
    injection = template.render(
        cycle=cycle,
        rules=rules,
        rule_exemplars=ctx.rule_exemplars,
        top_k_coverage=ctx.top_k_coverage,
        rule_cooccurrence=ctx.rule_cooccurrence,
        synthesis_seeds=ctx.synthesis_seeds,
        baseline_attempt_id=best_id,
        baseline_score=best_score,
        baseline_satisfied_rules=baseline_satisfied,
        baseline_missing_positive=baseline_missing,
        baseline_missing_descriptions=baseline_missing_desc,
        baseline_satisfied_negative=baseline_gaps.satisfied_negative if baseline_gaps else [],
        include_rule_weights=inj.include_rule_weights,
        exemplars_per_rule=inj.pro_exemplars_per_rule,
        top_k=inj.pro_top_k_attempts,
        max_proposals=inj.pro_max_proposals,
        min_new_positive_rules=inj.pro_min_new_positive_rules,
        cooccurrence_min_rules=inj.pro_cooccurrence_min_rules,
        cooccurrence_max_rules=inj.pro_cooccurrence_max_rules,
    )
    return _maybe_continuation_prompt(base, injection, continuation=continuation)


def build_rule_guided_counterfactual_prompt(
    workflow: WorkflowConfig,
    archive: Archive,
    workspace_dir: Path,
    max_improvements: int,
    rules: List[RuleSpec],
    *,
    cycle: int = 1,
    resumed: bool = True,
    agent_readable_evaluator: bool = True,
    hidden_testdata: bool = False,
    prompt_history_top_n: int = 20,
    prompt_history_recent_n: int = 20,
    prompt_history_max_feedback_chars: int = 400,
    rule_program_path: Path | None = None,
    continuation: bool = False,
) -> str:
    base = build_prompt(
        archive,
        workspace_dir,
        max_improvements,
        resumed=resumed,
        hidden_testdata=hidden_testdata,
        agent_readable_evaluator=agent_readable_evaluator,
        prompt_history_top_n=prompt_history_top_n,
        prompt_history_recent_n=prompt_history_recent_n,
        prompt_history_max_feedback_chars=prompt_history_max_feedback_chars,
    )
    best = archive.best()
    best_id = best.attempt_id if best else "none"
    best_score = best.score if best else None

    inj = workflow.injection
    program_path = resolve_rule_program_path(
        explicit=rule_program_path or inj.cf_rule_program,
        workspace_dir=workspace_dir,
        cycle=cycle,
        fallback_task_dir=(
            workflow.discovery.task_dir if workflow.discovery is not None else None
        ),
    )
    rule_fns, rule_names = load_rule_functions(program_path)

    ctx = build_counterfactual_injection_context(
        archive.archive_dir,
        rules,
        rule_fns,
        rule_names,
        baseline_attempt_id=best_id,
        baseline_score=best_score,
        top_k=inj.cf_top_k_attempts,
        max_code_lines=inj.cf_max_code_lines,
        maximize=archive.maximize,
    )

    template_path = (
        workflow.alpha_diagnosis_root / "templates/rule_guided_prompt_counterfactual.md.j2"
    )
    template = Template(template_path.read_text(encoding="utf-8"))
    injection = template.render(
        cycle=cycle,
        rules=rules,
        counterfactual_pairs=ctx.pairs,
        baseline_attempt_id=best_id,
        baseline_score=best_score,
        warnings=ctx.warnings,
        include_rule_weights=inj.include_rule_weights,
    )
    return _maybe_continuation_prompt(base, injection, continuation=continuation)


def build_primary_continuation_prompt(
    archive: Archive,
    workspace_dir: Path,
    max_improvements: int,
    *,
    mode: str = "standard",
    agent_readable_evaluator: bool = True,
    hidden_testdata: bool = False,
) -> str:
    from agentic_evolve.prompt_builder import build_continuation_prompt

    prompt = build_continuation_prompt(
        archive,
        workspace_dir,
        max_improvements,
        mode=mode,
    )
    return (
        prompt
        + "\nRule injection for this diagnosis cycle is complete. "
        "Resume open evolution in the same session (no rule quota).\n"
    )


def validate_injection_config(injection: InjectionConfig, rule_count: int) -> None:
    if injection.mode not in INJECTION_MODES:
        raise ValueError(f"Unsupported injection mode: {injection.mode}")
    if injection.mode == "per_rule_variants":
        if injection.max_submissions < rule_count:
            raise ValueError(
                f"injection.max_submissions ({injection.max_submissions}) < rule count ({rule_count})"
            )
    elif injection.mode == "counterfactual":
        if injection.max_submissions < rule_count:
            raise ValueError(
                f"injection.max_submissions ({injection.max_submissions}) < rule count ({rule_count})"
            )
    elif injection.mode == "pro":
        if injection.max_submissions < injection.pro_max_proposals:
            raise ValueError(
                f"injection.max_submissions ({injection.max_submissions}) < "
                f"pro_max_proposals ({injection.pro_max_proposals})"
            )
        if injection.pro_exemplars_per_rule < 1:
            raise ValueError("injection.pro_exemplars_per_rule must be >= 1")
        if injection.pro_top_k_attempts < 1:
            raise ValueError("injection.pro_top_k_attempts must be >= 1")
