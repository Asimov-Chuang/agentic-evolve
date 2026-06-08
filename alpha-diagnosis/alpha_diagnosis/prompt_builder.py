from __future__ import annotations

from pathlib import Path
from typing import List

from jinja2 import Template

from agentic_evolve.archive import Archive
from agentic_evolve.prompt_builder import build_prompt

from alpha_diagnosis.config_schema import InjectionConfig, WorkflowConfig
from alpha_diagnosis.rule_extract import RuleSpec
from alpha_diagnosis.vague_rule import vagueify_rule_description


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
) -> str:
    base = build_prompt(
        archive,
        workspace_dir,
        max_improvements,
        resumed=resumed,
        hidden_testdata=hidden_testdata,
        agent_readable_evaluator=agent_readable_evaluator,
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
            )
            for r in rules
        ]
    else:
        template_path = workflow.adapter.prompt_template
        display_rules = rules

    if not template_path.is_absolute():
        template_path = workflow.alpha_diagnosis_root / template_path
    template = Template(template_path.read_text(encoding="utf-8"))
    injection = template.render(rules=display_rules, best_attempt_id=best_id)
    return base + "\n" + injection


def validate_injection_config(injection: InjectionConfig, rule_count: int) -> None:
    if injection.mode != "per_rule_variants":
        raise ValueError(f"Unsupported injection mode: {injection.mode}")
    if injection.max_submissions < rule_count:
        raise ValueError(
            f"injection.max_submissions ({injection.max_submissions}) < rule count ({rule_count})"
        )
