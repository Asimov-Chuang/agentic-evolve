# EVOLVE-BLOCK-START
"""Seed mechanism model for AO temporal smooth control."""

from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Tuple

import numpy as np

from code_rule_utils import extract_evolve_block, has_name
from mechanism_types import MechanismLink

CodePredFn = Callable[[str], Tuple[int, str]]
TracePredFn = Callable[[Dict], Tuple[int, str]]
RawArtifact = Dict
Step = Dict


def _block(code: str) -> str:
    return extract_evolve_block(code)


def code_uses_prev_blend(code: str) -> Tuple[int, str]:
    block = _block(code)
    if has_name(block, "prev_commands") and ("prev_blend" in block or "blend" in block):
        return 1, "Uses prev_commands blending"
    return 0, "No prev_commands blend detected"


def _iter_episodes(raw: RawArtifact) -> Iterable[tuple[int, List[Step]]]:
    for block in raw.get("scenarios", []):
        steps = list(block.get("steps") or [])
        if steps:
            yield int(block.get("episode", 0)), steps


def _cmd_norm(step: Step) -> float:
    cmd = np.asarray((step.get("actions") or {}).get("cmd") or [], dtype=np.float64)
    return float(np.linalg.norm(cmd)) if cmd.size else 0.0


def _mean_slope_mag(step: Step) -> float:
    slopes = np.asarray((step.get("observations") or {}).get("slopes") or [], dtype=np.float64)
    return float(np.mean(np.abs(slopes))) if slopes.size else 0.0


def _step_cmd_delta(prev: Step | None, step: Step) -> float:
    if prev is None:
        return 0.0
    cmd = np.asarray((step.get("actions") or {}).get("cmd") or [], dtype=np.float64)
    pcmd = np.asarray((prev.get("actions") or {}).get("cmd") or [], dtype=np.float64)
    if cmd.size == 0 or pcmd.size == 0:
        return 0.0
    return float(np.linalg.norm(cmd - pcmd))


def code_aggressive_prev_blend(code: str) -> Tuple[int, str]:
    block = _block(code)
    if has_name(block, "prev_commands") and ("0.8" in block or "0.85" in block or "0.9" in block):
        return 1, "Strong prev_commands blend weight (>=0.8)"
    return 0, "No aggressive prev blend weight"


def code_uses_raw_reconstructor(code: str) -> Tuple[int, str]:
    block = _block(code)
    if "reconstructor@slopes" in block and "smooth_reconstructor" not in block:
        return 1, "Uses raw reconstructor@slopes without smooth_reconstructor"
    return 0, "Does not use raw-only reconstructor path"


def trace_high_slew_step_fraction(raw: RawArtifact) -> Tuple[int, str]:
    """Failure: >20% of steps have cmd delta above 0.06."""
    threshold, frac_thr = 0.06, 0.20
    high = 0
    total = 0
    for _ep, steps in _iter_episodes(raw):
        prev = None
        for step in steps:
            total += 1
            if _step_cmd_delta(prev, step) > threshold:
                high += 1
            prev = step
    if total == 0:
        return 0, "No steps in trajectory"
    frac = high / total
    if frac > frac_thr:
        return 1, f"High slew-step fraction {frac:.2%} > {frac_thr:.0%}"
    return 0, f"Slew-step fraction {frac:.2%} <= {frac_thr:.0%}"


def trace_low_slew_step_fraction(raw: RawArtifact) -> Tuple[int, str]:
    """Success signature: <=8% of steps have cmd delta above 0.06."""
    threshold, frac_thr = 0.06, 0.08
    high = 0
    total = 0
    for _ep, steps in _iter_episodes(raw):
        prev = None
        for step in steps:
            total += 1
            if _step_cmd_delta(prev, step) > threshold:
                high += 1
            prev = step
    if total == 0:
        return 0, "No steps in trajectory"
    frac = high / total
    if frac <= frac_thr:
        return 1, f"Low slew-step fraction {frac:.2%} <= {frac_thr:.0%}"
    return 0, f"Slew-step fraction {frac:.2%} > {frac_thr:.0%}"


def trace_under_correction_burst(raw: RawArtifact) -> Tuple[int, str]:
    """Failure: >=5 consecutive large-slope steps with weak ||cmd||."""
    min_run, slope_thr, cmd_thr = 5, 0.18, 0.04
    for ep, steps in _iter_episodes(raw):
        run = 0
        for step in steps:
            if _mean_slope_mag(step) > slope_thr and _cmd_norm(step) < cmd_thr:
                run += 1
                if run >= min_run:
                    return 1, f"Under-correction burst in episode {ep}"
            else:
                run = 0
    return 0, "No sustained under-correction burst"


def get_code_predicates() -> List[CodePredFn]:
    return [
        code_uses_prev_blend,
        code_aggressive_prev_blend,
        code_uses_raw_reconstructor,
    ]


def get_code_predicate_descriptions() -> List[str]:
    return [
        "Code blends current command with prev_commands",
        "Code uses strong prev blend weight (>= 0.8)",
        "Code uses raw reconstructor@slopes without smooth_reconstructor",
    ]


def get_trace_predicates() -> List[TracePredFn]:
    return [
        trace_high_slew_step_fraction,
        trace_low_slew_step_fraction,
        trace_under_correction_burst,
    ]


def get_trace_predicate_descriptions() -> List[str]:
    return [
        "Trajectory has a high fraction of large per-step command jumps",
        "Trajectory keeps per-step command jumps mostly small",
        "Trajectory has sustained under-correction bursts",
    ]


def get_mechanism_links() -> List[MechanismLink]:
    return [
        MechanismLink(
            source_kind="code",
            source_id="code_aggressive_prev_blend",
            target_kind="trace",
            target_id="trace_low_slew_step_fraction",
            effect="increase",
            rationale="Strong prev blending should increase low-slew-step fraction",
        ),
        MechanismLink(
            source_kind="code",
            source_id="code_uses_raw_reconstructor",
            target_kind="trace",
            target_id="trace_high_slew_step_fraction",
            effect="increase",
            rationale="Raw-only reconstruction tends to produce jittery commands",
        ),
        MechanismLink(
            source_kind="trace",
            source_id="trace_high_slew_step_fraction",
            target_kind="metric",
            target_id="mean_slew",
            effect="increase",
            rationale="More high-delta steps raise aggregate mean_slew",
        ),
        MechanismLink(
            source_kind="trace",
            source_id="trace_low_slew_step_fraction",
            target_kind="metric",
            target_id="mean_slew",
            effect="decrease",
            rationale="Smooth step-wise commands reduce mean_slew",
        ),
        MechanismLink(
            source_kind="trace",
            source_id="trace_high_slew_step_fraction",
            target_kind="metric",
            target_id="score",
            effect="decrease",
            rationale="Slew-heavy trajectories lose score via u_mean_slew",
        ),
        MechanismLink(
            source_kind="trace",
            source_id="trace_under_correction_burst",
            target_kind="metric",
            target_id="mean_rms",
            effect="increase",
            rationale="Under-correction leaves residual wavefront error high",
        ),
    ]
# EVOLVE-BLOCK-END
