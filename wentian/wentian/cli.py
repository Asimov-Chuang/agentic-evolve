from __future__ import annotations

import argparse
import sys
from pathlib import Path

from wentian.orchestrator import run_workflow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WenTian hub-agent orchestrator for agentic-evolve")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Run WenTian workflow")
    run_p.add_argument("workflow", type=Path, help="Path to workflow YAML")
    run_p.add_argument("--resume", action="store_true", help="Resume from wentian/state.json")
    run_p.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "run":
        return run_workflow(
            args.workflow.resolve(),
            resume=args.resume,
            verbose=args.verbose,
        )

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
