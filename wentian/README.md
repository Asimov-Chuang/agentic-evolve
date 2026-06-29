# WenTian

WenTian is a **hub-agent orchestration layer** on top of [agentic-evolve](../README.md). A central OpenCode agent dynamically plans exploration sub-tasks; each sub-task runs as an independent agentic-evolve session with its own budget, initial program, seed archive, and prompt directive.

## Architecture

```
Hub agent (OpenCode)
  → reads global archive + sub-task summaries
  → writes plan.json (spawn_subtasks | finish)
  → orchestrator runs up to max_parallel sub-tasks concurrently
  → merges results into global archive
  → repeat until finish or max_rounds
```

## Install

```bash
cd agentic-evolve
pip install -e .
pip install -e wentian/
```

Requires OpenCode CLI configured for your environment.

## Run examples

### SustainDC

```bash
cd agentic-evolve/wentian
wentian run workflows/sustaindc_wentian.yaml -v
wentian run workflows/sustaindc_wentian.yaml --resume
```

### Adaptive temporal smooth control (optics)

```bash
cd agentic-evolve/wentian
wentian run workflows/optics_temporal_smooth_wentian.yaml -v
wentian run workflows/optics_temporal_smooth_wentian.yaml --resume
```

## Configuration

Key knobs in `workflows/*.yaml`:

| Key | Description |
|-----|-------------|
| `subtasks.sequential` | `true`（默认）：subtask 逐个跑；`false` 用线程池排队 |
| `subtasks.max_parallel` | Hub 每轮最多派几个 subtask |
| `subtasks.defaults.max_improvements` | Default improvement budget per sub-task |
| `hub.max_rounds` | Max hub planning cycles |
| `global_archive.top_n` | Attempts kept in global archive |

## OpenCode concurrency

OpenCode uses a shared SQLite database under `~/.local/share/opencode/`. Set `subtasks.sequential: true` (default) to run sub-tasks one after another without a thread pool. Set `sequential: false` only if you want threaded queueing; OpenCode sessions are still serialized via a global lock.

## Output layout

```
wentian/outputs/<project_name>/
  global_archive/          # merged attempts from all sub-tasks
  global_archive_summary.md
  hub/plan.json              # latest hub plan
  subtasks/<id>/             # agentic-evolve workspace per sub-task
  subtasks/<id>/summary.json
  wentian/state.json         # resume state
  wentian/score_trajectory.jsonl  # 整体轨迹（round / hub / subtask / global_best）
  best_program.py              # final solution (on finish)
  final_report.json
```

## Hub plan protocol

Hub writes `hub/plan.json`:

- **spawn_subtasks** — list of sub-tasks with `initial_program`, `seed_archive`, `evolve_focus`, `prompt_append`
- **finish** — `best_ref` pointing to a global archive attempt

See [`templates/hub_prompt.md.j2`](templates/hub_prompt.md.j2) for the full schema exposed to the hub agent.

## Sub-task materials (provided by hub)

Each sub-task receives from the hub:

- **initial_program** — from global best, a specific attempt, base template, or path
- **seed_archive** — optional copy of global top-N or specific attempts
- **prompt_append** + **evolve_focus** — exploration direction within the EVOLVE-BLOCK

## Relationship to alpha-diagnosis

WenTian and alpha-diagnosis are **parallel** orchestration layers:

- **alpha-diagnosis** — single workspace, stuck detection, diagnostic rule discovery
- **WenTian** — multi-workspace divide-and-conquer with a planning hub agent

Sub-tasks use plain agentic-evolve (not alpha-diagnosis) in v1.
