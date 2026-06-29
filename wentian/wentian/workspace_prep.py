from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import yaml

from agentic_evolve.archive import Archive, read_improvement_baseline, write_improvement_baseline
from agentic_evolve.checkpoint import Checkpoint, save_checkpoint
from agentic_evolve.config import Config, load_config
from agentic_evolve.evaluator import run_evaluation
from agentic_evolve.result_sidecars import finalize_attempt_result
from agentic_evolve.workspace import (
    _copy_workspace_files,
    _link_source_archive,
    _write_workspace_meta,
    evaluator_workspace_path,
)

from wentian.config_schema import WenTianConfig
from wentian.evolve_block import focus_prompt_append
from wentian.global_archive import GlobalArchive
from wentian.hub_plan import InitialProgramSpec, SeedArchiveSpec, SubtaskSpec


def _resolve_initial_program_path(
    spec: InitialProgramSpec | None,
    *,
    base_config: Config,
    global_archive: GlobalArchive,
) -> Path:
    if spec is None or spec.source == "global_best":
        best = global_archive.best()
        if best:
            dest = base_config.config_dir / f".wentian_seed_{best.attempt_id}.py"
            shutil.copy2(best.code_path, dest)
            return dest
        return base_config.initial_program
    if spec.source == "base":
        return base_config.initial_program
    if spec.source == "attempt_id":
        if not spec.attempt_id:
            raise ValueError("initial_program.attempt_id required when source=attempt_id")
        attempt_dir = global_archive.get_attempt_dir(spec.attempt_id)
        if attempt_dir is None:
            raise FileNotFoundError(f"global attempt not found: {spec.attempt_id}")
        dest = base_config.config_dir / f".wentian_seed_{spec.attempt_id}.py"
        shutil.copy2(attempt_dir / "code.py", dest)
        return dest
    if spec.source == "path":
        if not spec.path:
            raise ValueError("initial_program.path required when source=path")
        path = Path(spec.path)
        if not path.is_file():
            raise FileNotFoundError(f"initial_program path not found: {path}")
        return path.resolve()
    raise ValueError(f"unknown initial_program source: {spec.source}")


def _collect_seed_attempt_dirs(
    seed: SeedArchiveSpec,
    global_archive: GlobalArchive,
) -> list[Path]:
    if seed.source != "global":
        raise ValueError(f"unsupported seed_archive source: {seed.source}")

    if seed.attempt_ids:
        dirs: list[Path] = []
        for attempt_id in seed.attempt_ids:
            d = global_archive.get_attempt_dir(attempt_id)
            if d is None:
                raise FileNotFoundError(f"global attempt not found for seed: {attempt_id}")
            dirs.append(d)
        return dirs

    if seed.top_n is not None:
        return [a.directory for a in global_archive.top_n_attempts(seed.top_n)]

    return [a.directory for a in global_archive.list_attempts()]


