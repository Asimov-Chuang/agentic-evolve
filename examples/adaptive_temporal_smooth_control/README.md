# Adaptive Temporal Smooth Control Example (agentic-evolve)

Evolve an adaptive-optics temporal smooth controller using [Frontier-Engineering](https://github.com/EinsiaLab/Frontier-Engineering) as the simulation backend.

| Config | Workspace | Agent-visible feedback |
|--------|-----------|------------------------|
| [`config.yaml`](config.yaml) | `outputs/optics_temporal_smooth_score_only/` | Score-only |
| [`config_rich_feedback.yaml`](config_rich_feedback.yaml) | `outputs/optics_temporal_smooth_rich_feedback/` | Rich metrics + diagnosis |
| [`config_pro.yaml`](config_pro.yaml) | `outputs/optics_temporal_smooth_pro/` | PRO: co-evolve analyzer + algorithm from raw-artifact |

[`problem.md`](problem.md) follows Frontier `Task.md` with agentic-evolve submit/archive notes.

The simulation report is stored in `result.json` under `construction` (hidden from `submit.py` stdout) for analyzers. Per-episode trajectories are written to `archive/attempt_NNNN/raw-artifact.json`.

## Prerequisites

### 1. Frontier-Engineering setup

```bash
cd ../Frontier-Engineering
bash init.sh
RUN_VALIDATION=0 bash scripts/env/setup_v1_task_envs.sh
# In frontier-v1-main venv:
python -m pip install -r benchmarks/Optics/requirements.txt
```

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
| `OPTICS_PYTHON` / `GENERAL_MEIO_PYTHON` | `{FRONTIER}/.venvs/frontier-v1-main/bin/python` | Python with `aotools` |

## Smoke test (evaluator only)

```bash
cd agentic-evolve
python examples/adaptive_temporal_smooth_control/evaluator.py \
  examples/adaptive_temporal_smooth_control/initial_program.py /tmp/optics_eval
```

Expect `is_valid: true` and a baseline score in `[0, 1]`.

## Run evolution

```bash
agentic-evolve run examples/adaptive_temporal_smooth_control/config.yaml
agentic-evolve run examples/adaptive_temporal_smooth_control/config_rich_feedback.yaml
agentic-evolve run --resume examples/adaptive_temporal_smooth_control/config_rich_feedback.yaml
agentic-evolve run examples/adaptive_temporal_smooth_control/config_pro.yaml
agentic-evolve run --resume examples/adaptive_temporal_smooth_control/config_pro.yaml
```

PRO mode stores `raw-artifact.json` per attempt and prompts the agent to evolve `analyzer.py` (see [`analyzer_pro.py`](analyzer_pro.py)) alongside the controller each iteration. Test analyzer changes without re-submitting:

```bash
cd outputs/optics_temporal_smooth_pro
python rerun_analyzer.py attempt_0001
```

## Diagnostic rule discovery (trajectory)

After rich-feedback evolution produces an archive with `raw-artifact.json`:

```bash
agentic-evolve run examples/diagnostic-rule-discovery/adaptive_temporal_smooth_control/config.yaml
```

## Algorithm-based rule discovery (code)

Uses optimizer `code.py` only (no raw-artifact):

```bash
agentic-evolve run examples/algorithm-rule-discovery/adaptive_temporal_smooth_control/config.yaml
```

## Alpha-diagnosis loop

```bash
pip install -e alpha-diagnosis/
alpha-diagnosis run alpha-diagnosis/workflows/optics_temporal_smooth_rich_feedback.yaml --resume
alpha-diagnosis run alpha-diagnosis/workflows/optics_temporal_smooth_algorithm_rule.yaml --resume
alpha-diagnosis plot --workspace examples/adaptive_temporal_smooth_control/outputs/optics_temporal_smooth_X
```
