# UAV Inspection Coverage With Wind Example

This example ports `Frontier-Engineering/benchmarks/Robotics/UAVInspectionCoverageWithWind` into agentic-evolve. It includes standard and pro mode configs, a trace-enabled evaluator bridge, and raw stepwise trajectory sidecars for every attempt.

The candidate program writes `submission.json` with one acceleration-control sequence per scene. The evaluator simulates all four Frontier scenes under wind, no-fly zones, dynamic obstacles, speed limits, and acceleration limits.

## Modes

- Standard: `config.yaml`
  - Evolves the UAV control-sequence generator.
  - Uses `analyzer.py` for fixed processed feedback.
  - Stores raw stepwise traces under `outputs/robotics_uav_inspection_coverage_with_wind/archive/attempt_*/raw-artifact.json`.

- Pro: `config_pro.yaml`
  - Evolves both the candidate and analyzer.
  - Uses `analyzer_pro.py` to extract richer trajectory signals from `raw-artifact.json`.
  - Provides diagnosis for low-coverage scenes, near no-fly zones, dynamic-obstacle near misses, and speed/acceleration saturation.

## Requirements

- Frontier-Engineering checkout available as a sibling of `agentic-evolve`, or set `FRONTIER_ENGINEERING_ROOT` to its root.
- Python environment with `numpy` available for the candidate and evaluator.
- CloudGPT proxy for OpenCode model routing when running full evolution.

Optional Python override:

| Variable | Default | Purpose |
|----------|---------|---------|
| `FRONTIER_ENGINEERING_ROOT` | sibling `Frontier-Engineering/` | Frontier checkout root |
| `UAV_INSPECTION_PYTHON` | `FRONTIER_EVAL_DRIVER_PYTHON` or `sys.executable` | Python used to run candidate programs |

## Run

From the `agentic-evolve` root:

```bash
agentic-evolve run examples/robotics_uav_inspection_coverage_with_wind/config.yaml
agentic-evolve run examples/robotics_uav_inspection_coverage_with_wind/config_pro.yaml
```

Direct evaluator smoke test:

```bash
python examples/robotics_uav_inspection_coverage_with_wind/evaluator.py examples/robotics_uav_inspection_coverage_with_wind/initial_program.py examples/robotics_uav_inspection_coverage_with_wind/_smoke
```

Expect `is_valid: true`, four successful scenes, and a positive `combined_score` for the included baseline.

## Scoring

For each scene, an inspection point is covered when the UAV comes within `coverage_radius` of it. The evaluator uses the Frontier task's actual code-level formula:

```text
scene_score = coverage_ratio * 100.0 - energy * 0.5
energy = sum(||u_k||^2 * dt)
```

The final score is the average scene score across all four scenes, but only if every scene succeeds. Any out-of-bounds step, no-fly-zone entry, dynamic-obstacle collision, speed limit violation, acceleration limit violation, or invalid submission makes the attempt invalid in agentic-evolve.

## Raw Artifacts

The original Frontier verification evaluator returns only scene-level summaries. This agentic-evolve bridge replays the same dynamics and writes a full `raw-artifact.json` trace with per-step fields such as:

- time, position, velocity, control, and wind
- speed and acceleration norms
- cumulative energy
- newly covered inspection points and coverage ratio so far
- boundary, no-fly-zone, and dynamic-obstacle clearance
- first failure reason and step, if any

The evaluator also cross-checks the trace replay against Frontier's official `verification/evaluator.py` and stores the official result in `artifacts.json` / `raw-artifact.json`.

## Files

- `initial_program.py`: baseline UAV controller and submission writer.
- `evaluator.py`: candidate runner, official evaluator cross-check, and trace generator.
- `analyzer.py`: standard processed feedback from raw traces.
- `analyzer_pro.py`: richer pro-mode trajectory diagnosis.
- `problem.md`: task contract shown to the agent.