# PIDTuning Example (agentic-evolve)

Evolve a PID gain optimizer for the Frontier-Engineering **Robotics/PIDTuning** benchmark.

| Config | Workspace | Agent-visible feedback |
|--------|-----------|------------------------|
| [`config.yaml`](config.yaml) | `outputs/pid_tuning_score_only/` | Score-only |
| [`config_rich_feedback.yaml`](config_rich_feedback.yaml) | `outputs/pid_tuning_rich_feedback/` | Rich per-scenario diagnosis |
| [`config_pro.yaml`](config_pro.yaml) | `outputs/pid_tuning_pro/` | PRO: co-evolve analyzer + optimizer from raw-artifact |

The evaluation report is stored in `result.json` under `construction` (hidden from `submit.py` stdout). The same report is written to `archive/attempt_NNNN/raw-artifact.json` (gains, per-scenario ITAE, gain bounds, constraints) for PRO-mode analyzer evolution.

## Prerequisites

### Frontier-Engineering

PIDTuning only needs `numpy`. No extra task assets are required beyond the benchmark tree:

```bash
cd ../Frontier-Engineering
bash init.sh
```

### agentic-evolve

```bash
cd ../agentic-evolve
pip install -e .
```

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `FRONTIER_ENGINEERING_ROOT` | sibling `Frontier-Engineering/` | Frontier checkout root |
| `PID_TUNING_PYTHON` | `FRONTIER_EVAL_DRIVER_PYTHON` or `sys.executable` | Python with numpy |

WSL helper (`env.sh`):

```bash
source env.sh
```

## Smoke test

```bash
python examples/pid_tuning/evaluator.py examples/pid_tuning/initial_program.py /tmp/pid_tuning_eval
```

Expect `is_valid: true` and a positive `combined_score`.

## Run evolution

```bash
agentic-evolve run examples/pid_tuning/config.yaml
agentic-evolve run examples/pid_tuning/config_rich_feedback.yaml
agentic-evolve run examples/pid_tuning/config_pro.yaml
```

## Alpha-diagnosis loop

```bash
alpha-diagnosis run alpha-diagnosis/workflows/pid_tuning_rich_feedback.yaml --resume
alpha-diagnosis run alpha-diagnosis/workflows/pid_tuning_algorithm_rule.yaml --resume
alpha-diagnosis plot --workspace examples/pid_tuning/outputs/pid_tuning_Test
```

## Diagnostic rule discovery (standalone, trajectory)

```bash
agentic-evolve run --fresh examples/diagnostic-rule-discovery/pid_tuning/config.yaml
```

(Requires a populated `source_archive` pointing at a primary evolution archive with `raw-artifact.json` per attempt.)

## Algorithm-based rule discovery (standalone, code)

```bash
agentic-evolve run --fresh examples/algorithm-rule-discovery/pid_tuning/config.yaml
```

(Requires `source_archive` with `code.py` and `result.json` per attempt — no raw-artifact needed.)
