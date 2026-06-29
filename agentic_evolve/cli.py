from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agentic_evolve.archive import Archive, read_improvement_baseline, save_best_program
from agentic_evolve.checkpoint import (
    format_checkpoint_summary,
    has_resumable_archive,
    list_named_checkpoints,
    load_checkpoint,
    save_named_checkpoint,
    save_run_checkpoint,
)
from agentic_evolve.config import load_config
from agentic_evolve.score_trajectory import sync_archive_to_trajectory
from agentic_evolve.session import run_evolution_until_done


def run_evolution(
    config_path: str,
    *,
    verbose: bool | None = None,
    resume: bool = False,
    fresh: bool = False,
    from_checkpoint: str | None = None,
    r2_early_stop_threshold: float | None = None,
    poll_interval_seconds: int = 30,
) -> int:
    config = load_config(config_path)
    if verbose is not None:
        config.verbose = verbose

    if fresh and (resume or from_checkpoint):
        print("error: --fresh cannot be combined with --resume or --from-checkpoint", file=sys.stderr)
        return 1

    archive = Archive(config.archive_dir, config.maximize)
    resumed = has_resumable_archive(config.archive_dir)

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

    baseline = read_improvement_baseline(config.workspace_dir)
    remaining = archive.remaining_improvements(config.max_improvements, baseline=baseline)
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
        save_run_checkpoint(config_path, config, archive, status="completed")
        save_best_program(archive, config.best_program_path, config.initial_program)
        print(f"Saved best program to {config.best_program_path}")
        return 0

    sync_archive_to_trajectory(
        config.workspace_dir,
        config.archive_dir,
        maximize=config.maximize,
        event="backfill",
    )

    evo = run_evolution_until_done(
        config_path,
        resume=resume,
        fresh=fresh,
        from_checkpoint=from_checkpoint,
        verbose=bool(config.verbose),
        auto_resume=config.auto_resume_on_early_exit,
        r2_threshold=r2_early_stop_threshold,
        poll_interval_seconds=poll_interval_seconds,
    )

    archive = evo["archive"]
    config = evo["config"]
    result = evo.get("result")
    if (
        result is not None
        and not result.success
        and result.error
        and result.stopped_reason != "r2_threshold"
    ):
        print(f"agent warning: {result.error}", file=sys.stderr)
    elif result is not None and result.stopped_reason == "r2_threshold" and result.error:
        print(result.error)

    attempts = archive.list_attempts()
    best = archive.best()
    baseline = read_improvement_baseline(config.workspace_dir)
    remaining = archive.remaining_improvements(config.max_improvements, baseline=baseline)
    status = evo["status"]

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

    save_run_checkpoint(config_path, config, archive, status="paused")
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
