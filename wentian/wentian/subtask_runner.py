from __future__ import annotations

from pathlib import Path

from agentic_evolve.config import load_config
from agentic_evolve.session import run_evolution_until_done

from wentian.config_schema import WenTianConfig
from wentian.global_archive import GlobalArchive
from wentian.hub_plan import SubtaskSpec
from wentian.opencode_lock import opencode_session_lock
from wentian.subtask_summary import summarize_subtask, write_subtask_summary
from wentian.workspace_prep import build_subtask_prompt, prepare_subtask_workspace


def run_subtask(
    workflow: WenTianConfig,
    spec: SubtaskSpec,
    global_archive: GlobalArchive,
    *,
    round_num: int,
    verbose: bool = False,
    fresh: bool = True,
) -> dict:
    """Run a single sub-task evolution and return result metadata."""
    base_config = load_config(workflow.task.base_config)
    config_path, brief = prepare_subtask_workspace(
        workflow,
        spec,
        global_archive,
        fresh=fresh,
    )

    def prompt_factory() -> str:
        return build_subtask_prompt(config_path, brief)

    with opencode_session_lock():
        evo = run_evolution_until_done(
            config_path,
            fresh=False,
            resume=not fresh,
            prompt_factory=prompt_factory,
            verbose=verbose,
            auto_resume=workflow.loop.auto_resume_on_early_exit,
            session_mode=f"wentian_subtask:{spec.id}",
        )

    config = evo["config"]
    archive = evo["archive"]
    summary = summarize_subtask(
        spec.id,
        config.archive_dir,
        round_num=round_num,
        maximize=config.maximize,
        spec=spec,
    )
    summary_path = workflow.subtasks_root / spec.id / "summary.json"
    write_subtask_summary(summary, summary_path)

    return {
        "subtask_id": spec.id,
        "spec": spec,
        "config_path": config_path,
        "workspace_dir": config.workspace_dir,
        "archive_dir": config.archive_dir,
        "status": evo["status"],
        "stopped_reason": evo.get("stopped_reason"),
        "summary": summary,
        "summary_path": summary_path,
    }
