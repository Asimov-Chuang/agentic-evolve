# EVOLVE-BLOCK-START
"""Diagnostic rules for general_meio using solution ratios and simulation outcomes."""

from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Sequence, Tuple

RawArtifact = Dict
Scenario = Dict
Step = Dict
RuleFn = Callable[[RawArtifact], Tuple[int, str]]

SINK_NODES = ("40", "50")
DEMAND_MEAN = {"40": 8.0, "50": 7.0}


def _solution(raw: RawArtifact) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for key, value in (raw.get("solution_base_stock") or {}).items():
        out[str(key)] = int(value)
    return out


def _scenario(raw: RawArtifact, name: str) -> Scenario | None:
    for block in raw.get("scenarios", []):
        if block.get("scenario") == name:
            return block
    return None


def _aggregate(raw: RawArtifact, name: str) -> Dict:
    block = _scenario(raw, name)
    return dict((block or {}).get("aggregate") or {})


def _iter_steps(raw: RawArtifact, scenario_name: str | None = None) -> Iterable[Step]:
    for block in raw.get("scenarios", []):
        if scenario_name is not None and block.get("scenario") != scenario_name:
            continue
        for step in block.get("steps", []):
            yield step


def _stockout_fraction(raw: RawArtifact, scenario_name: str, sink_id: str) -> float:
    steps = list(_iter_steps(raw, scenario_name))
    if not steps:
        return 0.0
    hits = 0
    for step in steps:
        stockout = (step.get("observations") or {}).get("stockout") or {}
        if float(stockout.get(sink_id, 0.0)) > 0.0:
            hits += 1
    return hits / len(steps)


def _fill_by_sink(aggregate: Dict, sink_id: str) -> float:
    fill_by_sink = aggregate.get("fill_by_sink") or {}
    return float(fill_by_sink.get(sink_id, 0.0))


def rule_low_sink50_ratio(raw: RawArtifact) -> Tuple[int, str]:
    solution = _solution(raw)
    ratio = float(solution.get("50", 0)) / DEMAND_MEAN["50"]
    if ratio < 2.0:
        return 1, f"Sink 50 base-stock / mean demand ratio {ratio:.2f} < 2.0"
    return 0, f"Sink 50 base-stock / mean demand ratio {ratio:.2f} >= 2.0"


def rule_stress_sink50_stockouts(raw: RawArtifact) -> Tuple[int, str]:
    frac = _stockout_fraction(raw, "stress", "50")
    if frac > 0.10:
        return 1, f"Stress scenario sink 50 stockout fraction {frac:.2%} > 10%"
    return 0, f"Stress scenario sink 50 stockout fraction {frac:.2%} <= 10%"


def rule_nominal_balance_gap(raw: RawArtifact) -> Tuple[int, str]:
    aggregate = _aggregate(raw, "nominal")
    fill40 = _fill_by_sink(aggregate, "40")
    fill50 = _fill_by_sink(aggregate, "50")
    gap = abs(fill40 - fill50)
    if gap > 0.05:
        return 1, f"Nominal sink fill gap |40-50| = {gap:.3f} > 0.05"
    return 0, f"Nominal sink fill gap |40-50| = {gap:.3f} <= 0.05"


def rule_upstream_understock(raw: RawArtifact) -> Tuple[int, str]:
    solution = _solution(raw)
    sink_total = DEMAND_MEAN["40"] + DEMAND_MEAN["50"]
    ratio = float(solution.get("10", 0)) / sink_total
    if ratio < 1.5:
        return 1, f"Node 10 base-stock / sink demand total ratio {ratio:.2f} < 1.5"
    return 0, f"Node 10 base-stock / sink demand total ratio {ratio:.2f} >= 1.5"


def rule_stress_fill_degradation(raw: RawArtifact) -> Tuple[int, str]:
    nom = _aggregate(raw, "nominal")
    stress = _aggregate(raw, "stress")
    drop50 = _fill_by_sink(nom, "50") - _fill_by_sink(stress, "50")
    if drop50 > 0.20:
        return 1, f"Sink 50 fill-rate drop under stress {drop50:.2f} > 0.20"
    return 0, f"Sink 50 fill-rate drop under stress {drop50:.2f} <= 0.20"


def rule_low_nominal_service(raw: RawArtifact) -> Tuple[int, str]:
    fill_rate = float(_aggregate(raw, "nominal").get("fill_rate", 0.0))
    if fill_rate < 0.98:
        return 1, f"Nominal weighted fill-rate {fill_rate:.3f} < 0.98"
    return 0, f"Nominal weighted fill-rate {fill_rate:.3f} >= 0.98"


RULE_CATALOG = [
    ("rule_low_sink50_ratio", "Sink 50 base-stock is low relative to mean demand."),
    ("rule_stress_sink50_stockouts", "Stress scenario has frequent sink 50 stockouts."),
    ("rule_nominal_balance_gap", "Nominal sink fill-rates are imbalanced."),
    ("rule_upstream_understock", "Upstream node 10 base-stock is too low."),
    ("rule_stress_fill_degradation", "Sink 50 service collapses under stress."),
    ("rule_low_nominal_service", "Nominal weighted fill-rate misses service target."),
]


def get_rule_functions() -> List[RuleFn]:
    return [
        rule_low_sink50_ratio,
        rule_stress_sink50_stockouts,
        rule_nominal_balance_gap,
        rule_upstream_understock,
        rule_stress_fill_degradation,
        rule_low_nominal_service,
    ]


def get_rule_descriptions() -> List[str]:
    return [entry[1] for entry in RULE_CATALOG]
# EVOLVE-BLOCK-END
