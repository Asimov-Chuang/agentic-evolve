# Algorithm-Based Rule Discovery — Adaptive Temporal Smooth Control

## 1. Task

Discover a **fixed-size set of algorithm classification rules** that predict AO controller scores from per-attempt `code.py` in the primary evolution archive.

Rules inspect **control algorithm structure** in `compute_dm_commands`: temporal smoothing, delta limiting, blend weights, clipping. They must only use the `code: str` argument — no external files.

The evaluator fits linear regression against archive `score` and returns **`score = -MSE`** (`maximize: true`).

---

## 2. Reference dataset (`workspace/dataset/`)

```
dataset/attempt_NNNN/
  result.json     # label: "score"
  code.py         # compute_dm_commands implementation
```

Read a few high/low score `code.py` samples to identify structural differences.

---

## 3. Required program interface

```python
def get_rule_functions() -> list[RuleFn]:
    ...

def get_rule_descriptions() -> list[str]:
    ...
```

- `RuleFn = Callable[[str], tuple[int, str]]`
- `rule_set_size` = 8
- `(1, explanation)` when criterion is met

Helpers: `workspace/_shared/code_rule_utils.py`

---

## 4. Rule design patterns

- temporal smoothing: `smooth_reconstructor`, raw/smooth blend coefficients
- delta limiting: `tanh` on `desired - prev_commands`
- raw weight: coefficient on `raw` vs smoothed path (baseline ~0.075)
- `prev_commands` dependency
- slew aggressiveness: `limit`, `tanh_scale` literals
- missing `np.clip` saturation
- `prev_blend` from `control_model`
- `control_model.get()` optional field access

---

## 5. Workflow

1. Spot-check `dataset/attempt_*/code.py` and `result.json`.
2. Edit candidate in `# EVOLVE-BLOCK`.
3. `python submit.py candidate.py`
