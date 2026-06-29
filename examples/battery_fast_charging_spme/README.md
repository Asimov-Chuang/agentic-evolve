# Battery Fast Charging SPMe Example

This example ports `Frontier-Engineering/benchmarks/EnergyStorage/BatteryFastChargingSPMe` into agentic-evolve. It includes a standard mode config, a pro mode config, a Frontier evaluator bridge, and raw trajectory sidecars for every attempt.

## Modes

- Standard: `config.yaml`
  - Evolves only `build_charging_policy()`.
  - Uses `analyzer.py` for fixed processed feedback.
  - Stores raw artifacts under `outputs/battery_fast_charging_spme/archive/attempt_*/raw-artifact.json`.

- Pro: `config_pro.yaml`
  - Evolves both the candidate and analyzer.
  - Uses `analyzer_pro.py` to extract richer trajectory signals from `raw-artifact.json`.
  - Enables `rerun_analyzer.py` in the generated workspace for analyzer-only iteration.

## Requirements

- Frontier-Engineering checkout available as a sibling of `agentic-evolve`, or set `FRONTIER_ENGINEERING_ROOT` to its root.
- Python with `numpy>=1.24` available for the Frontier battery evaluator.
- CloudGPT proxy for OpenCode model routing when running full evolution.

## Run

From the `agentic-evolve` root:

```bash
agentic-evolve run examples/battery_fast_charging_spme/config.yaml
agentic-evolve run examples/battery_fast_charging_spme/config_pro.yaml
```

Direct evaluator smoke test:

```bash
python examples/battery_fast_charging_spme/evaluator.py examples/battery_fast_charging_spme/initial_program.py examples/battery_fast_charging_spme/_smoke
```

## Raw Artifacts

The original Frontier task writes only aggregate metrics plus a light artifact summary. This example bridge adds `raw-artifact.json` with a compact per-step simulation trajectory so pro mode can analyze where voltage, temperature, and plating constraints become active.
