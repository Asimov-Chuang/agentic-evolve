# agentic-evolve

A minimal program evolution framework that uses [OpenCode](https://opencode.ai/) as a coding agent. OpenCode reads the problem, inspects the archive of past attempts, writes new candidates, and submits them for evaluation — all in a **single workspace**.

## Install

```bash
pip install -e .
pip install -e ".[example]"
```

## Prerequisites

1. Install OpenCode: https://opencode.ai/docs/cli/
2. Configure an LLM provider: `opencode auth login`

## Run the example

```bash
agentic-evolve run examples/circle_packing/config.yaml
```

Stream agent output live:

```bash
agentic-evolve run -v examples/circle_packing/config.yaml
```

### SustainDC (Frontier-Engineering backend)

The [`examples/sustaindc/`](examples/sustaindc/) task evolves a SustainDC control policy (`decide_actions`) using Frontier-Engineering's simulator (~20s per evaluation). Set up Frontier first (see [examples/sustaindc/README.md](examples/sustaindc/README.md)), then:

```bash
# Score-only feedback (analyzer commented out in config)
agentic-evolve run examples/sustaindc/config.yaml

# Rich feedback via analyzer.py
agentic-evolve run examples/sustaindc/config_rich_feedback.yaml
```

Toggle feedback by enabling or commenting `analyzer: analyzer.py` in config. The evaluator always returns score-only `feedback`; when the analyzer is on, `processed_feedback` adds scenario breakdowns and diagnosis from the hidden `construction` field.

Both configs use different `project_name` values (`sustaindc_score_only` vs `sustaindc_rich_feedback`) so you can run them in parallel without workspace conflicts.

## Workspace layout

One workspace per run at `outputs/{project_name}/`:

```text
outputs/circle_packing/
  problem.md
  evaluator.py
  analyzer.py            # optional processed-feedback helper
  submit.py              # evaluate + archive helper
  workspace_meta.json
  archive/
    attempt_0000/
      code.py            # seed program
      result.json        # score, is_valid, feedback, metrics, evaluator extras, optional analysis fields
    attempt_0001/
      code.py
      result.json
    ...
  prompt.md
  agent_stdout.log
  agent_stderr.log
  score_trajectory.jsonl   # append-only best-score log (see below)
  best_program.py        # best valid attempt after run
```

There is **no** root `program.py`. All candidates live under `archive/`.

## Score trajectory (`score_trajectory.jsonl`)

Each workspace can maintain an append-only JSONL log of score progress. This is the easiest way to watch **best so far** during a long run without parsing the whole archive.

| `event` | When |
|---------|------|
| `submit` | Each new archive entry (from `submit.py` or poll backfill) |
| `backfill` | Historical attempts synced at session start |
| `session_start` / `session_end` | OpenCode session boundaries |
| `auto_resume` | alpha-diagnosis restarted OpenCode after agent early exit |
| `stuck` | alpha-diagnosis killed a stuck session |
| `discovery_start` / `discovery_end` | Diagnostic rule discovery cycle |

Example row:

```json
{"event": "submit", "attempt_id": "attempt_0098", "score": 30.65, "best_so_far": 30.65, "best_attempt_id": "attempt_0098", "attempt_count": 99, "ts": "2026-06-04T12:34:56+00:00"}
```

Live tail during a run:

```bash
tail -f outputs/my_project/score_trajectory.jsonl
```

Backfill an existing workspace (no new run required):

```bash
python3 -c "
from pathlib import Path
from agentic_evolve.score_trajectory import sync_archive_to_trajectory
ws = Path('outputs/my_project')
sync_archive_to_trajectory(ws, ws / 'archive', maximize=True, event='backfill')
"
```

## Agent workflow

1. Framework seeds `archive/attempt_0000/` from `initial_program.py`.
2. OpenCode runs once in the workspace with an improvement budget (`max_improvements`).
3. Agent reads `archive/*/code.py` and `archive/*/result.json`.
4. Agent writes a new candidate and runs `python submit.py candidate.py`.
5. `submit.py` evaluates via `evaluator.py`, optionally runs `analyzer.py`, and creates the next `archive/attempt_NNNN/`.
6. Repeat until the budget is exhausted or the agent stops.
7. Framework saves `best_program.py` from the best valid archive entry.

## Config format

```yaml
project_name: my_problem
maximize: true

problem: problem.md
initial_program: initial_program.py
evaluator: evaluator.py
analyzer: analyzer.py             # optional

max_improvements: 10          # new submissions after seed
agent_timeout_seconds: 3600   # total OpenCode session timeout
evaluation_timeout_seconds: 60
agent_readable_evaluator: true  # if false, hide evaluator source from the agent
verbose: false

opencode:
  command: opencode
  args:
    - run
    - --dangerously-skip-permissions
```

`iterations` is accepted as an alias for `max_improvements` for backward compatibility.

`agent_readable_evaluator` controls whether the agent can read `evaluator.py` in the workspace. When `false`, the evaluator is stored as a hidden `_evaluator.py` file and the prompt instructs the agent to rely on `problem.md` and submit feedback only.

## Create a new problem

Provide four files: `problem.md`, `initial_program.py`, `evaluator.py`, `config.yaml`.

For evolving diagnostic rules against an existing run archive (linear regression on binary features), see [`examples/diagnostic-rule-discovery/`](examples/diagnostic-rule-discovery/) and config keys `source_archive`, optional `source_archive_top_n`, and `rule_set_size`.

Evaluator interface:

```python
def evaluate(program_path: str, output_dir: str) -> dict:
    return {
        "score": float,
        "is_valid": bool,
        "feedback": str,
        "metrics": dict,
    }
```

Optional analyzer interface:

```python
def analyze(program_path: str, output_dir: str, result: dict, archive_dir: str, workspace_dir: str) -> dict | str:
    return {
        "processed_feedback": "short guidance for the next design step",
        "analysis_metrics": {"some_metric": 1.0},
        "analysis": {"details": "optional structured data"},
    }
```

`analyzer.py` is copied into the workspace and may be edited by the agent. Its output is appended to each new `result.json`; analyzer failures do not change the evaluator score. Existing archives remain readable without these fields.

Evaluators may include extra JSON-serializable fields in their return dict. For example, a packing evaluator can return `construction: {"centers": centers, "radii": radii}` so `analyzer.py` can inspect the exact output that was scored without rerunning `code.py`.

If OpenCode is unavailable, the framework still seeds the archive and exits gracefully.

## Checkpoints

Each run writes `checkpoint.json` in the workspace with progress (attempt count, best score, remaining budget, status).

### Resume from archive

If a previous run was interrupted or paused:

```bash
agentic-evolve run --resume examples/circle_packing/config.yaml
```

This continues from the existing `archive/` without re-seeding. Remaining budget is computed from `max_improvements` minus submissions already in the archive.

### Start fresh

```bash
agentic-evolve run --fresh examples/circle_packing/config.yaml
```

Deletes the existing archive and checkpoint, then seeds from `initial_program.py`.

### Named checkpoint snapshots

Save a snapshot of the current archive:

```bash
agentic-evolve checkpoint save examples/circle_packing/config.yaml before_refactor
```

Inspect status:

```bash
agentic-evolve checkpoint status examples/circle_packing/config.yaml
```

Restore a snapshot and run (implies resume):

```bash
agentic-evolve run --from-checkpoint before_refactor examples/circle_packing/config.yaml
```

Snapshots are stored under `outputs/{project_name}/checkpoints/{name}/`.

To continue after exhausting the budget, increase `max_improvements` in `config.yaml` and run with `--resume`.
