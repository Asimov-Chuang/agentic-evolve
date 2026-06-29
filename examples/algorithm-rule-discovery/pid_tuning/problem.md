# Algorithm-Based Rule Discovery — PID Tuning

## 1. Task

Discover a **fixed-size set of algorithm classification rules** that predict optimizer scores from per-attempt `code.py` sources in the primary evolution archive.

Rules inspect **optimizer source structure**: search strategy, gain literals, control mechanisms (clipping, filtering, multi-phase loops). They must **not** read `result.json`, `raw-artifact.json`, or external files — only the `code: str` argument.

The evaluator fits linear regression against archive `score` and returns **`score = -MSE`** (`maximize: true`).

---

## 2. Reference dataset (`workspace/dataset/`)

Symlinked from `source_archive` in config (read-only).

```
dataset/attempt_NNNN/
  result.json     # label: "score"
  code.py         # optimizer source (input to each rule)
```

- Regression uses attempts with both `code.py` and `result.json`.
- Read a few `dataset/attempt_*/code.py` files to understand high/low score algorithm patterns.
- **Do not** bulk-read all code files in the agent loop; sample selectively.

---

## 3. Required program interface

```python
def get_rule_functions() -> list[RuleFn]:
    ...

def get_rule_descriptions() -> list[str]:
    ...
```

- `RuleFn = Callable[[str], tuple[int, str]]` — receives full `code.py` text.
- `len(get_rule_functions())` must equal `rule_set_size` in config (6).
- Return `(1, explanation)` when the classification criterion is met, `(0, explanation)` otherwise.

Use helpers from `workspace/_shared/code_rule_utils.py` (`has_call`, `parse_assignments`, `extract_evolve_block`, etc.).

---

## 4. Rule design patterns

Useful algorithm criteria for PID tuning:

- integral usage: non-trivial `Ki_*` literals
- horizontal gain shape: low `Kp_x` / `Kd_x`
- altitude integral windup risk: high `Ki_z`
- search structure: multiple optimization loops, perturbation phases
- saturation: `np.clip` on thrust or pitch
- derivative filtering: `N_*` gains or `df_*` state

---

## 5. Workflow

1. Read a few `dataset/attempt_*/result.json` files for score context; spot-check `code.py` for patterns.
2. Edit candidate inside `# EVOLVE-BLOCK`.
3. Submit: `python submit.py candidate.py`
