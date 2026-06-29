# Quadruped Gait Optimization Example

This example ports `Frontier-Engineering/benchmarks/Robotics/QuadrupedGaitOptimization` into agentic-evolve. It includes standard and pro configs, a MuJoCo evaluator bridge, and raw stepwise rollout sidecars for every attempt.

## Modes

- Standard: `config.yaml`
  - Evolves the candidate program that writes `submission.json`.
  - Uses `analyzer.py` for fixed processed feedback.
  - Stores raw artifacts under `outputs/quadruped_gait_optimization/archive/attempt_*/raw-artifact.json`.

- Pro: `config_pro.yaml`
  - Evolves both the candidate and analyzer.
  - Uses `analyzer_pro.py` to extract richer signals from MuJoCo step traces.
  - Enables `rerun_analyzer.py` in the generated workspace for analyzer-only iteration.

## Requirements

- Frontier-Engineering checkout available as a sibling of `agentic-evolve`, or set `FRONTIER_ENGINEERING_ROOT` to its root.
- Python with `numpy>=1.24` and `mujoco>=3.1.5`.
- A MuJoCo-compatible runtime. Headless CPU evaluation is sufficient for this task.
- CloudGPT proxy for full OpenCode evolution runs.

## Run

From the `agentic-evolve` root:

```bash
agentic-evolve run examples/quadruped_gait_optimization/config.yaml
agentic-evolve run examples/quadruped_gait_optimization/config_pro.yaml
```

Direct evaluator smoke test:

```bash
python examples/quadruped_gait_optimization/evaluator.py examples/quadruped_gait_optimization/initial_program.py examples/quadruped_gait_optimization/_smoke
```

## Raw Artifacts

The Frontier benchmark reports aggregate speed and feasibility. This example bridge additionally writes `raw-artifact.json` with the internal MuJoCo rollout: per-step body pose, velocity, controls, actuator forces, leg phase/stance signals, events, and derived stability/progress summaries.
