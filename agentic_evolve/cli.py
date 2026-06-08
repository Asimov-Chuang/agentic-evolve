from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agentic_evolve.archive import Archive, save_best_program
from agentic_evolve.checkpoint import (
    Checkpoint,
    format_checkpoint_summary,
    list_named_checkpoints,
    load_checkpoint,
    save_checkpoint,
    save_named_checkpoint,
)
from agentic_evolve.config import load_config
from agentic_evolve.opencode_runner import OpenCodeRunner
from agentic_evolve.prompt_builder import build_prompt
from agentic_evolve.score_trajectory import record_event, sync_archive_to_trajectory
from agentic_evolve.workspace import setup_workspace


def _save_run_checkpoint(
    config_path: str,
    config,
    archive: Archive,
    status: str,
) -> None:
    checkpoint = Checkpoint.from_archive(
        archive,
        project_name=config.project_name,
        maximize=config.maximize,
        max_improvements=config.max_improvements,
        evaluation_timeout_seconds=config.evaluation_timeout_seconds,
        config_path=str(Path(config_path).resolve()),
        status=status,
    )
    save_checkpoint(checkpoint, config.workspace_dir)


def run_evolution(
    config_path: str,
    *,
    verbose: bool | None = None,
    resume: bool = False,
    fresh: bool = False,
    from_checkpoint: str | None = None,
) -> int:
    config = load_config(config_path)
    if verbose is not None:
        config.verbose = verbose

    if fresh and (resume or from_checkpoint):
        print("error: --fresh cannot be combined with --resume or --from-checkpoint", file=sys.stderr)
        return 1

    workspace, archive, resumed = setup_workspace(
        config,
        fresh=fresh,
        from_checkpoint=from_checkpoint,
    )

    if resumed and not resume and not from_checkpoint and not fresh:
        print(
            "error: existing archive/checkpoint found. Use --resume to continue, "
            "or --fresh to restart, or --from-checkpoint NAME to restore a snapshot.",
            file=sys.stderr,
        )
        existing = load_checkpoint(config.workspace_dir)
        if existing:
            print("\n" + format_checkpoint_summary(existing, archive), file=sys.stderr)
        return 1

    remaining = archive.remaining_improvements(config.max_improvements)
    best = archive.best()
    best_score = f"{best.score:.6f}" if best else "N/A"

    mode = "resume" if resumed else "fresh"
    print(
        f"mode={mode} attempts={archive.submission_count()} "
        f"remaining={remaining}/{config.max_improvements} best={best_score}"
    )

    if remaining <= 0:
        print("Improvement budget exhausted. Extend max_improvements in config to continue.")
        sync_archive_to_trajectory(
            config.workspace_dir,
            config.archive_dir,
            maximize=config.maximize,
            event="backfill",
        )
        _save_run_checkpoint(config_path, config, archive, status="completed")
        save_best_program(archive, config.best_program_path, config.initial_program)
        print(f"Saved best program to {config.best_program_path}")
        return 0

    sync_archive_to_trajectory(
        config.workspace_dir,
        config.archive_dir,
        maximize=config.maximize,
        event="backfill",
    )
    best = archive.best()
    record_event(
        config.workspace_dir,
        "session_start",
        mode=mode,
        best_so_far=best.score if best else None,
        best_attempt_id=best.attempt_id if best else None,
        attempt_count=archive.submission_count(),
        remaining=remaining,
    )

    _save_run_checkpoint(config_path, config, archive, status="running")

    prompt = build_prompt(
        archive,
        workspace,
        config.max_improvements,
        resumed=resumed,
        hidden_testdata=config.hidden_testdata,
        agent_readable_evaluator=config.agent_readable_evaluator,
    )
    if config.verbose:
        print("\n--- agent trace ---", flush=True)
        print(f"workspace: {workspace}", flush=True)
        print(f"archive attempts: {archive.submission_count()}", flush=True)
        print(f"remaining improvements: {remaining}", flush=True)

    runner = OpenCodeRunner(
        command=config.opencode.command,
        args=config.opencode.resolved_args(),
        verbose=config.verbose,
    )
    agent_result = runner.run(
        workspace_dir=str(workspace),
        prompt=prompt,
        timeout_seconds=config.agent_timeout_seconds,
    )
    if not agent_result.success and agent_result.error:
        print(f"agent warning: {agent_result.error}", file=sys.stderr)

    archive = Archive(config.archive_dir, config.maximize)
    attempts = archive.list_attempts()
    best = archive.best()
    remaining = archive.remaining_improvements(config.max_improvements)
    status = "completed" if remaining <= 0 else "paused"
    sync_archive_to_trajectory(
        config.workspace_dir,
        config.archive_dir,
        maximize=config.maximize,
    )
    record_event(
        config.workspace_dir,
        "session_end",
        status=status,
        stopped_reason=agent_result.stopped_reason,
        best_so_far=best.score if best else None,
        best_attempt_id=best.attempt_id if best else None,
        attempt_count=archive.submission_count(),
        remaining=remaining,
    )
    _save_run_checkpoint(config_path, config, archive, status=status)

    print(f"\nFinished: {len(attempts)} attempt(s) in archive")
    for attempt in attempts:
        marker = " *best*" if best and attempt.attempt_id == best.attempt_id else ""
        print(
            f"  {attempt.attempt_id} score={attempt.score:.6f} "
            f"valid={attempt.is_valid}{marker}"
        )

    save_best_program(archive, config.best_program_path, config.initial_program)
    print(f"Saved best program to {config.best_program_path}")
    print(f"Archive directory: {config.archive_dir}")
    print(f"Checkpoint: {config.workspace_dir / 'checkpoint.json'} (status={status})")
    if remaining > 0:
        print(f"Resume later with: agentic-evolve run --resume {config_path}")
    return 0


