# EVOLVE-BLOCK-START
"""Algorithm classification rules for PID tuning optimizer code."""

from __future__ import annotations

import re
from typing import Callable, List, Tuple

from code_rule_utils import (
    extract_evolve_block,
    has_call,
    has_name,
    parse_gain_assignments,
)

CodeStr = str
RuleFn = Callable[[CodeStr], Tuple[int, str]]

GAIN_KEYS = (
    "Kp_z", "Ki_z", "Kd_z", "N_z",
    "Kp_x", "Ki_x", "Kd_x", "N_x",
    "Kp_theta", "Ki_theta", "Kd_theta", "N_theta",
)


def _block(code: CodeStr) -> str:
    return extract_evolve_block(code)


def _gain_literals(code: CodeStr) -> dict[str, float]:
    block = _block(code)
    gains = parse_gain_assignments(block)
    for key in GAIN_KEYS:
        match = re.search(rf'"{key}"\s*:\s*([-+]?\d*\.?\d+)', block)
        if match:
            gains[key] = float(match.group(1))
        match = re.search(rf"'{key}'\s*:\s*([-+]?\d*\.?\d+)", block)
        if match:
            gains[key] = float(match.group(1))
    return gains


def rule_uses_integral_gain(code: CodeStr) -> Tuple[int, str]:
    gains = _gain_literals(code)
    ki_values = [gains.get("Ki_z", 0.0), gains.get("Ki_x", 0.0), gains.get("Ki_theta", 0.0)]
    if any(v > 0.1 for v in ki_values):
        return 1, f"Non-trivial integral gains present (Ki_z={ki_values[0]:.3f}, Ki_x={ki_values[1]:.3f})"
    return 0, "Integral gains are low or absent in baseline literals"


def rule_low_horizontal_gains(code: CodeStr) -> Tuple[int, str]:
    gains = _gain_literals(code)
    kp_x = gains.get("Kp_x", 0.0)
    kd_x = gains.get("Kd_x", 0.0)
    if kp_x < 0.3 or kd_x < 0.2:
        return 1, f"Horizontal gains are low (Kp_x={kp_x:.3f}, Kd_x={kd_x:.3f})"
    return 0, f"Horizontal gains are moderate (Kp_x={kp_x:.3f}, Kd_x={kd_x:.3f})"


def rule_high_altitude_ki(code: CodeStr) -> Tuple[int, str]:
    ki_z = _gain_literals(code).get("Ki_z", 0.0)
    if ki_z > 5.0:
        return 1, f"Altitude Ki_z={ki_z:.3f} > 5.0 (windup/overshoot risk)"
    return 0, f"Altitude Ki_z={ki_z:.3f} <= 5.0"


def rule_many_search_iterations(code: CodeStr) -> Tuple[int, str]:
    block = _block(code)
    loops = len(re.findall(r"\bfor\s+_", block))
    if loops >= 2:
        return 1, f"Optimizer uses {loops} search loops (multi-phase tuning)"
    return 0, f"Optimizer uses {loops} search loop(s)"


def rule_uses_clipping(code: CodeStr) -> Tuple[int, str]:
    if has_call(block := _block(code), "clip"):
        return 1, "Uses np.clip or clip for saturation/limiting"
    return 0, "No explicit clipping detected"


def rule_uses_derivative_filter(code: CodeStr) -> Tuple[int, str]:
    block = _block(code)
    if has_name(block, "N_z") or has_name(block, "N_x") or "df_z" in block or "df_x" in block:
        return 1, "Uses derivative filtering (N_* or filtered derivative state)"
    return 0, "No derivative filter pattern detected"


RULE_CATALOG = [
    ("rule_uses_integral_gain", "Optimizer sets non-trivial Ki gains in literals or dict."),
    ("rule_low_horizontal_gains", "Horizontal Kp_x or Kd_x literals are very low."),
    ("rule_high_altitude_ki", "Altitude Ki_z literal exceeds 5.0."),
    ("rule_many_search_iterations", "Multiple for-loops suggest multi-phase search."),
    ("rule_uses_clipping", "Code applies np.clip for saturation."),
    ("rule_uses_derivative_filter", "Code uses derivative filter gains or df_* state."),
]


def get_rule_functions() -> List[RuleFn]:
    return [
        rule_uses_integral_gain,
        rule_low_horizontal_gains,
        rule_high_altitude_ki,
        rule_many_search_iterations,
        rule_uses_clipping,
        rule_uses_derivative_filter,
    ]


def get_rule_descriptions() -> List[str]:
    return [entry[1] for entry in RULE_CATALOG]
# EVOLVE-BLOCK-END
