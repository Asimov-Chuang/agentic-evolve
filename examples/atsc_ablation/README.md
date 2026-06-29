# ATSC Ablation

Blind ablation example for adaptive temporal smooth control. The task asks the agent to optimize a deformable-mirror command controller under delayed/noisy slopes, actuator lag, rate limits, and plant mismatch.

## Settings

- `cond_a` maps to `score_only`: the agent receives only the scalar score from the analyzer.
- `cond_b` maps to `feedback_with_meaning`: the agent receives the scalar score plus raw trajectory diagnostics and a prompt explaining what those diagnostics mean.

Both settings use the same hidden evaluator and the same initial program. The output project name is always `ablation_run_N` so the setting is hidden behind the blind output group.

## Files

- `initial_program.py`: valid frame-wise baseline.
- `evaluator_stub.py`: public evaluator bridge used inside agent workspaces.
- `evaluator_core.py`: private evaluator bridge to Frontier-Engineering Optics.
- `analyzer_score_only.py`: private analyzer wrapper for score-only feedback.
- `analyzer_feedback_meaning.py`: private analyzer wrapper for raw-artifact feedback.
- `problem.md`: base task prompt.
- `problem_feedback_meanings.md`: task prompt with raw metric meanings.
- `outputs_layout.py`: mapping from blind groups to internal setting names.

## Dependencies

Set up the Frontier-Engineering Optics environment. The evaluator looks for a Python interpreter with `aotools` in this order:

1. `OPTICS_PYTHON`
2. `GENERAL_MEIO_PYTHON`
3. `Frontier-Engineering/.venvs/frontier-v1-main/bin/python`
4. `Frontier-Engineering/.venvs/frontier-v1-main/Scripts/python.exe`
5. the current Python interpreter
6. `python3` on PATH

If the Frontier-Engineering checkout is not discoverable from the workspace, set `FRONTIER_ENGINEERING_ROOT`.

## Run

Build the blind OpenCode config:

```bash
python3 scripts/build_blind_opencode_config.py
```

Run all replicates:

```bash
bash scripts/run_all_replicates.sh
```

Run one condition from this example directory:

```bash
bash examples/atsc_ablation/scripts/run_score_only_replicates.sh
bash examples/atsc_ablation/scripts/run_feedback_meanings_replicates.sh
```

Control replicate range with `REPLICATE_START` and `REPLICATE_END`.