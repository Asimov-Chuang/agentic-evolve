from __future__ import annotations

import json
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from agentic_evolve.archive import save_best_program
from agentic_evolve.config import load_config

from wentian.config_schema import WenTianConfig, load_wentian_config
from wentian.global_archive import GlobalArchive
from wentian.hub_agent import run_hub_agent
from wentian.hub_plan import HubPlan, SubtaskSpec
from wentian.score_trajectory import record_event
from wentian.subtask_runner import run_subtask


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class WenTianState:
    workflow_name: str
    round: int = 0
    completed_subtasks: list[str] = field(default_factory=list)
    hub_history: list[dict] = field(default_factory=list)
    global_best: dict | None = None
    finished: bool = False
    final_summary: str = ""
    updated_at: str = ""

    @classmethod
    def load(cls, path: Path, workflow_name: str) -> WenTianState:
        if not path.is_file():
            return cls(workflow_name=workflow_name, updated_at=_now())
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        return cls(
            workflow_name=str(raw.get("workflow_name", workflow_name)),
            round=int(raw.get("round", 0)),
            completed_subtasks=list(raw.get("completed_subtasks") or []),
            hub_history=list(raw.get("hub_history") or []),
            global_best=raw.get("global_best"),
            finished=bool(raw.get("finished", False)),
            final_summary=str(raw.get("final_summary") or ""),
            updated_at=str(raw.get("updated_at", "")),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.updated_at = _now()
        with open(path, encoding="utf-8", mode="w") as f:
            json.dump(asdict(self), f, indent=2)


def _subtask_has_archive(workflow: WenTianConfig, subtask_id: str) -> bool:
    from agentic_evolve.archive import Archive

    base = load_config(workflow.task.base_config)
    config_path = base.config_dir / f".wentian_{workflow.name}_{subtask_id}.yaml"
    if not config_path.is_file():
        return False
    config = load_config(config_path)
    if not config.archive_dir.is_dir():
        return False
    return bool(Archive(config.archive_dir, config.maximize).list_attempts())


def _ensure_global_archive_seeded(workflow: WenTianConfig, global_archive: GlobalArchive) -> None:
    if global_archive.list_attempts():
        return
    base = load_config(workflow.task.base_config)
    seed_workspace = workflow.output_root / "_seed_workspace"
    seed_workspace.mkdir(parents=True, exist_ok=True)
    global_archive.seed_from_initial_program(
        base.initial_program,
        base.evaluator,
        workspace_dir=seed_workspace,
        evaluation_timeout_seconds=base.evaluation_timeout_seconds,
        analyzer_path=base.analyzer,
        store_raw_artifacts=base.store_raw_artifacts,
    )


def _update_global_best(state: WenTianState, global_archive: GlobalArchive) -> None:
    best = global_archive.best()
    if best:
        state.global_best = {"attempt_id": best.attempt_id, "score": best.score}


def _save_final_solution(
    workflow: WenTianConfig,
    global_archive: GlobalArchive,
    plan: HubPlan,
) -> Path:
    dest = workflow.output_root / "best_program.py"
    report_path = workflow.output_root / "final_report.json"

    if plan.best_ref and plan.best_ref.attempt_id:
        attempt_dir = global_archive.get_attempt_dir(plan.best_ref.attempt_id)
        if attempt_dir is not None:
            shutil.copy2(attempt_dir / "code.py", dest)
        else:
            best = global_archive.best()
            if best:
                shutil.copy2(best.code_path, dest)
    else:
        best = global_archive.best()
        if best:
            save_best_program(global_archive.inner, dest, best.code_path)

    report = {
        "reasoning": plan.reasoning,
        "final_summary": plan.final_summary,
        "best_ref": asdict(plan.best_ref) if plan.best_ref else None,
        "global_best": state_global_best(global_archive),
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return dest


def state_global_best(global_archive: GlobalArchive) -> dict | None:
    best = global_archive.best()
    if not best:
        return None
    return {"attempt_id": best.attempt_id, "score": best.score}


def _run_pending_subtasks(
    workflow: WenTianConfig,
    global_archive: GlobalArchive,
    pending: list[SubtaskSpec],
    *,
    round_num: int,
    resume: bool,
    verbose: bool,
) -> tuple[list[dict], list[tuple[str, Exception]]]:
    def _run_one(spec: SubtaskSpec) -> dict:
        subtask_fresh = not (resume and _subtask_has_archive(workflow, spec.id))
        record_event(
            workflow.output_root,
            "subtask_start",
            round=round_num,
            subtask_id=spec.id,
            max_improvements=workflow.subtasks.defaults.max_improvements,
            sequential=workflow.subtasks.sequential,
        )
        result = run_subtask(
            workflow,
            spec,
            global_archive,
            round_num=round_num,
            verbose=verbose,
            fresh=subtask_fresh,
        )
        record_event(
            workflow.output_root,
            "subtask_end",
            round=round_num,
            subtask_id=spec.id,
            status=result["status"],
            stopped_reason=result.get("stopped_reason"),
            best_score=result["summary"].get("best_score"),
            best_attempt_id=result["summary"].get("best_attempt_id"),
            attempt_count=result["summary"].get("attempt_count"),
        )
        print(
            f"  subtask {spec.id}: status={result['status']} "
            f"best={result['summary'].get('best_score')}"
        )
        return result

    results: list[dict] = []
    errors: list[tuple[str, Exception]] = []

    if workflow.subtasks.sequential:
        for spec in pending:
            try:
                results.append(_run_one(spec))
            except Exception as exc:
                errors.append((spec.id, exc))
                print(f"  subtask {spec.id} failed: {exc}")
                record_event(
                    workflow.output_root,
                    "subtask_error",
                    round=round_num,
                    subtask_id=spec.id,
                    error=str(exc),
                )
    else:
        if workflow.subtasks.max_parallel > 1:
            print(
                "Note: OpenCode sessions run one at a time (shared DB); "
                f"max_parallel={workflow.subtasks.max_parallel} queues sub-tasks."
            )
        with ThreadPoolExecutor(max_workers=workflow.subtasks.max_parallel) as pool:
            futures = {pool.submit(_run_one, spec): spec for spec in pending}
            for future in as_completed(futures):
                spec = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    errors.append((spec.id, exc))
                    print(f"  subtask {spec.id} failed: {exc}")
                    record_event(
                        workflow.output_root,
                        "subtask_error",
                        round=round_num,
                        subtask_id=spec.id,
                        error=str(exc),
                    )

    return results, errors


def run_workflow(
    workflow_path: Path,
    *,
    resume: bool = False,
    verbose: bool = False,
) -> int:
    workflow = load_wentian_config(workflow_path.resolve())
    workflow.output_root.mkdir(parents=True, exist_ok=True)

    base_config = load_config(workflow.task.base_config)
    global_archive = GlobalArchive(
        workflow.global_archive_dir,
        maximize=base_config.maximize,
        top_n=workflow.global_archive.top_n,
    )

    state = WenTianState.load(workflow.state_path, workflow.name)
    if resume and state.finished:
        print(f"Workflow already finished. Best at {workflow.output_root / 'best_program.py'}")
        return 0

    _ensure_global_archive_seeded(workflow, global_archive)
    _update_global_best(state, global_archive)

    record_event(
        workflow.output_root,
        "workflow_start",
        workflow_name=workflow.name,
        resume=resume,
        sequential=workflow.subtasks.sequential,
        max_parallel=workflow.subtasks.max_parallel,
        global_best=state.global_best,
    )

    start_round = state.round if resume else 0
    if not resume:
        state = WenTianState(workflow_name=workflow.name, updated_at=_now())

    previous_plan: HubPlan | None = None
    if state.hub_history:
        last = state.hub_history[-1]
        previous_plan = HubPlan(
            action=str(last.get("action", "")),
            reasoning=str(last.get("reasoning", "")),
        )

    for round_num in range(start_round + 1, workflow.hub.max_rounds + 1):
        print(f"\n=== WenTian round {round_num}/{workflow.hub.max_rounds} ===")
        record_event(
            workflow.output_root,
            "round_start",
            round=round_num,
            max_rounds=workflow.hub.max_rounds,
            global_best=state.global_best,
        )
        global_archive.summary_for_hub()

        plan = run_hub_agent(
            workflow,
            global_archive,
            round_num=round_num,
            verbose=verbose,
            previous_plan=previous_plan,
        )
        state.hub_history.append(
            {
                "round": round_num,
                "action": plan.action,
                "reasoning": plan.reasoning,
                "subtask_ids": [s.id for s in plan.subtasks],
                "at": _now(),
            }
        )
        previous_plan = plan
        state.save(workflow.state_path)

        record_event(
            workflow.output_root,
            "hub_plan",
            round=round_num,
            action=plan.action,
            reasoning=plan.reasoning,
            subtask_ids=[s.id for s in plan.subtasks],
        )

        if plan.action == "finish":
            print(f"Hub decided to finish: {plan.reasoning[:200]}")
            dest = _save_final_solution(workflow, global_archive, plan)
            state.finished = True
            state.final_summary = plan.final_summary
            state.round = round_num
            _update_global_best(state, global_archive)
            state.save(workflow.state_path)
            record_event(
                workflow.output_root,
                "workflow_finish",
                round=round_num,
                global_best=state.global_best,
                final_summary=plan.final_summary,
            )
            print(f"Saved best program to {dest}")
            return 0

        pending = [s for s in plan.subtasks if s.id not in state.completed_subtasks]
        if not pending:
            print("All subtasks in plan already completed; continuing to next hub round.")
            state.round = round_num
            state.save(workflow.state_path)
            continue

        mode = "sequential" if workflow.subtasks.sequential else f"parallel(max={workflow.subtasks.max_parallel})"
        print(f"Spawning {len(pending)} subtask(s), mode={mode}")

        results, errors = _run_pending_subtasks(
            workflow,
            global_archive,
            pending,
            round_num=round_num,
            resume=resume,
            verbose=verbose,
        )

        if errors and not results:
            raise RuntimeError(
                "All subtasks failed: " + "; ".join(f"{sid}: {exc}" for sid, exc in errors)
            )
        if errors:
            print(f"Warning: {len(errors)} subtask(s) failed; re-run with --resume to retry.")

        for result in results:
            imported = global_archive.merge_subtask_archive(
                result["archive_dir"],
                subtask_id=result["subtask_id"],
                round_num=round_num,
            )
            record_event(
                workflow.output_root,
                "global_merge",
                round=round_num,
                subtask_id=result["subtask_id"],
                imported_count=len(imported),
                global_best=state_global_best(global_archive),
            )
            if result["subtask_id"] not in state.completed_subtasks:
                state.completed_subtasks.append(result["subtask_id"])

        state.round = round_num
        _update_global_best(state, global_archive)
        state.save(workflow.state_path)
        record_event(
            workflow.output_root,
            "round_end",
            round=round_num,
            global_best=state.global_best,
            completed_subtasks=list(state.completed_subtasks),
        )
        print(f"Round {round_num} complete. Global best: {state.global_best}")

    print(f"Reached max_rounds ({workflow.hub.max_rounds}) without hub finish.")
    best = global_archive.best()
    if best:
        dest = workflow.output_root / "best_program.py"
        shutil.copy2(best.code_path, dest)
        print(f"Saved global best to {dest}")
    state.round = workflow.hub.max_rounds
    _update_global_best(state, global_archive)
    state.save(workflow.state_path)
    record_event(
        workflow.output_root,
        "workflow_max_rounds",
        round=workflow.hub.max_rounds,
        global_best=state.global_best,
    )
    return 0
