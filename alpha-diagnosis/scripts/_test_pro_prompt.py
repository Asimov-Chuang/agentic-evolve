#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from agentic_evolve.archive import Archive

from alpha_diagnosis.config_schema import load_workflow
from alpha_diagnosis.fork import fork_workspace
from alpha_diagnosis.config_schema import ForkConfig
from alpha_diagnosis.orchestrator import _resolve_primary_config
from alpha_diagnosis.prompt_builder import build_rule_guided_pro_prompt, validate_injection_config
from alpha_diagnosis.rule_extract import RuleSpec
from agentic_evolve.config import load_config

ROOT = Path(__file__).resolve().parents[2]
AD2 = ROOT / "examples/adaptive_temporal_smooth_control/outputs/optics_temporal_smooth_AD2"
WORKFLOW = Path(__file__).resolve().parents[1] / "workflows/optics_temporal_smooth_pro_reinject_c1.yaml"
RULES_JSON = AD2 / "alpha-diagnosis/discovery_cycle_01.json"
RULES_PROGRAM = (
    AD2
    / "alpha-diagnosis/discovery_configs/cycle_01/outputs/optics_temporal_smooth_AD2_drd_c01_r00/archive/attempt_0005/code.py"
)


def main() -> int:
    wf = load_workflow(WORKFLOW)
    rules_data = json.loads(RULES_JSON.read_text(encoding="utf-8"))
    rules = [
        RuleSpec(
            index=r["index"],
            name=r["name"],
            description=r["description"],
            score_effect=r.get("score_effect"),
        )
        for r in rules_data["rules"]
    ]
    validate_injection_config(wf.injection, len(rules))

    cfg_path = _resolve_primary_config(wf)
    cfg = load_config(cfg_path)
    fork_workspace(
        ForkConfig(source_workspace=AD2, at_stuck_cycle=1, start_at_diagnosis=True),
        cfg,
        config_path=str(cfg_path.resolve()),
    )
    archive = Archive(cfg.archive_dir, cfg.maximize)
    prompt = build_rule_guided_pro_prompt(
        wf,
        archive,
        cfg.workspace_dir,
        cfg.max_improvements,
        rules,
        cycle=1,
        rule_program_path=RULES_PROGRAM,
        prompt_history_top_n=10,
        prompt_history_recent_n=10,
    )
    out = cfg.workspace_dir / "injection_pro_prompt_preview.md"
    out.write_text(prompt, encoding="utf-8")
    best = archive.best()
    print(f"forked workspace: {cfg.workspace_dir}")
    print(f"attempts: {archive.submission_count()}")
    print(f"baseline: {best.attempt_id if best else None} score={best.score if best else None}")
    print(f"prompt saved: {out} ({len(prompt)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
