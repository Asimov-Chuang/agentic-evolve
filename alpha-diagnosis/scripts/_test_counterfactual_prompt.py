#!/usr/bin/env python3
"""Smoke-test counterfactual injection prompt on an existing mode_detection workspace."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agentic_evolve.archive import Archive

from alpha_diagnosis.config_schema import load_workflow
from alpha_diagnosis.prompt_builder import build_rule_guided_counterfactual_prompt
from alpha_diagnosis.rule_extract import RuleSpec

MODE_DET = (
    ROOT.parent
    / "examples/adaptive_temporal_smooth_control/outputs/optics_temporal_smooth_mode_detection"
)
WORKFLOW = ROOT / "workflows/optics_temporal_smooth_counterfactual.yaml"


def main() -> int:
    if not MODE_DET.is_dir():
        print(f"Missing workspace: {MODE_DET}", file=sys.stderr)
        return 1

    rules_json = MODE_DET / "alpha-diagnosis/discovery_cycle_01.json"
    if not rules_json.is_file():
        print(f"Missing {rules_json}", file=sys.stderr)
        return 1

    data = json.loads(rules_json.read_text(encoding="utf-8"))
    rules = [
        RuleSpec(
            index=r["index"],
            name=r["name"],
            description=r["description"],
            score_effect=r.get("score_effect"),
        )
        for r in data["rules"]
    ]

    meta = json.loads((MODE_DET / "workspace_meta.json").read_text(encoding="utf-8"))
    archive = Archive(MODE_DET / "archive", maximize=bool(meta.get("maximize", True)))
    workflow = load_workflow(WORKFLOW)

    prompt = build_rule_guided_counterfactual_prompt(
        workflow,
        archive,
        MODE_DET,
        int(meta.get("max_improvements", 300)),
        rules,
        cycle=1,
    )
    out = MODE_DET / "_counterfactual_prompt_preview.md"
    out.write_text(prompt, encoding="utf-8")
    print(f"Wrote {out} ({len(prompt)} chars)")
    if "## Counterfactual diagnostic injection" not in prompt:
        print("ERROR: counterfactual section missing", file=sys.stderr)
        return 1
    if "Counterfactual evidence" not in prompt:
        print("ERROR: no counterfactual evidence blocks", file=sys.stderr)
        return 1
    pair_count = prompt.count("**Counterfactual evidence**")
    print(f"counterfactual blocks: {pair_count}")
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