def checkpoint_status(config_path: str) -> int:
    config = load_config(config_path)
    archive = Archive(config.archive_dir, config.maximize)
    checkpoint = load_checkpoint(config.workspace_dir)

    if not archive.list_attempts():
        print("No archive found.")
        return 1

    if checkpoint:
        print(format_checkpoint_summary(checkpoint, archive))
    else:
        print(f"attempts: {archive.submission_count()}")
        best = archive.best()
        if best:
            print(f"best: {best.attempt_id} score={best.score:.6f}")

    named = list_named_checkpoints(config.workspace_dir)
    if named:
        print(f"named checkpoints: {', '.join(named)}")
    return 0


def checkpoint_save(config_path: str, name: str) -> int:
    config = load_config(config_path)
    archive = Archive(config.archive_dir, config.maximize)
    if not archive.list_attempts():
        print("No archive to save.", file=sys.stderr)
        return 1

    _save_run_checkpoint(config_path, config, archive, status="paused")
    dest = save_named_checkpoint(config.workspace_dir, name)
    print(f"Saved checkpoint '{name}' to {dest}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agentic-evolve")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run evolution in a single workspace")
    run_parser.add_argument("config", help="Path to config.yaml")
    run_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Stream OpenCode stdout/stderr to the terminal",
    )
    run_parser.add_argument(
        "--resume",
        action="store_true",
        help="Continue from existing archive/checkpoint in the workspace",
    )
    run_parser.add_argument(
        "--fresh",
        action="store_true",
        help="Delete existing archive and start from initial_program",
    )
    run_parser.add_argument(
        "--from-checkpoint",
        metavar="NAME",
        help="Restore a named checkpoint snapshot before running",
    )

    cp_parser = subparsers.add_parser("checkpoint", help="Inspect or save archive checkpoints")
    cp_sub = cp_parser.add_subparsers(dest="checkpoint_command", required=True)

    cp_status = cp_sub.add_parser("status", help="Show current checkpoint status")
    cp_status.add_argument("config", help="Path to config.yaml")

    cp_save = cp_sub.add_parser("save", help="Save a named snapshot of the archive")
    cp_save.add_argument("config", help="Path to config.yaml")
    cp_save.add_argument("name", help="Checkpoint name")

    args = parser.parse_args(argv)

    if args.command == "run":
        return run_evolution(
            args.config,
            verbose=args.verbose,
            resume=args.resume,
            fresh=args.fresh,
            from_checkpoint=args.from_checkpoint,
        )

    if args.command == "checkpoint":
        if args.checkpoint_command == "status":
            return checkpoint_status(args.config)
        if args.checkpoint_command == "save":
            return checkpoint_save(args.config, args.name)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
