# Feedback Noise Ablation

Small agentic-evolve example that demonstrates how **feedback quality** affects evolution efficiency.

The agent optimizes a control sequence to match a hidden reference waveform. When an analyzer is enabled, `processed_feedback` includes diagnostic metrics — some correlated with the true objective, others deterministic noise. The agent is **not told** which metrics are useful.

## Configurations

| Config | `output_group` | Workspace (agent-visible) | Feedback |
|--------|----------------|---------------------------|----------|
| [`config_score_only.yaml`](config_score_only.yaml) | `cond_a` | `cond_a/ablation_run_N` | Scalar score only |
| [`config_0pct_noise.yaml`](config_0pct_noise.yaml) | `cond_b` | `cond_b/ablation_run_N` | 5 signal metrics |
| [`config_50pct_noise.yaml`](config_50pct_noise.yaml) | `cond_c` | `cond_c/ablation_run_N` | 5 signal + 5 noise (50%) |
| [`config_80pct_noise.yaml`](config_80pct_noise.yaml) | `cond_d` | `cond_d/ablation_run_N` | 5 signal + 20 noise (80%) |
| [`config_0pct_metric_meanings.yaml`](config_0pct_metric_meanings.yaml) | `cond_e` | `cond_e/ablation_run_N` | 5 signal metrics + metric meanings disclosed |

Setting labels (`0pct`, `50pct`, …) are **not** in agent workspace paths. Mapping lives in [`outputs_layout.py`](outputs_layout.py) (`BLIND_GROUP_TO_SETTING`).

Expected outcome: **0% noise** converges fastest; **score-only** and **80% noise** are slowest or most unstable.

## Run

From the `agentic-evolve` repo root:

```bash
agentic-evolve run examples/Control_Sequence/config_score_only.yaml
agentic-evolve run examples/Control_Sequence/config_0pct_noise.yaml
agentic-evolve run examples/Control_Sequence/config_50pct_noise.yaml
agentic-evolve run examples/Control_Sequence/config_80pct_noise.yaml
agentic-evolve run examples/Control_Sequence/config_0pct_metric_meanings.yaml
```

Each config uses a distinct `project_name` so runs can execute in parallel.

## Replicate runs (bash)

Scripts under [`scripts/`](scripts/) run replicates with `--fresh`. Workspaces use neutral names; generated configs land in [`.run_configs/`](.run_configs/) as `cond_*_ablation_run_N.yaml`.

Outputs are grouped by blind `output_group` under `.run_configs/outputs/`:

```text
.run_configs/outputs/
  cond_a/ablation_run_1/    # score_only (internal label)
  cond_b/ablation_run_1/    # 0pct
  cond_c/ablation_run_1/    # 50pct
  cond_d/ablation_run_1/    # 80pct
  cond_e/ablation_run_1/    # 0pct_metric_meanings
```

Legacy layouts (`0pct/feedback_ablation_0pct_1/`, flat folders) are still readable by analysis scripts. To rename legacy nested outputs to the blind layout:

```bash
python examples/Control_Sequence/scripts/migrate_to_blind_layout.py --dry-run
python examples/Control_Sequence/scripts/migrate_to_blind_layout.py
```

To move flat replicate folders into legacy setting subfolders first:

```bash
python examples/Control_Sequence/scripts/migrate_outputs_to_setting_dirs.py --dry-run
python examples/Control_Sequence/scripts/migrate_outputs_to_setting_dirs.py
```

From repo root (`agentic-evolve/`):

```bash
bash examples/Control_Sequence/scripts/run_score_only_replicates.sh
bash examples/Control_Sequence/scripts/run_0pct_replicates.sh
bash examples/Control_Sequence/scripts/run_50pct_replicates.sh
bash examples/Control_Sequence/scripts/run_80pct_replicates.sh
bash examples/Control_Sequence/scripts/run_0pct_metric_meanings_replicates.sh

# Or all five conditions sequentially:
bash examples/Control_Sequence/scripts/run_all_replicates.sh
```

Optional env overrides:

```bash
REPLICATE_START=1 REPLICATE_END=3 bash examples/Control_Sequence/scripts/run_0pct_replicates.sh
AUTO_CONTINUE=0 bash examples/Control_Sequence/scripts/run_0pct_replicates.sh
MAX_AUTO_CONTINUES=-1 bash examples/Control_Sequence/scripts/run_0pct_metric_meanings_replicates.sh
```

Replicate scripts enable `agentic-evolve run --auto-continue` by default, so an agent that exits before exhausting `max_improvements` is continued in the same OpenCode session until the budget is used or `MAX_AUTO_CONTINUES` is reached.
### CloudGPT proxy + model selection

Replicate scripts can route OpenCode through the company CloudGPT proxy. Enable with `USE_CLOUDGPT=1` and pick a model via `CLOUDGPT_MODEL` (must match `provider/model` in [`opencode.cloudgpt.json`](../../opencode.cloudgpt.json)):

