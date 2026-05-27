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

## Workspace layout

One workspace per run at `outputs/{project_name}/`:

```text
outputs/circle_packing/
  problem.md
  evaluator.py
  submit.py              # evaluate + archive helper
  workspace_meta.json
  archive/
    attempt_0000/
      code.py            # seed program
      result.json        # score, is_valid, feedback, metrics
    attempt_0001/
      code.py
      result.json
    ...
  prompt.md
  agent_stdout.log
  agent_stderr.log
  best_program.py        # best valid attempt after run
```

There is **no** root `program.py`. All candidates live under `archive/`.

## Agent workflow

1. Framework seeds `archive/attempt_0000/` from `initial_program.py`.
2. OpenCode runs once in the workspace with an improvement budget (`max_improvements`).
3. Agent reads `archive/*/code.py` and `archive/*/result.json`.
4. Agent writes a new candidate and runs `python submit.py candidate.py`.
5. `submit.py` evaluates via `evaluator.py` and creates the next `archive/attempt_NNNN/`.
6. Repeat until the budget is exhausted or the agent stops.
7. Framework saves `best_program.py` from the best valid archive entry.

## Config format

```yaml
project_name: my_problem
maximize: true

problem: problem.md
initial_program: initial_program.py
evaluator: evaluator.py

max_improvements: 10          # new submissions after seed
agent_timeout_seconds: 3600   # total OpenCode session timeout
evaluation_timeout_seconds: 60
verbose: false

opencode:
  command: opencode
  args:
    - run
    - --dangerously-skip-permissions
```

`iterations` is accepted as an alias for `max_improvements` for backward compatibility.

## Create a new problem

Provide four files: `problem.md`, `initial_program.py`, `evaluator.py`, `config.yaml`.

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

If OpenCode is unavailable, the framework still seeds the archive and exits gracefully.
