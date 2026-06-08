# Task 02 - General Multi-Echelon Inventory Optimization (MEIO)

## Background
This is a network optimization problem with stochastic demand.

- Graph: 5-node DAG (`10 -> {20,30} -> {40,50}`)
- Decision variable: base-stock level at each node
- Objective: balance cost and service under random demand
- Constraint: avoid unfair service allocation across sinks

## Engineering Scenario
A two-layer distribution network serves two customer-facing markets.

- Nodes 40 and 50 face external demand
- Demand is Poisson and increases in stress scenario (`x1.2`)
- You need one base-stock policy that performs well on cost, service, robustness, and sink balance

## Network topology

| Node | Role | Lead time | Holding cost | Stockout cost |
|------|------|-----------|--------------|---------------|
| 10 | upstream supplier | 1 | 0.2 | 0 |
| 20 | mid-tier | 1 | 0.4 | 0 |
| 30 | mid-tier | 1 | 0.4 | 0 |
| 40 | sink (demand) | 0 | 0.9 | 10 |
| 50 | sink (demand) | 0 | 0.9 | 9 |

Edges: `(10,20), (10,30), (20,40), (30,40), (20,50), (30,50)`

## Demand parameters

| Node | Type | Mean (nominal) | Std (nominal) |
|------|------|----------------|---------------|
| 40 | Poisson | 8.0 | 3.0 |
| 50 | Poisson | 7.0 | 2.5 |

Stress scenario scales demand mean and std by `1.2`.

## Simulation settings

- **nominal**: `demand_scale=1.0`, `periods=160`, `seed=11`
- **stress**: `demand_scale=1.2`, `periods=160`, `seed=17`

## Scoring (0 to 1)
`clip(x) = min(1, max(0, x))`

- `CostScore` (0.30): nominal cost-per-period reduction vs fixed baseline
- `ServiceScore` (0.35): nominal weighted fill-rate target (`0.98 -> 0.995`)
- `RobustnessScore` (0.25): stress cost-per-period reduction vs baseline
- `BalanceScore` (0.10): sink fill-rate fairness (`|fill40-fill50|`)

Final score:

`FinalScore = 0.30*CostScore + 0.35*ServiceScore + 0.25*RobustnessScore + 0.10*BalanceScore`

Fixed baseline policy for scoring reference:

`{10: 30, 20: 18, 30: 18, 40: 20, 50: 20}`

## Your task

Implement `solve()` that returns base-stock levels for all five nodes.

```python
def solve() -> dict[int, int]:
    return {10: ..., 20: ..., 30: ..., 40: ..., 50: ...}
```

Requirements:

- Return integer base-stock levels for nodes `10, 20, 30, 40, 50`
- Do **not** call stockpyl optimizers (`meio_by_enumeration`, etc.)
- Use only the demand statistics and network structure described above
- One policy must perform well on both nominal and stress scenarios

## Heuristic hints

- Sink nodes (40, 50) need enough base-stock to cover Poisson demand variability
- Upstream nodes (10, 20, 30) buffer lead-time demand; under-buffering hurts stress robustness
- Balance score penalizes large gaps between sink fill-rates
- Reference solution (stockpyl enumeration) scores around `0.60`; baseline heuristic scores around `0.18`

## Minimal example

```python
def solve() -> dict[int, int]:
    return {10: 30, 20: 18, 30: 18, 40: 20, 50: 20}
```

This matches the scoring baseline and will score poorly on service and robustness.

## What success looks like

A good submission:

- raises nominal fill-rate toward `0.995` without excessive cost
- maintains service under `demand_scale=1.2`
- keeps sink fill-rates balanced
- reaches scores well above the baseline (`0.18`)

## How to submit candidates

Write your code to **`candidate.py`** in the workspace root (overwrite the same file each iteration), then:

```bash
python submit.py candidate.py
```

Do **not** create `candidate_001.py`, `candidate_002.py`, or other numbered scratch files — archived copies live under `archive/attempt_NNNN/code.py`.

This evaluates the program and archives it under `archive/attempt_NNNN/` with:

- `code.py` — your source
- `result.json` — score, validity, feedback, metrics
- `raw-artifact.json` — simulation trajectories for diagnostic analysis

Read previous attempts in `archive/` before proposing improvements.
