# PID Tuning for 2D Quadrotor

## 1. Goal

Tune **12 cascaded PID gains** for a 2D planar quadrotor so it stays stable and tracks waypoints across four flight scenarios.

You will edit `optimize_pid_gains()` in your candidate program. When run as a script, the program must write `submission.json` with the tuned gains.

**Do not modify** `load_config()`, `simulate_quadrotor_2d()`, or `compute_itae()` — the evaluator relies on the same simulation contract as Frontier-Engineering.

## 2. Control structure

State vector:

```text
[x, z, theta, x_dot, z_dot, theta_dot]
```

Three cascaded PID loops:

1. **Altitude PID** → thrust offset
2. **Horizontal PID** → desired pitch angle
3. **Pitch PID** → torque

Filtered derivatives use `N_z`, `N_x`, and `N_theta`.

Physics includes total thrust, torque, first-order motor lag, linear/angular drag, and constant wind.

## 3. Decision variables (12 gains)

| Loop | Gains |
|------|-------|
| Altitude | `Kp_z`, `Ki_z`, `Kd_z`, `N_z` |
| Horizontal | `Kp_x`, `Ki_x`, `Kd_x`, `N_x` |
| Pitch | `Kp_theta`, `Ki_theta`, `Kd_theta`, `N_theta` |

All values must lie within the bounds in `references/pid_config.json` (copied into the evaluation sandbox).

## 4. Scenarios

| Name | Description |
|------|-------------|
| `vertical_hover` | Hover climb from ground to z=5 |
| `lateral_move` | Lateral translation at altitude |
| `combined_wind` | Diagonal move under wind [0.5, 0.2] |
| `multi_waypoint` | Three waypoints, longest duration |

Simulation step `dt = 0.005 s`. Waypoint switch radius `0.5 m`.

## 5. Submission format

Write `submission.json`:

```json
{
  "Kp_z": 8.0,
  "Ki_z": 0.5,
  "Kd_z": 4.0,
  "N_z": 20.0,
  "Kp_x": 0.1,
  "Ki_x": 0.01,
  "Kd_x": 0.1,
  "N_x": 10.0,
  "Kp_theta": 10.0,
  "Ki_theta": 0.5,
  "Kd_theta": 3.0,
  "N_theta": 20.0
}
```

All keys are required and must be numeric.

## 6. Feasibility rules

Score is `0.0` if any of the following hold:

1. Missing required keys or non-numeric gains
2. Gains outside configured bounds
3. Any scenario exceeds max pitch (`|theta| > 1.0472 rad`)
4. Any scenario produces non-positive ITAE

## 7. Scoring

Per scenario:

```text
ITAE = ∫ t * position_error(t) dt
position_error = sqrt(ex² + ez²)
```

Combined score (higher is better):

```text
score = geometric_mean(1 / ITAE_i)
```

## 8. Required program interface

Your candidate must define:

```python
def optimize_pid_gains() -> dict[str, float]:
    ...
```

and, when executed as `python candidate.py`, write `submission.json`.

The seed program also provides `load_config()`, `simulate_quadrotor_2d()`, and `compute_itae()` for local search during optimization.

## 9. Practical advice

- Start from the hand-tuned baseline in the seed program before random search.
- Wind and multi-waypoint scenarios are usually harder than hover/lateral moves.
- Aggressive horizontal gains can violate pitch limits; tune pitch loop jointly.
- Very large `Ki_z` can cause altitude windup under wind disturbance.
- Use `compute_itae()` inside your optimizer to score candidate gain vectors quickly.

## 10. agentic-evolve workflow

1. Edit `candidate.py` (overwrite each iteration).
2. Submit: `python submit.py candidate.py`
3. Read `feedback` / `processed_feedback` from the archived `result.json`.
4. Per-scenario ITAE breakdown is available in rich-feedback mode via `processed_feedback`.

The aggregate evaluation report is stored under `construction` in `result.json` (hidden from submit stdout). Scenario-level traces for rule discovery are written to `archive/attempt_NNNN/raw-artifact.json`.
