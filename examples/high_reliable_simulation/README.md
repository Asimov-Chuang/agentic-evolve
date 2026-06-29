# HighReliableSimulation Example (agentic-evolve)

Evolve a rare-event BER sampler for Hamming-code simulation using [Frontier-Engineering](https://github.com/EinsiaLab/Frontier-Engineering) as the evaluation backend.

| Config | Workspace | Agent-visible feedback |
|--------|-----------|------------------------|
| [`config.yaml`](config.yaml) | `outputs/high_reliable_simulation_score_only/` | Score-only |
| [`config_rich_feedback.yaml`](config_rich_feedback.yaml) | `outputs/high_reliable_simulation_rich_feedback/` | Rich metrics + diagnosis |

[`problem.md`](problem.md) follows Frontier `Task.md` with agentic-evolve submit/archive notes.

The evaluation report is stored in `result.json` under `construction` (hidden from `submit.py` stdout) for analyzers. Repeat-level traces are written to `archive/attempt_NNNN/raw-artifact.json`.

## Prerequisites

### 1. Frontier-Engineering setup

```bash
cd ../Frontier-Engineering
bash init.sh
```

This creates `.venvs/frontier-eval-driver` with `numpy` and `scipy`.

### 2. agentic-evolve

```bash
cd ../agentic-evolve
pip install -e .
pip install -e ".[example]"
```

### 3. OpenCode (for full evolution runs)

Install and authenticate OpenCode: https://opencode.ai/docs/cli/

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `FRONTIER_ENGINEERING_ROOT` | sibling `Frontier-Engineering` | Frontier checkout root |
| `HIGH_RELIABLE_SIM_PYTHON` / `FRONTIER_EVAL_DRIVER_PYTHON` | `{FRONTIER}/.venvs/frontier-eval-driver/bin/python` | Driver Python with numpy/scipy |

## Smoke test (evaluator only)

```bash
cd agentic-evolve
source env.sh
python examples/high_reliable_simulation/evaluator.py \
  examples/high_reliable_simulation/initial_program.py /tmp/hrs_eval
```

Expect `is_valid: true` and `combined_score > 0`.

## Run evolution

```bash
agentic-evolve run examples/high_reliable_simulation/config.yaml
agentic-evolve run examples/high_reliable_simulation/config_rich_feedback.yaml
agentic-evolve run --resume examples/high_reliable_simulation/config_rich_feedback.yaml
```

## Diagnostic rule discovery

After rich-feedback evolution produces an archive with `raw-artifact.json`:

```bash
agentic-evolve run examples/diagnostic-rule-discovery/high_reliable_simulation/config.yaml
```

## Alpha-diagnosis loop

```bash
pip install -e alpha-diagnosis/
alpha-diagnosis run alpha-diagnosis/workflows/high_reliable_simulation_rich_feedback.yaml --resume
alpha-diagnosis plot --workspace examples/high_reliable_simulation/outputs/high_reliable_simulation_X
```
