# Adaptive Fault-Tolerant Fusion Example (agentic-evolve)

Evolve a robust adaptive-optics sensor fusion controller using the Frontier-Engineering Optics benchmark `adaptive_fault_tolerant_fusion`.

| Config | Workspace | Feedback |
|--------|-----------|----------|
| [`config.yaml`](config.yaml) | `outputs/optics_adaptive_fault_tolerant_fusion/` | Score + compact raw-artifact diagnostics |
| [`config_pro.yaml`](config_pro.yaml) | `outputs/optics_adaptive_fault_tolerant_fusion_pro/` | PRO analyzer with per-case raw trace diagnostics |

The evaluator dynamically loads the Frontier benchmark setup, then runs an instrumented copy of the deterministic evaluation loop. Raw artifacts include per-case RMS/Strehl, fault metadata, anomaly-score diagnostics, and command statistics. They are returned as `raw_artifacts` and persisted by agentic-evolve as `archive/attempt_NNNN/raw-artifact.json` when `store_raw_artifacts: true`.

## Prerequisites

```bash
cd ../Frontier-Engineering
bash init.sh
RUN_VALIDATION=0 bash scripts/env/setup_v1_task_envs.sh
python -m pip install -r benchmarks/Optics/requirements.txt

cd ../agentic-evolve
pip install -e .
pip install -e ".[example]"
```

The agentic-evolve evaluator subprocess can run directly if its Python has `aotools`, `scikit-learn`, `matplotlib`, and `numpy`. Otherwise it delegates to an interpreter discovered via the variables below.

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `FRONTIER_ENGINEERING_ROOT` | sibling `Frontier-Engineering` | Frontier checkout root |
| `OPTICS_PYTHON` / `GENERAL_MEIO_PYTHON` | `{FRONTIER}/.venvs/frontier-v1-main/bin/python` | Python with Optics dependencies |

## Smoke Test

```bash
cd agentic-evolve
python examples/optics_adaptive_fault_tolerant_fusion/evaluator.py \
  examples/optics_adaptive_fault_tolerant_fusion/initial_program.py \
  /tmp/aftf_eval
```

Expect `is_valid: true`, a baseline score in `[0, 1]`, and `/tmp/aftf_eval/raw-artifact.json` containing 320 case entries.

## Run Evolution

```bash
agentic-evolve run examples/optics_adaptive_fault_tolerant_fusion/config.yaml
agentic-evolve run --resume examples/optics_adaptive_fault_tolerant_fusion/config.yaml
agentic-evolve run examples/optics_adaptive_fault_tolerant_fusion/config_pro.yaml
agentic-evolve run --resume examples/optics_adaptive_fault_tolerant_fusion/config_pro.yaml
```

For PRO reruns:

```bash
cd examples/optics_adaptive_fault_tolerant_fusion/outputs/optics_adaptive_fault_tolerant_fusion_pro
python rerun_analyzer.py attempt_0001
```
