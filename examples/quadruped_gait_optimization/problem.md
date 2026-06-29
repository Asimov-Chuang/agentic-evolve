# Quadruped Gait Optimization

Optimize an open-loop gait for a MuJoCo ant-style quadruped. The candidate program must write `submission.json` in its current working directory. The evaluator maps the eight gait parameters to leg targets and applies joint-space PD control during a fixed-duration rollout.

## Submission Format

Write a JSON object with these keys:

```json
{
  "step_frequency": 1.8,
  "duty_factor": 0.42,
  "step_length": 0.18,
  "step_height": 0.11,
  "phase_FR": 0.5,
  "phase_RL": 0.5,
  "phase_RR": 0.0,
  "lateral_distance": 0.16
}
```

Parameter ranges:

- `step_frequency` in `[0.5, 4.0]`
- `duty_factor` in `[0.30, 0.85]`
- `step_length` in `[0.04, 0.40]`
- `step_height` in `[0.02, 0.15]`
- `phase_FR` in `[0.0, 1.0)`
- `phase_RL` in `[0.0, 1.0)`
- `phase_RR` in `[0.0, 1.0)`
- `lateral_distance` in `[0.08, 0.20]`

## Objective

Maximize average forward speed:

```text
speed = (x_end - x_start) / duration
```

Higher is better.

## Hard Constraints

Any hard violation gives score `0.0`:

- any parameter outside its configured range,
- body roll or pitch exceeds the configured attitude limit,
- actuator force exceeds the configured torque/force limit,
- forward progress is below the configured minimum distance.

## Raw Artifacts

The example evaluator stores `raw-artifact.json` for each attempt. It contains the MuJoCo stepwise rollout: body position, roll/pitch, velocity, controls, actuator forces, leg phases, stance flags, constraint events, and derived stability/progress summaries. Standard mode can inspect these traces; pro mode can evolve `analyzer.py` to extract better diagnostics from them.
