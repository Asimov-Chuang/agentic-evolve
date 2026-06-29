# UAV Inspection Coverage With Wind

Optimize a UAV control program for 3D inspection coverage under wind, no-fly zones, dynamic obstacles, and hard kinematic constraints.

Your program must write `submission.json` in the current working directory. The evaluator will run your program from a sandbox `baseline/` directory containing `../references/scenarios.json`.

## Submission Format

```json
{
  "scenarios": [
    {
      "id": "scene_1",
      "timestamps": [0.0, 0.1, 0.2],
      "controls": [[0.0, 0.0, 0.0], [0.2, -0.1, 0.0], [0.1, 0.0, 0.0]]
    }
  ]
}
```

You must submit entries for all four scenes: `scene_1`, `scene_2`, `scene_3`, and `scene_4`.

For every scene:

- `timestamps` must be one-dimensional, strictly increasing, start at `0.0`, and end at or before the scene `T_max`.
- `controls` must have the same length as `timestamps`.
- each control is a 3D acceleration vector `[ax, ay, az]`.
- acceleration norm must never exceed the scene `a_max`.

If the submitted control horizon ends before `T_max`, the evaluator holds the last control until the simulation ends.

## Dynamics

The evaluator uses fixed step simulation with `dt` from `scenarios.json`:

```text
v_{k+1} = v_k + u_k * dt
p_{k+1} = p_k + (v_{k+1} + w(t_k)) * dt
```

The state is `(x, y, z, vx, vy, vz)`. The control is `(ax, ay, az)`. Wind is scenario-specific and sinusoidal:

```text
w(t) = base + amplitude * sin(frequency * t + phase)
```

## Hard Constraints

Any one of these makes the scene fail:

- out of 3D bounds
- entering an axis-aligned no-fly box
- collision with a dynamic spherical obstacle
- speed norm greater than `v_max`
- acceleration norm greater than `a_max`
- invalid submission schema or missing scene

If any scene fails, the whole attempt is invalid and receives score `0.0` in agentic-evolve.

## Objective

An inspection point is covered when the UAV is within `coverage_radius` of it. The scene score is:

```text
scene_score = coverage_ratio * 100.0 - energy * 0.5
energy = sum(||u_k||^2 * dt)
```

The final score is the average scene score across all four scenes, but only if all scenes succeed.

## Raw Artifact Feedback

The agentic-evolve evaluator records a stepwise trace for every scene in `raw-artifact.json`. The trace includes position, velocity, control, wind, coverage events, cumulative energy, constraint checks, and obstacle clearances. Use analyzer feedback to identify low-coverage scenes, early failures, excessive energy, speed/acceleration saturation, near no-fly zones, and dynamic-obstacle near misses.