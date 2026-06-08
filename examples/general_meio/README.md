# general_meio Example (agentic-evolve)

Evolve a hand-crafted MEIO base-stock policy using [Frontier-Engineering](https://github.com/EinsiaLab/Frontier-Engineering) as the simulation backend.

| Config | Workspace | Agent-visible feedback |
|--------|-----------|------------------------|
| [`config.yaml`](config.yaml) (`project_name: general_meio_score_only`) | `outputs/general_meio_score_only/` | Score-only: `feedback: "Score: X.XXXX"` |
| [`config_rich_feedback.yaml`](config_rich_feedback.yaml) (`project_name: general_meio_rich_feedback`) | `outputs/general_meio_rich_feedback/` | Rich: `processed_feedback` with subscores + diagnosis |

## Prerequisites

### 1. Frontier-Engineering setup

From the sibling `Frontier-Engineering` checkout (default: `../Frontier-Engineering` relative to this repo):

```bash
cd ../Frontier-Engineering
bash init.sh
RUN_VALIDATION=0 bash scripts/env/setup_v1_task_envs.sh
```

Verify the runtime can import stockpyl:

```bash
.venvs/frontier-v1-main/bin/python -c "import stockpyl"
```

If that fails, install it in the Frontier venv:

```bash
.venvs/frontier-v1-main/bin/pip install stockpyl
```

Verify `benchmarks/InventoryOptimization/general_meio/verification/evaluate.py` supports `--solution`.

### 2. agentic-evolve

```bash
cd ../agentic-evolve
pip install -e .
```

### 3. OpenCode (for full evolution runs)

Install and authenticate OpenCode: https://opencode.ai/docs/cli/

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `FRONTIER_ENGINEERING_ROOT` | `../../Frontier-Engineering` (from repo layout) | Frontier checkout root |
| `GENERAL_MEIO_PYTHON` | `{FRONTIER_ROOT}/.venvs/frontier-v1-main/bin/python` | Python for stockpyl simulation |

## Smoke test (evaluator only)

```bash
cd agentic-evolve
python examples/general_meio/evaluator.py examples/general_meio/initial_program.py /tmp/general_meio_eval
```

Expect `is_valid: true` and score roughly `0.18`.

## Run evolution

Score-only feedback:

```bash
agentic-evolve run examples/general_meio/config.yaml
```

Rich feedback (analyzer enabled):

```bash
agentic-evolve run examples/general_meio/config_rich_feedback.yaml
```

Resume / fresh:

```bash
agentic-evolve run --resume examples/general_meio/config.yaml
agentic-evolve run --fresh examples/general_meio/config_rich_feedback.yaml
```

Each evaluation takes about 20–25 seconds; `evaluation_timeout_seconds` is set to 120.

### Run both conditions in parallel

The two configs use **different `project_name` values** so they write to separate workspaces:

```bash
# Terminal 1 — score-only
agentic-evolve run examples/general_meio/config.yaml

# Terminal 2 — rich feedback
agentic-evolve run examples/general_meio/config_rich_feedback.yaml
```

## Diagnostic rule discovery + alpha-diagnosis

After rich-feedback evolution accumulates an archive:

```bash
agentic-evolve run --fresh examples/diagnostic-rule-discovery/general_meio/config.yaml
alpha-diagnosis run alpha-diagnosis/workflows/general_meio_rich_feedback.yaml
```

## File layout

```text
examples/general_meio/
  config.yaml
  config_rich_feedback.yaml
  problem.md
  initial_program.py
  evaluator.py
  analyzer.py
  analyzer_rich.py
  outputs/general_meio_score_only/
  outputs/general_meio_rich_feedback/
```

## How feedback flows

1. **evaluator.py** runs Frontier `verification/evaluate.py`, returns:
   - `feedback`: `"Score: X.XXXX"` (always score-only)
   - `construction`: structured evaluation report (omitted from submit stdout)
   - `raw-artifact.json`: per-period simulation trace (only in attempt folder)
2. **analyzer.py** (when enabled) reads `construction` and writes `processed_feedback` without re-running simulation.
3. **prompt_builder** shows `processed_feedback` in archive history when analyzer is on.
