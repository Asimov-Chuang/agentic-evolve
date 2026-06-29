"""Utilities for algorithm-based rule discovery over optimizer source code."""

from __future__ import annotations

import ast
import re
from typing import Dict, List, Optional

EVOLVE_BLOCK_START = "# EVOLVE-BLOCK-START"
EVOLVE_BLOCK_END = "# EVOLVE-BLOCK-END"


def extract_evolve_block(code: str) -> str:
    """Return text inside EVOLVE-BLOCK markers, or full code if markers absent."""
    start = code.find(EVOLVE_BLOCK_START)
    end = code.find(EVOLVE_BLOCK_END)
    if start >= 0 and end > start:
        return code[start + len(EVOLVE_BLOCK_START) : end]
    return code


def has_call(code: str, name: str) -> bool:
    """True if code contains a call to ``name`` (e.g. ``np.clip`` or ``clip``)."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return name in code
    short = name.split(".")[-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == short:
                return True
            if isinstance(func, ast.Attribute) and func.attr == short:
                return True
    return short in code


def has_name(code: str, pattern: str) -> bool:
    """True if ``pattern`` appears as identifier or substring."""
    if pattern in code:
        return True
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == pattern:
            return True
        if isinstance(node, ast.Attribute) and node.attr == pattern:
            return True
    return False


def find_numeric_literals(code: str) -> List[float]:
    """Collect numeric literals from parseable code."""
    values: List[float] = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return values
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            values.append(float(node.value))
    return values


def parse_assignments(code: str) -> Dict[str, float]:
    """Extract simple top-level ``name = number`` assignments from evolve block."""
    block = extract_evolve_block(code)
    assignments: Dict[str, float] = {}
    try:
        tree = ast.parse(block)
    except SyntaxError:
        return _parse_assignments_regex(block)
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
                if isinstance(node.value.value, (int, float)):
                    assignments[target.id] = float(node.value.value)
    return assignments


def _parse_assignments_regex(code: str) -> Dict[str, float]:
    assignments: Dict[str, float] = {}
    for match in re.finditer(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)", code, re.M):
        try:
            assignments[match.group(1)] = float(match.group(2))
        except ValueError:
            continue
    return assignments


def parse_gain_assignments(code: str) -> Dict[str, float]:
    """Extract PID-style gain assignments (Kp_x, Ki_z, etc.)."""
    assignments = parse_assignments(code)
    return {k: v for k, v in assignments.items() if re.match(r"^[Kk][pidPID][_.]", k) or k.startswith(("Kp_", "Ki_", "Kd_"))}


def coef_above_threshold(assignments: Dict[str, float], key: str, threshold: float) -> bool:
    value = assignments.get(key)
    return value is not None and value > threshold


def literal_in_code(code: str, value: float, *, tolerance: float = 1e-9) -> bool:
    """True if a numeric literal approximately equal to ``value`` appears in code."""
    for lit in find_numeric_literals(code):
        if abs(lit - value) <= tolerance:
            return True
    return False
