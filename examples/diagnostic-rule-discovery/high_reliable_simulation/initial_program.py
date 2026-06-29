# EVOLVE-BLOCK-START
"""Diagnostic rules for HighReliableSimulation using repeat-level evaluation traces."""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Tuple

RawArtifact = Dict
RuleFn = Callable[[RawArtifact], Tuple[int, str]]


def _dev(raw: RawArtifact) -> Dict:
    return dict(raw.get("dev_constants") or {})


def _aggregate(raw: RawArtifact) -> Dict:
    return dict(raw.get("aggregate") or {})


def _repeats(raw: RawArtifact) -> List[Dict]:
    return list(raw.get("repeats") or [])


def rule_invalid_submission(raw: RawArtifact) -> Tuple[int, str]:
    valid = float(_aggregate(raw).get("valid", 0.0))
    if valid <= 0.0:
        return 1, "aggregate.valid=0 (submission invalid under frozen scoring rules)"
    return 0, "aggregate.valid=1"


def rule_std_exceeds_target(raw: RawArtifact) -> Tuple[int, str]:
    target_std = float(_dev(raw).get("target_std", 0.05))
    repeats = _repeats(raw)
    offenders = [block for block in repeats if float(block.get("actual_std", 0.0)) > target_std]
    if offenders:
        worst = max(float(block.get("actual_std", 0.0)) for block in offenders)
        return 1, f"{len(offenders)} repeat(s) exceed target_std={target_std:.3f}; worst={worst:.4f}"
    return 0, f"All repeats satisfy target_std={target_std:.3f}"


def rule_high_error_log_ratio(raw: RawArtifact) -> Tuple[int, str]:
    epsilon = float(_dev(raw).get("epsilon", 0.8))
    ratio = float(_aggregate(raw).get("error_log_ratio", float("inf")))
    if ratio >= epsilon:
        return 1, f"error_log_ratio={ratio:.4f} >= epsilon={epsilon:.4f}"
    return 0, f"error_log_ratio={ratio:.4f} < epsilon={epsilon:.4f}"


def rule_low_converged_rate(raw: RawArtifact) -> Tuple[int, str]:
    rate = float(_aggregate(raw).get("converged_rate", 0.0))
    if rate < 1.0:
        return 1, f"converged_rate={rate:.2f} < 1.0"
    return 0, f"converged_rate={rate:.2f}"


def rule_slow_runtime(raw: RawArtifact) -> Tuple[int, str]:
    aggregate = _aggregate(raw)
    if float(aggregate.get("valid", 0.0)) <= 0.0:
        return 0, "Skipped slow-runtime rule because submission is invalid"
    median_runtime = float(aggregate.get("runtime_s", 0.0))
    slow = [
        block
        for block in _repeats(raw)
        if float(block.get("runtime_s", 0.0)) > median_runtime * 1.5
    ]
    if slow:
        return 1, f"{len(slow)} repeat(s) exceed 1.5x median runtime={median_runtime:.3f}s"
    return 0, f"Repeat runtimes are within 1.5x median runtime={median_runtime:.3f}s"


def rule_ber_log_drift(raw: RawArtifact) -> Tuple[int, str]:
    dev = _dev(raw)
    r0 = float(dev.get("r0_dev", 7.261287772505011e-07))
    r0_log = math.log(r0)
    median_log = float(_aggregate(raw).get("err_rate_log_median", 0.0))
    drift = abs(median_log - r0_log)
    epsilon = float(dev.get("epsilon", 0.8))
    if drift >= epsilon * 0.5:
        return 1, f"|err_rate_log_median - log(r0)| = {drift:.4f} is large"
    return 0, f"|err_rate_log_median - log(r0)| = {drift:.4f} is moderate"


RULE_CATALOG = [
    ("rule_invalid_submission", "Submission fails frozen validity checks."),
    ("rule_std_exceeds_target", "At least one repeat exceeds target variance."),
    ("rule_high_error_log_ratio", "Median BER log estimate is far from reference r0."),
    ("rule_low_converged_rate", "Some repeats fail to converge within max_samples."),
    ("rule_slow_runtime", "Valid submission has repeat runtimes much slower than median."),
    ("rule_ber_log_drift", "Median err_rate_log drifts far from log(r0)."),
]


def get_rule_functions() -> List[RuleFn]:
    return [
        rule_invalid_submission,
        rule_std_exceeds_target,
        rule_high_error_log_ratio,
        rule_low_converged_rate,
        rule_slow_runtime,
        rule_ber_log_drift,
    ]


def get_rule_descriptions() -> List[str]:
    return [entry[1] for entry in RULE_CATALOG]
# EVOLVE-BLOCK-END
