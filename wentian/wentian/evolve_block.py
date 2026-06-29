from __future__ import annotations

import re

EVOLVE_START = re.compile(
    r"^\s*#\s*(EVOLVE-BLOCK-START|START-EVOLVE-BLOCK|BEGIN-EVOLVE-BLOCK)\s*$",
    re.MULTILINE,
)
EVOLVE_END = re.compile(
    r"^\s*#\s*(EVOLVE-BLOCK-END|END-EVOLVE-BLOCK)\s*$",
    re.MULTILINE,
)

FOCUS_HINTS: dict[str, str] = {
    "load_shifting": (
        "Focus evolution on `_act_load_shifting` and closely related load-shifting logic. "
        "Keep `decide_actions` signature and return structure unchanged unless necessary."
    ),
    "cooling": (
        "Focus evolution on data-center cooling / `agent_dc` action logic. "
        "Minimize changes to load-shifting and battery logic."
    ),
    "battery": (
        "Focus evolution on battery / `agent_bat` action logic. "
        "Minimize changes to load-shifting and cooling logic."
    ),
    "decide_actions": (
        "Focus on coordinating all three agents inside `decide_actions`. "
        "You may refactor helper functions but preserve the public API."
    ),
    "temporal_smoothing": (
        "Focus evolution on `compute_dm_commands` temporal smoothing: blend with "
        "`prev_commands`, limit per-frame change, and use `control_model` smoothing fields."
    ),
    "slew_reduction": (
        "Focus on reducing mean command slew (|u_t - u_{t-1}|) inside `compute_dm_commands`. "
        "Preserve finite bounded output and the function signature."
    ),
    "delay_compensation": (
        "Focus on handling delayed/noisy slopes using `delay_prediction_gain` and related "
        "`control_model` fields in `compute_dm_commands`."
    ),
    "lowpass_filtering": (
        "Focus on `command_lowpass` and filtering strategies in `compute_dm_commands` "
        "to suppress high-frequency command jitter."
    ),
    "prev_command_blend": (
        "Focus on `prev_blend` and explicit mixing with `prev_commands` in "
        "`compute_dm_commands`."
    ),
    "smooth_reconstructor": (
        "Focus on using `smooth_reconstructor` vs baseline `reconstructor` in "
        "`compute_dm_commands`."
    ),
}


def has_evolve_block(code: str) -> bool:
    return bool(EVOLVE_START.search(code) and EVOLVE_END.search(code))


def extract_evolve_block(code: str) -> str | None:
    start = EVOLVE_START.search(code)
    end = EVOLVE_END.search(code)
    if not start or not end or end.start() <= start.end():
        return None
    return code[start.end() : end.start()]


def focus_prompt_append(focus: str | None) -> str:
    if not focus:
        return ""
    key = focus.strip().lower().replace("-", "_").replace(" ", "_")
    hint = FOCUS_HINTS.get(key)
    if hint:
        return f"\n\n## Evolution focus: {focus}\n\n{hint}\n"
    return (
        f"\n\n## Evolution focus: {focus}\n\n"
        f"Prioritize changes related to `{focus}` within the EVOLVE-BLOCK. "
        "Keep unrelated code stable when possible.\n"
    )
