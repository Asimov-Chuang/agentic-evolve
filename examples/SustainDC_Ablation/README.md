# SustainDC Feedback Ablation

Blind feedback-design ablation for the SustainDC data-center control task.

The candidate writes a hand-coded policy with:

```python
def decide_actions(observations) -> dict:
    ...
```

The policy controls load shifting, cooling, and battery dispatch across fixed hidden SustainDC scenarios. The scoring objective is to improve carbon and water usage relative to noop while avoiding dropped or overdue tasks.

## Settings

| Config | `output_group` | Internal setting | Feedback |
|--------|----------------|------------------|----------|
| [`config_score_only.yaml`](config_score_only.yaml) | `cond_a` | `score_only` | Score, scenario scores, and at most coarse rich warnings |
| [`config_feedback_meanings.yaml`](config_feedback_meanings.yaml) | `cond_b` | `feedback_with_meaning` | Score, scenario breakdowns, raw-artifact trajectory metrics, and meaning-aware diagnoses |

The `score_only` name is kept for experiment taxonomy, but this condition intentionally includes limited basic rich feedback because SustainDC is a complex simulator. It does not expose raw trajectory metrics, action fractions, CI-binned behavior, SOC diagnostics, or per-scenario trajectory tables.

`feedback_with_meaning` exposes a richer metric panel adapted from the evolved analyzer in `examples/sustaindc/outputs/sustaindc_pro/analyzer.py`.

## Blind Layout

Agent workspaces use neutral condition names:

```text
.run_configs/outputs/
  cond_a/ablation_run_1/    # score_only internally
  cond_b/ablation_run_1/    # feedback_with_meaning internally
```

The mapping is defined in [`outputs_layout.py`](outputs_layout.py).

## Feedback Details

Limited score feedback includes:

- scalar score;
- scenario scores for `az_july`, `ca_april`, `ny_january`, and `tx_august` when available;
- at most two coarse warnings about safety or carbon/water failing to beat noop.

Meaning feedback includes:

- report-derived scenario scores, `carbon_gain`, `water_gain`, and `safety_penalty`;
- global load-shifting, cooling, and battery action fractions;
- state summaries such as average CI, queue fill, oldest age, overdue fraction, workload, temperature, and SOC;
- high/low carbon-intensity conditioned actions;
- high-temperature cooling behavior;
- SOC-conditioned battery behavior;
- per-scenario trajectory summaries;
- diagnosis rules that explain likely policy failures.

The agent sees metric meanings in [`problem_feedback_meanings.md`](problem_feedback_meanings.md). It is still forbidden from reading raw artifact files directly.

## Run

From the `agentic-evolve` repo root:

```bash
python examples/SustainDC_Ablation/scripts/build_blind_opencode_config.py
agentic-evolve run examples/SustainDC_Ablation/config_score_only.yaml
agentic-evolve run examples/SustainDC_Ablation/config_feedback_meanings.yaml
```

## Replicates

```bash
bash examples/SustainDC_Ablation/scripts/run_score_only_replicates.sh
bash examples/SustainDC_Ablation/scripts/run_feedback_meanings_replicates.sh

# Or both settings sequentially:
bash examples/SustainDC_Ablation/scripts/run_all_replicates.sh
```

Optional range override:

```bash
REPLICATE_START=1 REPLICATE_END=3 bash examples/SustainDC_Ablation/scripts/run_feedback_meanings_replicates.sh
```

## Dependencies

This example requires the adjacent `Frontier-Engineering` checkout and SustainDC environment assets. The evaluator locates them via:

- `FRONTIER_ENGINEERING_ROOT`, or nearby `Frontier-Engineering` directory;
- `SUSTAINDC_ROOT`, defaulting under `benchmarks/SustainableDataCenterControl/hand_written_control/sustaindc`;
- `SUSTAINDC_PYTHON`, defaulting to `.venvs/frontier-v1-sustaindc` under Frontier-Engineering.

## Smoke Tests

From repo root:

```bash
python examples/SustainDC_Ablation/scripts/build_blind_opencode_config.py
python examples/SustainDC_Ablation/evaluator_core.py examples/SustainDC_Ablation/initial_program.py examples/SustainDC_Ablation/.smoke_eval
```

If the SustainDC environment is unavailable, the evaluator returns an invalid result describing the missing dependency. Config and syntax checks can still run without the simulator environment.

## Files

- `problem.md` - public task with limited score feedback surface
- `problem_feedback_meanings.md` - public task plus raw-artifact feedback meaning guide
- `initial_program.py` - valid baseline policy
- `evaluator_core.py` - private SustainDC subprocess evaluator and feedback builders
- `evaluator_stub.py` - workspace-facing evaluator stub
- `analyzer_score_limited.py` - limited rich feedback wrapper
- `analyzer_feedback_meaning.py` - raw-artifact meaning feedback wrapper
- `_private_runner.py` / `_analyzer_delegate.py` - private subprocess bridge
- `outputs_layout.py` - blind output group mapping
- `opencode.blind_permissions.json` - blind permission overlay
- `scripts/` - replicate helpers