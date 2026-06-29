# Causal Filter Feedback Ablation

Small agentic-evolve example for studying how feedback design changes optimization efficiency.

The agent designs a causal denoising filter for hidden noisy time-series families. The evaluator scores filtered outputs against hidden clean signals. When an analyzer is enabled, `processed_feedback` includes diagnostic metrics; the anonymous setting hides their meanings, while the meanings setting discloses them in the prompt.

## Configurations

| Config | `output_group` | Workspace (agent-visible) | Feedback |
|--------|----------------|---------------------------|----------|
| [`config_score_only.yaml`](config_score_only.yaml) | `cond_a` | `cond_a/ablation_run_N` | Scalar score only |
| [`config_0pct_noise.yaml`](config_0pct_noise.yaml) | `cond_b` | `cond_b/ablation_run_N` | 5 informative anonymous metrics |
| [`config_0pct_metric_meanings.yaml`](config_0pct_metric_meanings.yaml) | `cond_c` | `cond_c/ablation_run_N` | 5 informative metrics + metric meanings disclosed |

Setting labels are not in agent workspace paths. Mapping lives in [`outputs_layout.py`](outputs_layout.py) (`BLIND_GROUP_TO_SETTING`).

Expected outcome: anonymous diagnostics should help more than score-only, and disclosed metric meanings should help most when the agent uses metric-specific feedback.

## Task

Candidates implement:

```python
def denoise_signal(noisy_signal: list[float], window_size: int = 21) -> list[float]:
    ...
```

The output must be the same length as the input and causal: output at index `i` may not depend on samples after `i`.

The private evaluator tests hidden smooth, chirp, step, burst, and drift signals with noise and outliers.

## Run

From the `agentic-evolve` repo root:

```bash
agentic-evolve run examples/Causal_Filter_Ablation/config_score_only.yaml
agentic-evolve run examples/Causal_Filter_Ablation/config_0pct_noise.yaml
agentic-evolve run examples/Causal_Filter_Ablation/config_0pct_metric_meanings.yaml
```

Each config uses a neutral `project_name`; workspaces are grouped by blind `output_group`.

## Replicate Runs

Scripts under [`scripts/`](scripts/) run replicates with `--fresh`. Generated configs land in [`.run_configs/`](.run_configs/) as `cond_*_ablation_run_N.yaml`.

Outputs are grouped under `.run_configs/outputs/`:

```text
.run_configs/outputs/
  cond_a/ablation_run_1/    # score_only (internal label)
  cond_b/ablation_run_1/    # 0pct anonymous diagnostics
  cond_c/ablation_run_1/    # 0pct_metric_meanings
```

From repo root:

```bash
bash examples/Causal_Filter_Ablation/scripts/run_score_only_replicates.sh
bash examples/Causal_Filter_Ablation/scripts/run_0pct_replicates.sh
bash examples/Causal_Filter_Ablation/scripts/run_0pct_metric_meanings_replicates.sh

# Or all three conditions sequentially:
bash examples/Causal_Filter_Ablation/scripts/run_all_replicates.sh
```

Optional env overrides:

```bash
REPLICATE_START=1 REPLICATE_END=3 bash examples/Causal_Filter_Ablation/scripts/run_0pct_replicates.sh
```

## Metric Meanings Setting

The anonymous and meanings settings expose the same five informative metrics, relabeled with a fixed deterministic order:

| Display metric | Meaning |
|----------------|---------|
| `metric_01` | lag error from best small temporal shift |
| `metric_02` | step transition error around abrupt level changes |
| `metric_03` | transient peak error around sparse bursts |
| `metric_04` | noise suppression error on non-event regions |
| `metric_05` | periodic RMSE on sinusoid/chirp signals |

All diagnostics are lower-is-better.

## Local Smoke Tests

```bash
cd examples/Causal_Filter_Ablation
python evaluator_core.py initial_program.py
python -c "from evaluator_core import metric_meaning_mapping; print(metric_meaning_mapping())"
python scripts/build_blind_opencode_config.py
```

Validate generated configs from repo root:

```bash
python -c "from pathlib import Path; import yaml; root=Path('examples/Causal_Filter_Ablation'); files=list(root.glob('config_*.yaml'))+list((root/'.run_configs').glob('cond_*_ablation_run_*.yaml')); [yaml.safe_load(p.read_text()) for p in files]; print(len(files))"
```

## Files

- `problem.md` - blind task prompt; metric meanings hidden
- `problem_metric_meanings.md` - prompt variant that discloses metric meanings
- `initial_program.py` - simple causal EMA baseline
- `evaluator_core.py` - private hidden signal generation, scoring, diagnostics
- `evaluator_stub.py` - workspace-facing evaluator stub; delegates privately
- `analyzer_0.py` - 0pct informative diagnostic wrapper
- `_private_runner.py` / `_analyzer_delegate.py` - private subprocess bridge
- `outputs_layout.py` - blind output group mapping and project parsing
- `scripts/` - replicate runner helpers

Configs set `agent_readable_evaluator: false` and `hidden_testdata: true` so the framework prompt forbids reading evaluator/analyzer internals. Blind OpenCode permissions further restrict direct reads of generated evaluator, analyzer, submit, registry, and workspace metadata files.