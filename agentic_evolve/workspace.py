from __future__ import annotations

import json
import shutil
from importlib import resources
from pathlib import Path

from agentic_evolve.archive import Archive
from agentic_evolve.checkpoint import (
    Checkpoint,
    has_resumable_archive,
    restore_named_checkpoint,
    save_checkpoint,
)
from agentic_evolve.config import Config
from agentic_evolve.evaluator import run_evaluation
from agentic_evolve.registry import register_testdata


def evaluator_filename(config: Config) -> str:
    return "evaluator.py" if config.agent_readable_evaluator else "_evaluator.py"


def evaluator_workspace_path(config: Config) -> Path:
    return config.workspace_dir / evaluator_filename(config)


def _eligible_source_attempts(source: Path) -> list[tuple[str, float, Path]]:
    """Attempts with raw-artifact.json and a scored result.json (usable for discovery)."""
    eligible: list[tuple[str, float, Path]] = []
    for attempt_dir in sorted(source.glob("attempt_*")):
        if not attempt_dir.is_dir():
            continue
        raw_path = attempt_dir / "raw-artifact.json"
        result_path = attempt_dir / "result.json"
        if not raw_path.is_file() or not result_path.is_file():
            continue
        with open(result_path, encoding="utf-8") as f:
            result = json.load(f)
        score = result.get("score")
        if score is None:
            continue
        eligible.append((attempt_dir.name, float(score), attempt_dir))
    return eligible


def _top_source_attempt_dirs(source: Path, top_n: int, maximize: bool) -> list[Path]:
    eligible = _eligible_source_attempts(source)
    if not eligible:
        raise ValueError(
            f"No eligible attempts in {source} "
            "(need attempt_*/raw-artifact.json and result.json with score)"
        )
    eligible.sort(key=lambda item: (item[1], item[0]), reverse=maximize)
    return [path for _name, _score, path in eligible[:top_n]]


def _remove_dataset_path(dataset_path: Path) -> None:
    if dataset_path.is_symlink():
        dataset_path.unlink()
    elif dataset_path.is_dir():
        shutil.rmtree(dataset_path)
    elif dataset_path.exists():
        dataset_path.unlink()


def _link_source_archive(config: Config) -> None:
    if config.source_archive is None:
        return
    source = config.source_archive.resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"source_archive is not a directory: {source}")
    dataset_path = config.workspace_dir / "dataset"
    _remove_dataset_path(dataset_path)

    if config.source_archive_top_n is None:
        dataset_path.symlink_to(source, target_is_directory=True)
        return

    dataset_path.mkdir(parents=True, exist_ok=True)
    for attempt_dir in _top_source_attempt_dirs(
        source, config.source_archive_top_n, config.maximize
    ):
        link = dataset_path / attempt_dir.name
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(attempt_dir, target_is_directory=True)


def _write_workspace_meta(config: Config) -> None:
    meta = {
        "project_name": config.project_name,
        "maximize": config.maximize,
        "max_improvements": config.max_improvements,
        "evaluation_timeout_seconds": config.evaluation_timeout_seconds,
        "analyzer_enabled": config.analyzer is not None,
        "hidden_testdata": config.hidden_testdata,
        "agent_readable_evaluator": config.agent_readable_evaluator,
        "evaluator_filename": evaluator_filename(config),
    }
    if config.source_archive is not None:
        meta["source_archive"] = str(config.source_archive.resolve())
        meta["dataset_dir"] = str((config.workspace_dir / "dataset").resolve())
        if config.source_archive_top_n is not None:
            meta["source_archive_top_n"] = config.source_archive_top_n
    if config.rule_set_size is not None:
        meta["rule_set_size"] = config.rule_set_size
    with open(config.workspace_dir / "workspace_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


def _copy_workspace_files(config: Config) -> None:
    workspace = config.workspace_dir
    visible_evaluator = workspace / "evaluator.py"
    hidden_evaluator = workspace / "_evaluator.py"
    shutil.copy2(config.problem, workspace / "problem.md")
    if config.agent_readable_evaluator:
        shutil.copy2(config.evaluator, visible_evaluator)
        hidden_evaluator.unlink(missing_ok=True)
    else:
        shutil.copy2(config.evaluator, hidden_evaluator)
        visible_evaluator.unlink(missing_ok=True)
    if config.analyzer is not None:
        shutil.copy2(config.analyzer, workspace / "analyzer.py")
        analyzer_runner_src = resources.files("agentic_evolve").joinpath("analyzer.py")
        shutil.copy2(analyzer_runner_src, workspace / "_analyzer_runner.py")
    submit_src = resources.files("agentic_evolve").joinpath("submit.py")
    shutil.copy2(submit_src, workspace / "submit.py")
    registry_src = resources.files("agentic_evolve").joinpath("_registry.py")
    shutil.copy2(registry_src, workspace / "_registry.py")

    shared_src = config.evaluator.parent.parent / "_shared"
    if shared_src.is_dir():
        shared_dest = workspace / "_shared"
        if shared_dest.exists():
            shutil.rmtree(shared_dest)
        shutil.copytree(shared_src, shared_dest)


def _seed_archive(config: Config) -> Archive:
    workspace = config.workspace_dir
    archive = Archive(config.archive_dir, config.maximize)
    result = run_evaluation(
        evaluator_path=evaluator_workspace_path(config),
        program_path=config.initial_program,
        output_dir=config.archive_dir / "_seed_eval",
        timeout_seconds=config.evaluation_timeout_seconds,
        maximize=config.maximize,
        analyzer_path=workspace / "analyzer.py" if config.analyzer is not None else None,
        archive_dir=config.archive_dir,
        workspace_dir=workspace,
    )
    archive.seed_initial(config.initial_program, result)
    return archive


def setup_workspace(
    config: Config,
    *,
    fresh: bool = False,
    from_checkpoint: str | None = None,
) -> tuple[Path, Archive, bool]:
    """Prepare workspace. Returns (workspace_path, archive, resumed)."""
    workspace = config.workspace_dir
    workspace.mkdir(parents=True, exist_ok=True)

    if fresh:
        archive_dir = config.archive_dir
        if archive_dir.exists():
            shutil.rmtree(archive_dir)
        cp = workspace / "checkpoint.json"
        if cp.is_file():
            cp.unlink()

    if from_checkpoint:
        restore_named_checkpoint(workspace, from_checkpoint)

    _copy_workspace_files(config)
    _link_source_archive(config)
    _write_workspace_meta(config)
    if config.testdata_dir is not None and config.testdata_dir.is_dir():
        register_testdata(config.project_name, config.testdata_dir)

    archive = Archive(config.archive_dir, config.maximize)
    resumed = has_resumable_archive(config.archive_dir)

    if not resumed:
        archive = _seed_archive(config)
        return workspace, archive, False

    return workspace, archive, True