```bash
# Default codex model
USE_CLOUDGPT=1 bash examples/Control_Sequence/scripts/run_0pct_replicates.sh

# Another proxy model
USE_CLOUDGPT=1 CLOUDGPT_MODEL=cloudgpt-codex/gpt-5.4-20260305 \
  bash examples/Control_Sequence/scripts/run_50pct_replicates.sh

# Chat provider models (non-codex)
USE_CLOUDGPT=1 CLOUDGPT_MODEL=cloudgpt/DeepSeek-V3.2 \
  bash examples/Control_Sequence/scripts/run_score_only_replicates.sh
```

Common `CLOUDGPT_MODEL` values:

| Model slug | Provider |
|------------|----------|
| `cloudgpt-codex/gpt-5.3-codex-20260224` | default codex |
| `cloudgpt-codex/gpt-5.4-20260305` | codex |
| `cloudgpt-codex/gpt-5.4-mini-20260317` | codex mini |
| `cloudgpt/gpt-4o-20241120` | chat |
| `cloudgpt/DeepSeek-V3.2` | chat |
| `cloudgpt/grok-code-fast-1` | chat |

Verify proxy before long runs:

```bash
bash scripts/start-cloudgpt-proxy.sh
curl -fsS http://127.0.0.1:8765/health
opencode models cloudgpt-codex   # after: export OPENCODE_CONFIG=opencode.cloudgpt.json
```

| Script | Workspace pattern |
|--------|-------------------|
| `run_score_only_replicates.sh` | `cond_a/ablation_run_{N}` |
| `run_0pct_replicates.sh` | `cond_b/ablation_run_{N}` |
| `run_50pct_replicates.sh` | `cond_c/ablation_run_{N}` |
| `run_80pct_replicates.sh` | `cond_d/ablation_run_{N}` |
| `run_0pct_metric_meanings_replicates.sh` | `cond_e/ablation_run_{N}` |

## Compare trajectories

After runs complete, compare `best_score` over submissions:

```bash
python examples/Control_Sequence/plot_trajectories.py
```

Or inspect `.run_configs/outputs/<setting>/<project_name>/score_trajectory.jsonl` manually.

## Local smoke test (no agent)

```bash
cd examples/Control_Sequence
python evaluator_core.py initial_program.py
python -c "from evaluator_core import evaluate, compute_signal_metrics, compute_noise_metrics, hidden_target, select_display_metrics; seq=[0.2]*80; t=hidden_target(); s=compute_signal_metrics(seq,t); n=compute_noise_metrics(seq); print('counts:', len(select_display_metrics(s,n,0.0)), len(select_display_metrics(s,n,0.5)), len(select_display_metrics(s,n,0.8)))"
```

Expected metric counts: **5**, **10**, **25**.

## Files

- `problem.md` — task description (no signal/noise hint; strict blind-feedback rules)
- `problem_cond_e.md` — variant that discloses the five 0pct metric meanings to the agent
- `initial_program.py` — weak baseline (constant sequence)
- `evaluator_core.py` — private scoring + metric logic (not copied to workspace)
- `evaluator_stub.py` — workspace-facing evaluator (subprocess delegate only)
- `analyzer_0.py` / `analyzer_50.py` / `analyzer_80.py` — noise-ratio variants
- `plot_trajectories.py` — optional comparison plot

Configs set `agent_readable_evaluator: false` and `hidden_testdata: true` so the framework prompt forbids reading evaluator/analyzer internals; only public submit fields are allowed.

### OpenCode blind permissions (layer 1)

Configs use `opencode_config: opencode.blind_ablation.json` and **do not** pass `--dangerously-skip-permissions`. OpenCode enforces read/edit/bash rules that block `analyzer.py`, `_evaluator.py`, `submit.py`, `workspace_meta.json`, parent-directory access, etc., while allowing `**/problem.md`, `**/candidate.py`, and `**/archive/*/result.json` (glob patterns match absolute paths).

Build or refresh the merged config (CloudGPT providers + permission overlay):

```bash
python examples/Control_Sequence/scripts/build_blind_opencode_config.py
```

Replicate scripts (`scripts/_common.sh`) run this automatically when `USE_BLIND_PERMISSIONS=1` (default). Opt out of permission enforcement (old behavior):

```bash
USE_BLIND_PERMISSIONS=0 bash examples/Control_Sequence/scripts/run_0pct_replicates.sh
```

Edit rules in [`opencode.blind_permissions.json`](opencode.blind_permissions.json); provider/model settings come from [`opencode.cloudgpt.json`](../../opencode.cloudgpt.json).

Signal/noise metric pools are computed inside the private core only; they are **not** written to `result.json`, so reading archive history does not reveal which diagnostics are informative.
