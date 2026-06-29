from __future__ import annotations

import json
import shutil
from pathlib import Path

from jinja2 import Template

from agentic_evolve.config import load_config
from agentic_evolve.opencode_runner import OpenCodeRunner

from wentian.config_schema import WenTianConfig
from wentian.global_archive import GlobalArchive
from wentian.hub_plan import HubPlan, HubPlanError, extract_json_from_text, load_hub_plan, parse_hub_plan
from wentian.opencode_lock import opencode_session_lock


PLAN_FILENAME = "plan.json"


def _collect_subtask_summaries(workflow: WenTianConfig) -> list[dict]:
    summaries: list[dict] = []
    subtasks_root = workflow.subtasks_root
    if not subtasks_root.is_dir():
        return summaries
    for summary_path in sorted(subtasks_root.glob("*/summary.json")):
        with open(summary_path, encoding="utf-8") as f:
            summaries.append(json.load(f))
    return summaries


def _prepare_hub_workspace(workflow: WenTianConfig) -> Path:
    hub_dir = workflow.hub_dir
    hub_dir.mkdir(parents=True, exist_ok=True)

    base_config = load_config(workflow.task.base_config)
    problem_dest = hub_dir / "problem.md"
    if not problem_dest.is_file():
        shutil.copy2(base_config.problem, problem_dest)

    return hub_dir


def build_hub_prompt(
    workflow: WenTianConfig,
    global_archive: GlobalArchive,
    *,
    round_num: int,
    max_rounds: int,
    previous_plan: HubPlan | None = None,
) -> str:
    template_path = workflow.hub.prompt_template
    if not template_path.is_file():
        raise FileNotFoundError(f"hub prompt template not found: {template_path}")

    template = Template(template_path.read_text(encoding="utf-8"))
    summaries = _collect_subtask_summaries(workflow)
    global_summary = global_archive.summary_for_hub()

    return template.render(
        workflow_name=workflow.name,
        round_num=round_num,
        max_rounds=max_rounds,
        global_archive_summary=global_summary,
        subtask_summaries=summaries,
        previous_plan=json.dumps(
            {
                "action": previous_plan.action,
                "reasoning": previous_plan.reasoning,
                "subtasks": [{"id": s.id} for s in previous_plan.subtasks],
            },
            indent=2,
        )
        if previous_plan
        else None,
        plan_path=f"hub/{PLAN_FILENAME}",
        defaults_max_improvements=workflow.subtasks.defaults.max_improvements,
        max_parallel=workflow.subtasks.max_parallel,
    )


def run_hub_agent(
    workflow: WenTianConfig,
    global_archive: GlobalArchive,
    *,
    round_num: int,
    verbose: bool = False,
    previous_plan: HubPlan | None = None,
) -> HubPlan:
    """Run hub OpenCode session and return validated plan."""
    hub_dir = _prepare_hub_workspace(workflow)
    plan_path = hub_dir / PLAN_FILENAME

    base_config = load_config(workflow.task.base_config)
    prompt = build_hub_prompt(
        workflow,
        global_archive,
        round_num=round_num,
        max_rounds=workflow.hub.max_rounds,
        previous_plan=previous_plan,
    )
    (hub_dir / "prompt.md").write_text(prompt, encoding="utf-8")

    runner = OpenCodeRunner(
        command=base_config.opencode.command,
        args=base_config.opencode.resolved_args(),
        verbose=verbose,
    )

    last_error: Exception | None = None
    for attempt in range(workflow.hub.max_plan_retries + 1):
        if plan_path.is_file():
            plan_path.unlink()

        with opencode_session_lock():
            result = runner.run(str(hub_dir), prompt, workflow.hub.agent_timeout_seconds)
        if not result.success and result.error:
            last_error = RuntimeError(result.error)

        if plan_path.is_file():
            try:
                return load_hub_plan(plan_path)
            except HubPlanError as exc:
                last_error = exc
                continue

        combined = (result.stdout or "") + "\n" + (result.stderr or "")
        if combined.strip():
            try:
                raw = extract_json_from_text(combined)
                plan = parse_hub_plan(raw)
                plan_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
                return plan
            except (HubPlanError, json.JSONDecodeError) as exc:
                last_error = exc

    raise HubPlanError(f"hub agent failed to produce valid plan after retries: {last_error}")
