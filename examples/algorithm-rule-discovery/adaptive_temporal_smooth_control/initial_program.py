# EVOLVE-BLOCK-START
"""Algorithm classification rules for AO temporal smooth control code."""

from __future__ import annotations

import re
from typing import Callable, List, Tuple

from code_rule_utils import (
    extract_evolve_block,
    find_numeric_literals,
    has_call,
    has_name,
    literal_in_code,
)

CodeStr = str
RuleFn = Callable[[CodeStr], Tuple[int, str]]


def _block(code: CodeStr) -> str:
    return extract_evolve_block(code)


def rule_uses_temporal_smoothing(code: CodeStr) -> Tuple[int, str]:
    block = _block(code)
    if has_name(block, "smooth_reconstructor") or "sr @" in block or "sr @ slopes" in block:
        return 1, "Uses temporal smoothing via smooth_reconstructor"
    if re.search(r"0\.\d+\s*\*\s*raw\s*\+\s*0\.\d+\s*\*\s*\(", block):
        return 1, "Blends raw and smoothed reconstruction (temporal mix)"
    return 0, "No temporal smoothing pattern detected"


def rule_uses_delta_limiting(code: CodeStr) -> Tuple[int, str]:
    block = _block(code)
    if has_call(block, "tanh") and ("delta" in block or "prev_commands" in block):
        return 1, "Uses tanh-based delta limiting with prev_commands"
    return 0, "No tanh delta-limiting pattern detected"


def rule_large_raw_weight(code: CodeStr) -> Tuple[int, str]:
    block = _block(code)
    for lit in find_numeric_literals(block):
        if 0.15 <= lit <= 0.5 and "raw" in block:
            return 1, f"Large raw blend weight detected (literal={lit:.3f})"
    if literal_in_code(block, 0.075) and "raw" in block:
        return 0, "Baseline-like low raw weight (0.075) present"
    return 0, "No large raw weight pattern"


def rule_uses_prev_commands(code: CodeStr) -> Tuple[int, str]:
    block = _block(code)
    if "prev_commands" in block:
        return 1, "Algorithm depends on prev_commands (temporal state)"
    return 0, "No prev_commands dependency"


def rule_aggressive_slew(code: CodeStr) -> Tuple[int, str]:
    block = _block(code)
    literals = find_numeric_literals(block)
    for lit in literals:
        if lit >= 0.08 and ("limit" in block or "tanh_scale" in block):
            return 1, f"Large slew/limit literal {lit:.3f} (aggressive command changes)"
    return 0, "Slew/limit literals appear conservative"


def rule_no_clipping(code: CodeStr) -> Tuple[int, str]:
    block = _block(code)
    if not has_call(block, "clip"):
        return 1, "Missing np.clip saturation (voltage limiting absent)"
    return 0, "Uses np.clip for command saturation"


def rule_uses_prev_blend(code: CodeStr) -> Tuple[int, str]:
    block = _block(code)
    if "prev_blend" in block:
        return 1, "Uses prev_blend from control_model"
    return 0, "No prev_blend usage detected"


def rule_uses_control_model_get(code: CodeStr) -> Tuple[int, str]:
    block = _block(code)
    if "control_model.get(" in block or ".get(" in block and "control_model" in block:
        return 1, "Uses control_model.get() for optional fields"
    return 0, "No control_model.get() pattern detected"


RULE_CATALOG = [
    ("rule_uses_temporal_smoothing", "Uses smooth_reconstructor or raw/smooth blend."),
    ("rule_uses_delta_limiting", "Applies tanh delta limiting on command changes."),
    ("rule_large_raw_weight", "Raw reconstruction weight is relatively large."),
    ("rule_uses_prev_commands", "Uses prev_commands for temporal continuity."),
    ("rule_aggressive_slew", "Large limit/tanh_scale literals allow fast slew."),
    ("rule_no_clipping", "No np.clip voltage saturation in evolve block."),
    ("rule_uses_prev_blend", "Uses prev_blend from control_model."),
    ("rule_uses_control_model_get", "Uses control_model.get() for safe access."),
]


def get_rule_functions() -> List[RuleFn]:
    return [
        rule_uses_temporal_smoothing,
        rule_uses_delta_limiting,
        rule_large_raw_weight,
        rule_uses_prev_commands,
        rule_aggressive_slew,
        rule_no_clipping,
        rule_uses_prev_blend,
        rule_uses_control_model_get,
    ]


def get_rule_descriptions() -> List[str]:
    return [entry[1] for entry in RULE_CATALOG]
# EVOLVE-BLOCK-END
