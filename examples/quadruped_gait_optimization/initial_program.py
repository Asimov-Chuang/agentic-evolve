# EVOLVE-BLOCK-START
"""Initial candidate for Quadruped Gait Optimization."""

from __future__ import annotations

import json

submission = {
    "step_frequency": 1.8,
    "duty_factor": 0.42,
    "step_length": 0.18,
    "step_height": 0.11,
    "phase_FR": 0.5,
    "phase_RL": 0.5,
    "phase_RR": 0.0,
    "lateral_distance": 0.16,
}

with open("submission.json", "w", encoding="utf-8") as f:
    json.dump(submission, f, indent=2)

print("Submission written to submission.json")
print(json.dumps(submission, indent=2))
# EVOLVE-BLOCK-END
