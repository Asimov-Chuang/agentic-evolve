from pathlib import Path
import json
from agentic_evolve.archive import Archive
from alpha_diagnosis.rule_extract import extract_rules

workspace = Path(
    "examples/adaptive_temporal_smooth_control/outputs/optics_temporal_smooth_AD"
)
disc_archive = workspace / (
    "alpha-diagnosis/discovery_configs/cycle_02/outputs/"
    "optics_temporal_smooth_AD_drd_c02_r00/archive"
)
archive = Archive(disc_archive, True)
best = archive.best()
if best is None:
    raise SystemExit("No valid discovery attempts in cycle 02")

rules = extract_rules(best.directory)
out = workspace / "alpha-diagnosis/manual_injection_cycle_02_rules.json"
payload = {
    "project_name": "optics_temporal_smooth_AD_drd_c02_r00",
    "best_attempt_id": best.attempt_id,
    "best_score": best.score,
    "rules": [
        {
            "index": r.index,
            "name": r.name,
            "description": r.description,
            "score_effect": r.score_effect,
        }
        for r in rules
    ],
}
out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
print(f"Wrote {out} ({len(rules)} rules from {best.attempt_id}, score={best.score})")
