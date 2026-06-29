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


def _eligible_trajectory_attempts(source: Path) -> list[tuple[str, float, Path]]:
    """Attempts with raw-artifact.json and a scored result.json (trajectory discovery)."""
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


def _eligible_code_attempts(source: Path) -> list[tuple[str, float, Path]]:
    """Attempts with code.py and a scored result.json (algorithm-based rule discovery)."""
    eligible: list[tuple[str, float, Path]] = []
    for attempt_dir in sorted(source.glob("attempt_*")):
        if not attempt_dir.is_dir():
            continue
        code_path = attempt_dir / "code.py"
        result_path = attempt_dir / "result.json"
        if not code_path.is_file() or not result_path.is_file():
            continue
        with open(result_path, encoding="utf-8") as f:
            result = json.load(f)
        score = result.get("score")
        if score is None:
            continue
        eligible.append((attempt_dir.name, float(score), attempt_dir))
    return eligible


def _eligible_source_attempts(
    source: Path,
    *,
    sample_type: str = "trajectory",
) -> list[tuple[str, float, Path]]:
    if sample_type == "code":
        return _eligible_code_attempts(source)
    return _eligible_trajectory_attempts(source)


def _top_source_attempt_dirs(
    source: Path,
    top_n: int,
    maximize: bool,
    *,
    sample_type: str = "trajectory",
) -> list[Path]:
    eligible = _eligible_source_attempts(source, sample_type=sample_type)
    if not eligible:
        if sample_type == "code":
            requirement = "attempt_*/code.py and result.json with score"
        else:
            requirement = "attempt_*/raw-artifact.json and result.json with score"
        raise ValueError(f"No eligible attempts in {source} (need {requirement})")
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
    sample_type = config.discovery_sample_type
    for attempt_dir in _top_source_attempt_dirs(
        source, config.source_archive_top_n, config.maximize, sample_type=sample_type
    ):
        link = dataset_path / attempt_dir.name
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(attempt_dir, target_is_directory=True)


def _write_workspace_meta(config: Config) -> None:
    meta = {
        "project_name": config.project_name,
        "maximize": config.maximize,
        "target_score": config.target_score,
        "max_improvements": config.max_improvements,
        "evaluation_timeout_seconds": config.evaluation_timeout_seconds,
        "analyzer_enabled": config.analyzer is not None,
        "analyzer_max_feedback_lines": config.analyzer_max_feedback_lines,
        "hidden_testdata": config.hidden_testdata,
        "agent_readable_evaluator": config.agent_readable_evaluator,
        "evaluator_filename": evaluator_filename(config),
        "mode": config.mode,
    }
    if config.source_archive is not None:
        meta["source_archive"] = str(config.source_archive.resolve())
        meta["dataset_dir"] = str((config.workspace_dir / "dataset").resolve())
        if config.source_archive_top_n is not None:
            meta["source_archive_top_n"] = config.source_archive_top_n
    if config.rule_set_size is not None:
        meta["rule_set_size"] = config.rule_set_size
    meta["discovery_sample_type"] = config.discovery_sample_type
    meta["store_raw_artifacts"] = config.store_raw_artifacts
    if config.mechanism is not None:
        meta["mechanism"] = config.mechanism
    with open(config.workspace_dir / "workspace_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


def _target_score_text(config: Config) -> str:
    if config.target_score is None:
        return ""
    direction = "at least" if config.maximize else "at most"
    comparison = ">=" if config.maximize else "<="
    return (
        "\n\n## Target Score\n\n"
        f"The target score for this run is {direction} {config.target_score:g} "
        f"(score {comparison} {config.target_score:g}). Keep iterating toward this target "
        "while respecting the submission budget. Reaching the target is a success criterion; "
        "if it is not reached yet, use archive feedback to keep searching for improvements.\n"
    )


def _copy_problem_file(config: Config) -> None:
    problem_text = config.problem.read_text(encoding="utf-8")
    (config.workspace_dir / "problem.md").write_text(
        problem_text + _target_score_text(config),
        encoding="utf-8",
    )


def _copy_workspace_files(config: Config, *, seed_analyzer: bool = True) -> None:
    workspace = config.workspace_dir
    visible_evaluator = workspace / "evaluator.py"
    hidden_evaluator = workspace / "_evaluator.py"
    _copy_problem_file(config)
    if config.agent_readable_evaluator:
        shutil.copy2(config.evaluator, visible_evaluator)
        hidden_evaluator.unlink(missing_ok=True)
    else:
        shutil.copy2(config.evaluator, hidden_evaluator)
        visible_evaluator.unlink(missing_ok=True)
    if config.analyzer is not None:
        if seed_analyzer:
            shutil.copy2(config.analyzer, workspace / "analyzer.py")
        analyzer_runner_src = resources.files("agentic_evolve").joinpath("analyzer.py")
        shutil.copy2(analyzer_runner_src, workspace / "_analyzer_runner.py")
    submit_src = resources.files("agentic_evolve").joinpath("submit.py")
    shutil.copy2(submit_src, workspace / "submit.py")
    if config.mode == "pro":
        rerun_src = resources.files("agentic_evolve").joinpath("rerun_analyzer.py")
        shutil.copy2(rerun_src, workspace / "rerun_analyzer.py")
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
        analyzer_max_feedback_lines=config.analyzer_max_feedback_lines,
    )
    archive.seed_initial(
        config.initial_program,
        result,
        store_raw_artifacts=config.store_raw_artifacts,
    )
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
        (workspace / "opencode_session.json").unlink(missing_ok=True)

    if from_checkpoint:
        restore_named_checkpoint(workspace, from_checkpoint)

    seed_analyzer = fresh or not has_resumable_archive(config.archive_dir)
    _copy_workspace_files(config, seed_analyzer=seed_analyzer)
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
