# Causal Signal Denoising

Design a causal denoising filter for hidden noisy time series. The evaluator applies your filter to several hidden signal families and returns a scalar score. **Maximize score** (higher is better).

## Required API

Your program must define:

```python
def denoise_signal(noisy_signal: list[float], window_size: int = 21) -> list[float]:
    """
    Return one denoised value for each input sample.
    """
```

Do not change this function signature or return format.

## Constraints

- Return exactly one finite numeric value per input sample.
- The filter must be **causal**: output at index `i` may use only `noisy_signal[:i + 1]` and fixed internal state, never future samples.
- Avoid external files, network access, and long-running optimization inside `denoise_signal`.
- Keep output numerically stable; very large values are invalid.

## Feedback

Each submission returns:

- `score` - single objective (maximize)
- `feedback` - short summary
- `processed_feedback` - diagnostic metrics (`metric_01`, `metric_02`, ...) when an analyzer is enabled

This setting exposes the true meaning of the five diagnostic metrics. They are all informative metrics computed against hidden clean signals:

- `metric_01`: lag error from the best small temporal shift; lower means less causal delay or phase lag
- `metric_02`: step transition error around abrupt level changes; lower means better edge preservation
- `metric_03`: transient peak error around sparse burst events; lower means better short-event preservation
- `metric_04`: noise suppression error, measured as residual variance relative to input noise variance on non-event regions; lower means more residual noise removed
- `metric_05`: periodic RMSE on smooth sinusoid and chirp-like signals; lower means better tracking of oscillatory signals

Use these metrics and history in `archive/` to guide improvements.

## Strict rules (experiment integrity)

This is a **blind feedback** experiment. Violating these rules invalidates the run:

1. **Use only public feedback fields** from `submit.py` stdout and `archive/attempt_NNNN/result.json`:
   `score`, `is_valid`, `feedback`, `metrics`, `processed_feedback`.
2. **Do NOT read, import, execute, or reverse-engineer** any of the following:
   - `_evaluator.py`, `evaluator.py`, `analyzer.py`
   - `_analyzer_runner.py`, `_registry.py`, `submit.py` (source)
   - `workspace_meta.json`, `checkpoint.json`
   - Any file outside this workspace, including parent directories and the example source tree
3. **Do NOT** run helper scripts to probe hidden signals, metric definitions beyond the meanings listed here, or diagnostic ordering.
4. **Do NOT** infer hidden clean signals by importing evaluation modules; improve only via legitimate submits.
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

Improve `denoise_signal` so it removes noise while preserving causal timing, steps, bursts, and slow drift.