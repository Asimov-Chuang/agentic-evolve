from __future__ import annotations

import argparse
import sys
from pathlib import Path

from alpha_diagnosis.config_schema import load_workflow
from alpha_diagnosis.orchestrator import run_workflow
from alpha_diagnosis.plot import plot_best_so_far


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="alpha-diagnosis orchestrator for agentic-evolve")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Run alpha-diagnosis workflow")
    run_p.add_argument("workflow", type=Path, help="Path to workflow YAML")
    run_p.add_argument("--resume", action="store_true", help="Resume primary evolution workspace")
    run_p.add_argument(
        "--fork-from",
        type=Path,
        default=None,
        help="Fork target workspace from an existing primary workspace (ablation baseline)",
    )
    run_p.add_argument(
        "--fork-at-stuck",
        type=int,
        default=None,
        help="Truncate archive at the Nth stuck event (1-indexed) in --fork-from workspace",
    )
    run_p.add_argument(
        "--fork-at-attempt",
        type=int,
        default=None,
        help="Truncate archive through attempt_NNNN inclusive (e.g. 21 for attempt_0021)",
    )
    run_p.add_argument("-v", "--verbose", action="store_true")

    plot_p = sub.add_parser("plot", help="Plot best-so-far chart with diagnosis markers")
    plot_p.add_argument("--workspace", type=Path, required=True, help="Primary task workspace directory")
    plot_p.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help="Optional discovery dataset dir for purple markers",
    )
    plot_p.add_argument("-o", "--output", type=Path, default=None)

    args = parser.parse_args(argv)

    if args.command == "run":
        return run_workflow(
            args.workflow.resolve(),
            resume=args.resume,
            verbose=args.verbose,
            fork_from=args.fork_from.resolve() if args.fork_from else None,
            fork_at_stuck=args.fork_at_stuck,
            fork_at_attempt=args.fork_at_attempt,
        )

    if args.command == "plot":
        dataset = args.dataset
        if dataset is None:
            state_dir = args.workspace / "alpha-diagnosis"
            if state_dir.is_dir():
                for hist in sorted(state_dir.glob("discovery_cycle_*.json"), reverse=True):
                    import json

                    data = json.loads(hist.read_text(encoding="utf-8"))
                    pname = data.get("project_name")
                    if pname:
                        candidate = (
                            args.workspace.parent.parent.parent
                            / "diagnostic-rule-discovery"
                            / "outputs"
                            / pname
                            / "dataset"
                        )
                        if candidate.is_dir():
                            dataset = candidate
                            break
        plot_best_so_far(args.workspace.resolve(), dataset_dir=dataset, output_path=args.output)
        out = args.output or (args.workspace / "best_so_far_vs_attempts.png")
        print(f"Saved plot to {out}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