def _copy_attempt_tree(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("code.py", "result.json", "raw-artifact.json", "diagnosis_meta.json", "provenance.json"):
        src_file = src / name
        if src_file.is_file():
            shutil.copy2(src_file, dest / name)


def seed_subtask_archive(
    config: Config,
    *,
    initial_program: Path,
    seed_dirs: list[Path] | None,
    fresh_initial_as_zero: bool,
) -> Archive:
    """Populate sub-task archive with optional seeded history."""
    archive_dir = config.archive_dir
    if archive_dir.exists():
        shutil.rmtree(archive_dir)
    archive_dir.mkdir(parents=True)

    archive = Archive(archive_dir, config.maximize)
    workspace = config.workspace_dir
    evaluator = evaluator_workspace_path(config)
    analyzer = workspace / "analyzer.py" if config.analyzer is not None else None

    if not seed_dirs:
        result = run_evaluation(
            evaluator_path=evaluator,
            program_path=initial_program,
            output_dir=archive_dir / "_seed_eval",
            timeout_seconds=config.evaluation_timeout_seconds,
            maximize=config.maximize,
            analyzer_path=analyzer if analyzer.is_file() else None,
            archive_dir=archive_dir,
            workspace_dir=workspace,
        )
        archive.seed_initial(
            initial_program,
            result,
            store_raw_artifacts=config.store_raw_artifacts,
        )
        return archive

    idx = 0
    if fresh_initial_as_zero:
        result = run_evaluation(
            evaluator_path=evaluator,
            program_path=initial_program,
            output_dir=archive_dir / "_seed_eval",
            timeout_seconds=config.evaluation_timeout_seconds,
            maximize=config.maximize,
            analyzer_path=analyzer if analyzer.is_file() else None,
            archive_dir=archive_dir,
            workspace_dir=workspace,
        )
        attempt_id = f"attempt_{idx:04d}"
        dest = archive_dir / attempt_id
        dest.mkdir(parents=True, exist_ok=False)
        shutil.copy2(initial_program, dest / "code.py")
        payload = finalize_attempt_result(
            dest,
            dict(result),
            store_raw_artifacts=config.store_raw_artifacts,
        )
        with open(dest / "result.json", "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=str)
        idx += 1

    for src in seed_dirs:
        attempt_id = f"attempt_{idx:04d}"
        dest = archive_dir / attempt_id
        _copy_attempt_tree(src, dest)
        idx += 1

    if idx == 0:
        raise RuntimeError("seed_archive produced empty archive")

    return Archive(archive_dir, config.maximize)


def write_subtask_config(
    workflow: WenTianConfig,
    base_config: Config,
    spec: SubtaskSpec,
) -> tuple[Path, Path]:
    """Write derived agentic-evolve config. Returns (config_path, subtask_workspace)."""
    subtask_workspace = workflow.subtasks_root / spec.id
    subtask_workspace.mkdir(parents=True, exist_ok=True)

    base_outputs = base_config.config_dir / "outputs"
    rel_project = os.path.relpath(subtask_workspace, base_outputs).replace("\\", "/")

    max_improvements = workflow.subtasks.defaults.max_improvements
    agent_timeout = spec.agent_timeout_seconds or workflow.subtasks.defaults.agent_timeout_seconds

    with open(workflow.task.base_config, encoding="utf-8") as f:
        raw: dict = yaml.safe_load(f) or {}

    raw["project_name"] = rel_project
    raw["max_improvements"] = max_improvements
    raw["agent_timeout_seconds"] = agent_timeout

    config_path = base_config.config_dir / f".wentian_{workflow.name}_{spec.id}.yaml"
    config_path.write_text(yaml.dump(raw, default_flow_style=False), encoding="utf-8")
    return config_path, subtask_workspace


def prepare_subtask_workspace(
    workflow: WenTianConfig,
    spec: SubtaskSpec,
    global_archive: GlobalArchive,
    *,
    fresh: bool = True,
) -> tuple[Path, str]:
    """Prepare sub-task workspace and return (config_path, prompt_append_text)."""
    base_config = load_config(workflow.task.base_config)
    config_path, _subtask_ws = write_subtask_config(workflow, base_config, spec)

    config = load_config(config_path)
    workspace = config.workspace_dir

    if fresh and workspace.exists():
        archive_dir = config.archive_dir
        if archive_dir.exists():
            shutil.rmtree(archive_dir)
        cp = workspace / "checkpoint.json"
        if cp.is_file():
            cp.unlink()

    workspace.mkdir(parents=True, exist_ok=True)
    _copy_workspace_files(config)
    _link_source_archive(config)
    _write_workspace_meta(config)

    initial_program = _resolve_initial_program_path(
        spec.initial_program,
        base_config=base_config,
        global_archive=global_archive,
    )
    shutil.copy2(initial_program, workspace / "initial_program.py")

    seed_dirs: list[Path] | None = None
    fresh_initial_as_zero = False
    if spec.seed_archive is not None:
        seed_dirs = _collect_seed_attempt_dirs(spec.seed_archive, global_archive)
        fresh_initial_as_zero = spec.initial_program is not None

    if not (workspace / "archive").is_dir() or not Archive(config.archive_dir, config.maximize).list_attempts():
        archive = seed_subtask_archive(
            config,
            initial_program=initial_program,
            seed_dirs=seed_dirs,
            fresh_initial_as_zero=fresh_initial_as_zero,
        )
        write_improvement_baseline(workspace, archive.submission_count())
        baseline = archive.submission_count()
        checkpoint = Checkpoint.from_archive(
            archive,
            project_name=config.project_name,
            maximize=config.maximize,
            max_improvements=config.max_improvements,
            evaluation_timeout_seconds=config.evaluation_timeout_seconds,
            config_path=str(config_path.resolve()),
            status="paused",
            improvement_baseline=baseline,
        )
        save_checkpoint(checkpoint, workspace)
    elif "improvement_baseline_count" not in json.loads(
        (workspace / "workspace_meta.json").read_text(encoding="utf-8")
    ):
        write_improvement_baseline(workspace, read_improvement_baseline(workspace))

    prompt_parts = [spec.prompt_append.strip()]
    if spec.evolve_focus:
        prompt_parts.append(focus_prompt_append(spec.evolve_focus).strip())

    brief = "\n\n".join(p for p in prompt_parts if p)
    if brief:
        (workspace / "subtask_brief.md").write_text(brief + "\n", encoding="utf-8")

    return config_path, brief


def build_subtask_prompt(config_path: Path, brief: str) -> str:
    from agentic_evolve.prompt_builder import build_prompt

    config = load_config(config_path)
    archive = Archive(config.archive_dir, config.maximize)
    workspace = config.workspace_dir
    resumed = archive.submission_count() > 0

    prompt = build_prompt(
        archive,
        workspace,
        config.max_improvements,
        resumed=resumed,
        hidden_testdata=config.hidden_testdata,
        agent_readable_evaluator=config.agent_readable_evaluator,
        prompt_history_top_n=config.prompt_history_top_n,
        prompt_history_recent_n=config.prompt_history_recent_n,
        prompt_history_max_feedback_chars=config.prompt_history_max_feedback_chars,
    )
    if brief:
        prompt += f"\n\n---\n\n## Sub-task directive (from WenTian hub)\n\n{brief}\n"
    return prompt
