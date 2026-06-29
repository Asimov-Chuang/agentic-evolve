# EV2Gym Smart Charging Example (agentic-evolve)

Evolve an EV workplace smart-charging policy using [Frontier-Engineering](https://github.com/EinsiaLab/Frontier-Engineering) as the simulation backend.

| Config | Workspace | Agent-visible feedback |
|--------|-----------|------------------------|
| [`config.yaml`](config.yaml) | `outputs/ev2gym_smart_charging_score_only/` | Score-only |
| [`config_rich_feedback.yaml`](config_rich_feedback.yaml) | `outputs/ev2gym_smart_charging_rich_feedback/` | Rich metrics + diagnosis |

[`problem.md`](problem.md) follows Frontier `Task.md` with agentic-evolve submit/archive notes.

The evaluation report is stored in `result.json` under `construction` (hidden from `submit.py` stdout) for analyzers. Per-step trajectories are written to `archive/attempt_NNNN/raw-artifact.json`.

## Prerequisites

### 1. Frontier-Engineering setup (WSL)

```bash
cd /mnt/c/Users/v-shuhazhang/projects/Evaluator-Discovery/Frontier-Engineering
bash init.sh
RUN_VALIDATION=0 bash scripts/env/setup_v1_task_envs.sh
```

This creates the shared `frontier-eval-driver` venv with `ev2gym` and dependencies.

### 2. agentic-evolve

```bash
cd /mnt/c/Users/v-shuhazhang/projects/Evaluator-Discovery/agentic-evolve
pip install -e .
pip install -e ".[example]"
source activate-env.sh
```

### 3. OpenCode (for full evolution runs)

Install and authenticate OpenCode: https://opencode.ai/docs/cli/

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `FRONTIER_ENGINEERING_ROOT` | sibling `Frontier-Engineering` | Frontier checkout root |
| `EV2GYM_PYTHON` | `FRONTIER_EVAL_DRIVER_PYTHON` | Python with `ev2gym` installed |

## Smoke test (evaluator only)

```bash
cd agentic-evolve
source activate-env.sh
python examples/ev2gym_smart_charging/evaluator.py \
  examples/ev2gym_smart_charging/initial_program.py /tmp/ev2gym_eval
```

Expect `is_valid: true` and score ≈ 100.

## Run evolution

```bash
agentic-evolve run examples/ev2gym_smart_charging/config.yaml
agentic-evolve run examples/ev2gym_smart_charging/config_rich_feedback.yaml
agentic-evolve run --resume examples/ev2gym_smart_charging/config_rich_feedback.yaml
```

## Diagnostic rule discovery

After rich-feedback evolution produces an archive with `raw-artifact.json`:

```bash
agentic-evolve run examples/diagnostic-rule-discovery/ev2gym_smart_charging/config.yaml
```

## Alpha-diagnosis loop

```bash
pip install -e alpha-diagnosis/
alpha-diagnosis run alpha-diagnosis/workflows/ev2gym_smart_charging_rich_feedback.yaml --resume
alpha-diagnosis plot --workspace examples/ev2gym_smart_charging/outputs/ev2gym_smart_charging_Test
```
