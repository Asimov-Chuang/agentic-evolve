# Circle Packing Problem

Place **26 circles** inside the unit square `[0, 1] × [0, 1]` and **maximize the sum of their radii**.

## Required API

Your program must define:

```python
def construct_packing():
    """
    Return:
        centers: list of [x, y]
        radii: list of float
    """
```

Do not change this function signature or return format.

## Constraints

- All circles must stay inside the unit square
- Circles must not overlap
- All radii must be positive
- Return exactly 26 circles

## How to submit candidates

Write your code to a file (e.g. `candidate.py`), then:

```bash
python submit.py candidate.py
```

This evaluates the program and archives it under `archive/attempt_NNNN/` with:
- `code.py` — your source
- `result.json` — score, validity, feedback, metrics

Read previous attempts in `archive/` before proposing improvements.

## Goal

Improve the packing algorithm to maximize the sum of radii while satisfying all constraints.
Reference target from literature: ~2.635 (AlphaEvolve).
