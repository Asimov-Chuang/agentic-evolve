#!/usr/bin/env python3

"""Run rule injection with an explicit rule list (skip discovery)."""



from __future__ import annotations



import argparse

import json

import shutil

import sys

from pathlib import Path



from agentic_evolve.archive import Archive

from agentic_evolve.config import load_config



from alpha_diagnosis.config_schema import ForkConfig, load_workflow

from alpha_diagnosis.fork import fork_workspace

from alpha_diagnosis.orchestrator import (

    _resolve_primary_config,

    _run_evolution_until_stuck_or_done,

    _tag_injection_attempts,

)

from alpha_diagnosis.prompt_builder import (

    build_rule_guided_prompt,

    injection_quota_target,

    validate_injection_config,

)

from alpha_diagnosis.rule_extract import RuleSpec





def _rules_from_json(path: Path) -> list[RuleSpec]:

    data = json.loads(path.read_text(encoding="utf-8"))

    if "rules" in data:

        items = data["rules"]

    else:

        names = data.get("rule_names") or []

        descs = data.get("rule_descriptions") or []

        items = [

            {"name": names[i], "description": descs[i]}

            for i in range(min(len(names), len(descs)))

        ]

    rules: list[RuleSpec] = []

    for i, item in enumerate(items):

        rules.append(

            RuleSpec(

                index=i,

                name=str(item["name"]),

                description=str(item["description"]),

                score_effect=item.get("score_effect"),

            )

        )

    return rules





def main(argv: list[str] | None = None) -> int:

    parser = argparse.ArgumentParser(description="Run alpha-diagnosis injection only")

    parser.add_argument("workflow", type=Path, help="Workflow YAML path")

    parser.add_argument(

        "--rules-json",

        type=Path,

        required=True,

        help="JSON with rules[] or rule_names/rule_descriptions",

    )

    parser.add_argument(

        "--rules-program",

        type=Path,

        default=None,

        help="Discovery rule-set program (code.py with get_rule_functions). Required for pro mode unless discovery artifact exists in workspace.",

    )

    parser.add_argument("--cycle", type=int, default=1, help="Diagnosis cycle tag for metadata")

    parser.add_argument(

        "--fork-from",

        type=Path,

        default=None,

        help="Fork target workspace from existing primary workspace before injection",

    )

    parser.add_argument(

        "--fork-at-stuck",

        type=int,

        default=None,

        help="Truncate archive at Nth stuck event (1-indexed) in --fork-from workspace",

    )

    parser.add_argument(

        "--fork-at-attempt",

        type=int,

        default=None,

        help="Truncate archive through attempt_NNNN inclusive (e.g. 40 for attempt_0040)",

    )

    parser.add_argument(

        "--save-prompt",

        type=Path,

        default=None,

        help="Write the injection prompt to this path before running OpenCode",

    )

    parser.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args(argv)



    workflow = load_workflow(args.workflow.resolve())

    rules = _rules_from_json(args.rules_json.resolve())

    validate_injection_config(workflow.injection, len(rules))



    primary_cfg_path = _resolve_primary_config(workflow)

    primary_cfg = load_config(primary_cfg_path)



    if args.fork_from is not None:

        if args.fork_at_stuck is not None and args.fork_at_attempt is not None:

            raise SystemExit("Specify only one of --fork-at-stuck or --fork-at-attempt")

        if args.fork_at_stuck is None and args.fork_at_attempt is None:

            raise SystemExit("--fork-from requires --fork-at-stuck or --fork-at-attempt")

        fork_cfg = ForkConfig(

            source_workspace=args.fork_from.resolve(),

            at_stuck_cycle=args.fork_at_stuck,

            at_attempt=args.fork_at_attempt,

            start_at_diagnosis=True,

        )

        if args.verbose:

            print(f"Forking from {fork_cfg.source_workspace} ...", flush=True)

        fork_workspace(fork_cfg, primary_cfg, config_path=str(primary_cfg_path.resolve()))

        src_alpha = fork_cfg.source_workspace / "alpha-diagnosis"

        dst_alpha = primary_cfg.workspace_dir / "alpha-diagnosis"

        if src_alpha.is_dir():

            dst_alpha.mkdir(parents=True, exist_ok=True)

            for name in (

                f"discovery_cycle_{args.cycle:02d}.json",

                "state.json",

            ):

                src_file = src_alpha / name

                if src_file.is_file():

                    shutil.copy2(src_file, dst_alpha / name)



    archive = Archive(primary_cfg.archive_dir, primary_cfg.maximize)

    start_count = archive.submission_count()

    rule_count = len(rules)

    quota_target = injection_quota_target(workflow.injection, rule_count)

    rules_program = args.rules_program.resolve() if args.rules_program else None



    if args.verbose:

        print(f"workspace: {primary_cfg.workspace_dir}", flush=True)

        print(f"injection mode: {workflow.injection.mode}", flush=True)

        print(f"archive attempts: {start_count}", flush=True)

        print(f"quota target: {quota_target} (+ tolerance {workflow.injection.quota_tolerance})", flush=True)

        best = archive.best()

        if best:

            print(f"baseline: {best.attempt_id} score={best.score:.6f}", flush=True)

        for rule in rules:

            print(f"  [{rule.index}] {rule.name}: {rule.description}", flush=True)



    def _injection_prompt() -> str:

        current = Archive(primary_cfg.archive_dir, primary_cfg.maximize)

        return build_rule_guided_prompt(

            workflow,

            current,

            primary_cfg.workspace_dir,

            primary_cfg.max_improvements,

            rules,

            resumed=True,

            agent_readable_evaluator=primary_cfg.agent_readable_evaluator,

            hidden_testdata=primary_cfg.hidden_testdata,

            prompt_history_top_n=primary_cfg.prompt_history_top_n,

            prompt_history_recent_n=primary_cfg.prompt_history_recent_n,

            prompt_history_max_feedback_chars=primary_cfg.prompt_history_max_feedback_chars,

            cycle=args.cycle,

            rule_program_path=rules_program,

        )



    if args.save_prompt:

        prompt_text = _injection_prompt()

        args.save_prompt.parent.mkdir(parents=True, exist_ok=True)

        args.save_prompt.write_text(prompt_text, encoding="utf-8")

        if args.verbose:

            print(f"saved prompt to {args.save_prompt}", flush=True)



    _run_evolution_until_stuck_or_done(

        workflow,

        primary_cfg_path,

        resume=True,

        fresh=False,

        prompt_factory=_injection_prompt,

        verbose=args.verbose,

        injection_start_count=start_count,

        injection_target=quota_target,

    )



    archive = Archive(primary_cfg.archive_dir, primary_cfg.maximize)

    first_idx, last_idx = _tag_injection_attempts(

        primary_cfg.archive_dir,

        start_count,

        args.cycle,

        rule_count,

        mode=workflow.injection.mode,

        tag_limit=quota_target if workflow.injection.mode == "pro" else None,

    )

    best = archive.best()

    if args.verbose:

        print(

            f"injection done: tagged attempts {first_idx}..{last_idx} "

            f"(started from archive count {start_count})",

            flush=True,

        )

        if best:

            print(f"best now: {best.attempt_id} score={best.score:.6f}", flush=True)

    return 0





if __name__ == "__main__":

    raise SystemExit(main())
