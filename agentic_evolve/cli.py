from __future__ import annotations

import argparse
import sys

from agentic_evolve.archive import Archive, save_best_program
from agentic_evolve.config import load_config
from agentic_evolve.opencode_runner import OpenCodeRunner
from agentic_evolve.prompt_builder import build_prompt
from agentic_evolve.workspace import setup_workspace


def run_evolution(config_path: str, verbose: bool | None = None) -> int:
    config = load_config(config_path)
    if verbose is not None:
        config.verbose = verbose

    workspace = setup_workspace(config)
    archive = Archive(config.archive_dir, config.maximize)

    seed = archive.list_attempts()[0]
    print(
        f"seed score={seed.score:.6f} best={seed.score:.6f} "
        f"attempts=1 budget={config.max_improvements}"
    )

    prompt = build_prompt(archive, workspace, config.max_improvements)
    if config.verbose:
        print(f"\n--- agent trace ---", flush=True)
        print(f"workspace: {workspace}", flush=True)
        print(f"archive attempts: {archive.submission_count()}", flush=True)
        print(f"improvement budget: {config.max_improvements}", flush=True)

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
        help="Stream OpenCode stdout/stderr to the terminal (also saved to agent_*.log)",
    )

    args = parser.parse_args(argv)
    if args.command == "run":
        return run_evolution(args.config, verbose=args.verbose)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
