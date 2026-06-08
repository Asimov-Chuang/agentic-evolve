# SustainDC Example (agentic-evolve)

Evolve a hand-written SustainDC control policy using [Frontier-Engineering](https://github.com/EinsiaLab/Frontier-Engineering) as the simulation backend.

This example uses agentic-evolve's **analyzer toggle** to switch feedback modes without changing the scoring function:

| Config | Workspace | Agent-visible feedback |
|--------|-----------|------------------------|
| [`config.yaml`](config.yaml) (`project_name: sustaindc_score_only`) | `outputs/sustaindc_score_only/` | Score-only: `feedback: "Score: X.XXXX"` |
| [`config_rich_feedback.yaml`](config_rich_feedback.yaml) (`project_name: sustaindc_rich_feedback`) | `outputs/sustaindc_rich_feedback/` | Rich: `processed_feedback` with scenario scores + diagnosis |

[`problem.md`](problem.md) sections 1–15 match Frontier-Engineering `hand_written_control/Task.md` verbatim; section 16 adds agentic-evolve submit/archive notes.

The aggregate simulation report is stored in `result.json` under `construction` (hidden from `submit.py` stdout) for `analyzer.py` to consume. Per-step trajectories are written only to `archive/attempt_NNNN/raw-artifact.json` (not in `result.json` or other JSON sidecars).

## Prerequisites

### 1. Frontier-Engineering setup

From the sibling `Frontier-Engineering` checkout (default: `../Frontier-Engineering` relative to this repo):

```bash
cd ../Frontier-Engineering
bash init.sh
RUN_VALIDATION=0 bash scripts/env/setup_v1_task_envs.sh
python scripts/bootstrap/fetch_task_assets.py --target sustaindc
```

Verify `benchmarks/SustainableDataCenterControl/hand_written_control/sustaindc/sustaindc_env.py` exists.

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
| `SUSTAINDC_PYTHON` | `{FRONTIER_ROOT}/.venvs/frontier-v1-sustaindc/bin/python` | Python for simulation |
| `SUSTAINDC_ROOT` | `{FRONTIER_ROOT}/benchmarks/.../hand_written_control/sustaindc` | dc-rl checkout |

## Smoke test (evaluator only)

```bash
cd agentic-evolve
python examples/sustaindc/evaluator.py examples/sustaindc/initial_program.py /tmp/sustaindc_eval
```

Expect `is_valid: true` and score roughly 8–9.

## Run evolution

Score-only feedback:

```bash
agentic-evolve run examples/sustaindc/config.yaml
```

Rich feedback (analyzer enabled):

```bash
agentic-evolve run examples/sustaindc/config_rich_feedback.yaml
```

Resume / fresh:

```bash
agentic-evolve run --resume examples/sustaindc/config.yaml
agentic-evolve run --fresh examples/sustaindc/config_rich_feedback.yaml
```

Each evaluation takes about 20 seconds; `evaluation_timeout_seconds` is set to 300.

### Run both conditions in parallel

The two configs use **different `project_name` values** so they write to separate workspaces and do not overwrite each other's `archive/` or `checkpoint.json`:

```bash
# Terminal 1 — score-only
agentic-evolve run examples/sustaindc/config.yaml

# Terminal 2 — rich feedback
agentic-evolve run examples/sustaindc/config_rich_feedback.yaml
```

Frontier simulation subprocesses are independent; the only shared resource is the read-only `sustaindc/` tree under Frontier-Engineering (safe to read concurrently).

## File layout

```text
examples/sustaindc/
  config.yaml                 # score-only (default)
  config_rich_feedback.yaml   # rich feedback via analyzer
  problem.md                  # Task.md-aligned problem statement (sections 1–15)
  initial_program.py          # seed policy (decide_actions)
  evaluator.py                # subprocess bridge to Frontier evaluate.py
  analyzer.py                 # rich processed_feedback from construction
  feedback_utils.py           # diagnosis / breakdown helpers
  outputs/sustaindc_score_only/       # score-only workspace
  outputs/sustaindc_rich_feedback/    # rich-feedback workspace
```

## How feedback flows

1. **evaluator.py** runs Frontier `verification/evaluate.py`, returns:
   - `feedback`: `"Score: X.XXXX"` (always score-only)
   - `construction`: aggregate `last_eval.json` report (omitted from submit stdout)
   - `raw-artifact.json`: per-step observations/actions/rewards/common trace (large; only in attempt folder)
2. **analyzer.py** (when enabled) reads `construction` and writes `processed_feedback` without re-running simulation.
3. **prompt_builder** shows `processed_feedback` in archive history when analyzer is on.

This mirrors the Frontier feedback ablation (score-only vs rich) while keeping prompt assembly clean inside agentic-evolve.
