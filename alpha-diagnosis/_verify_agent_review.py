"""Quick smoke test for agent_review implementation."""
from pathlib import Path
import json
import tempfile

from alpha_diagnosis.config_schema import load_workflow
from alpha_diagnosis.direction_extract import extract_directions
from alpha_diagnosis.fork import _read_stuck_attempt_count

reg = load_workflow(Path("workflows/sustaindc_rich_feedback.yaml"))
ar = load_workflow(Path("workflows/sustaindc_rich_feedback_agent_review.yaml"))
assert reg.discovery.mode == "regression"
assert reg.discovery.task_dir is not None
assert ar.discovery.mode == "agent_review"
assert ar.discovery.task_dir is None

with tempfile.TemporaryDirectory() as d:
    p = Path(d) / "directions.json"
    p.write_text(
        json.dumps(
            {"directions": [{"name": f"r{i}", "description": f"d{i}"} for i in range(8)]}
        )
    )
    assert len(extract_directions(p, expected_count=8)) == 8

src = Path("../examples/sustaindc/outputs/sustaindc_X")
if src.is_dir():
    assert _read_stuck_attempt_count(src, 1) == 22

print("all checks passed")
