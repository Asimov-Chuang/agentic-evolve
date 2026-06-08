# alpha-diagnosis

Automated **diagnostic rule discovery → rule-guided evolution → resume** loop for [agentic-evolve](../README.md).

## Install

```bash
cd agentic-evolve
pip install -e .
pip install -e alpha-diagnosis/
pip install -e ".[example]"
pip install -r examples/diagnostic-rule-discovery/requirements.txt
```

Requires OpenCode CLI configured (`opencode auth login`).

## Run

```bash
alpha-diagnosis run alpha-diagnosis/workflows/sustaindc_rich_feedback.yaml --resume
```

## Plot

```bash
alpha-diagnosis plot --workspace examples/sustaindc/outputs/sustaindc_rich_feedback_5
```

## Layout

- `workflows/` — end-to-end workflow YAML (primary task + stuck + discovery + injection)
- `adapters/` — per-task metadata (trajectory format, prompt template)
- `templates/` — Jinja prompt sections for rule injection

State is persisted under `<primary_workspace>/alpha-diagnosis/state.json`.

Score progress is logged to `<primary_workspace>/score_trajectory.jsonl` (see [agentic-evolve README](../README.md#score-trajectory-score_trajectoryjsonl)). During stuck monitoring, new attempts are synced on each poll so you can `tail -f` the file while OpenCode runs.

When the agent exits early but improvement budget remains, `loop.auto_resume_on_early_exit` (default `true`) starts a new OpenCode session automatically for **primary evolution**, **rule injection**, and **discovery** until stuck, the inject quota, or the budget is exhausted. Look for `auto_resume` events in each workspace's `score_trajectory.jsonl`.

**Stuck detection applies only to primary evolution.** Rule injection is quota-driven (submit one variant per discovered rule); consecutive no-improvement does not stop inject sessions.

## Adding a new task

1. Add `examples/diagnostic-rule-discovery/<task_id>/` (see `_shared/README.md`).
2. Add `alpha-diagnosis/adapters/<task_id>.yaml`.
3. Add `alpha-diagnosis/workflows/<name>.yaml` pointing at primary + discovery task dirs.

Upstream archive must include `raw-artifact.json` per attempt for trajectory-based rules.
