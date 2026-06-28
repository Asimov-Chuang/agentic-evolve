# Hidden Waveform Matching

Design a control sequence that closely tracks a **hidden reference waveform**. The evaluator compares your output against this reference and returns a scalar score. **Maximize score** (higher is better; score is negative RMSE).

## Required API

Your program must define:

```python
def generate_control_sequence(n: int = 80) -> list[float]:
    """
    Return exactly n control values, each in [-1.0, 1.0].
    """
```

Do not change this function signature or return format.

## Constraints

- Return exactly **80** values (when called with default `n=80`)
- Every value must be in `[-1.0, 1.0]`
- No external files or network access required

## Feedback

Each submission returns:

- `score` - single objective (maximize)
- `feedback` - short summary
- `processed_feedback` - diagnostic metrics (`metric_01`, `metric_02`, ...) when an analyzer is enabled

This setting exposes the true meaning of the five diagnostic metrics. They are all informative metrics computed against the hidden reference waveform:

- `metric_01`: mean signed error over all 80 timesteps (`sequence - target`); values closer to 0 are better
- `metric_02`: RMSE on the middle third of the sequence; lower is better
- `metric_03`: RMSE on the final third of the sequence; lower is better
- `metric_04`: maximum absolute error on the five largest-magnitude target points; lower is better
- `metric_05`: RMSE on the first third of the sequence; lower is better

Use these metrics and history in `archive/` to guide improvements.

## Strict rules (experiment integrity)

This is a **blind feedback** experiment. Violating these rules invalidates the run:

1. **Use only public feedback fields** from `submit.py` stdout and `archive/attempt_NNNN/result.json`:
   `score`, `is_valid`, `feedback`, `metrics`, `processed_feedback`.
2. **Do NOT read, import, execute, or reverse-engineer** any of the following:
   - `_evaluator.py`, `evaluator.py`, `analyzer.py`
   - `_analyzer_runner.py`, `_registry.py`, `submit.py` (source)
   - `workspace_meta.json`, `checkpoint.json`
   - Any file outside this workspace (including parent directories and the example source tree)
3. **Do NOT** run helper scripts to probe the hidden reference waveform, metric definitions, or noise/signal split.
4. **Do NOT** infer the hidden target by importing evaluation modules into Python; improve only via legitimate submits.
5. Allowed reads in `archive/`: `code.py`, and the public fields in `result.json` listed above.

Improve `candidate.py` using submit feedback only.

## How to submit candidates

Write your code to a file (e.g. `candidate.py`), then:

```bash
python submit.py candidate.py
```

This evaluates the program and archives it under `archive/attempt_NNNN/` with:
- `code.py` - your source
- `result.json` - score, validity, feedback, metrics, optional processed feedback

Read previous attempts in `archive/` before proposing improvements.

## Goal

Improve `generate_control_sequence` so the sequence matches the hidden reference as closely as possible (maximize score toward 0).
