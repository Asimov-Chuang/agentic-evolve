# EVOLVE-BLOCK-START
"""Mode-detection diagnostic rules for AO temporal smooth control.

Each rule scans policy-visible trajectories for a named failure mode or success
signature. Returns 1 if the mode is present on the attempt, else 0.
"""

from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Tuple

import numpy as np

RawArtifact = Dict
Step = Dict
RuleFn = Callable[[RawArtifact], Tuple[int, str]]


def _iter_episodes(raw: RawArtifact) -> Iterable[tuple[int, List[Step]]]:
    for block in raw.get("scenarios", []):
        steps = list(block.get("steps") or [])
        if steps:
            yield int(block.get("episode", 0)), steps


def _slopes(step: Step) -> np.ndarray:
    return np.asarray((step.get("observations") or {}).get("slopes") or [], dtype=np.float64)


def _cmd(step: Step) -> np.ndarray:
    return np.asarray((step.get("actions") or {}).get("cmd") or [], dtype=np.float64)


def _mean_slope_mag(step: Step) -> float:
    slopes = _slopes(step)
    return float(np.mean(np.abs(slopes))) if slopes.size else 0.0


def _cmd_norm(step: Step) -> float:
    cmd = _cmd(step)
    return float(np.linalg.norm(cmd)) if cmd.size else 0.0


def _cmd_slope_cosine(step: Step) -> float:
    cmd, slopes = _cmd(step), _slopes(step)
    if cmd.size == 0 or slopes.size == 0:
        return 0.0
    cn, sn = float(np.linalg.norm(cmd)), float(np.linalg.norm(slopes))
    if cn < 1e-9 or sn < 1e-9:
        return 0.0
    return float(np.dot(cmd, slopes) / (cn * sn))


def _response_ratio(step: Step) -> float:
    ms = _mean_slope_mag(step)
    if ms < 1e-6:
        return 0.0
    return _cmd_norm(step) / ms


def mode_sustained_under_correction_burst(raw: RawArtifact) -> Tuple[int, str]:
    """Failure: >=5 consecutive large-slope steps with weak ||cmd||."""
    min_run, slope_thr, cmd_thr = 5, 0.18, 0.04
    for ep, steps in _iter_episodes(raw):
        run = 0
        for step in steps:
            if _mean_slope_mag(step) > slope_thr and _cmd_norm(step) < cmd_thr:
                run += 1
                if run >= min_run:
                    return 1, f"Under-correction burst (run>={min_run}) in episode {ep}"
            else:
                run = 0
    return 0, "No sustained under-correction burst"


def mode_regime_transition_lag(raw: RawArtifact) -> Tuple[int, str]:
    """Failure: after calm→active transition, response ratio stays low for 3 steps."""
    for ep, steps in _iter_episodes(raw):
        for i in range(1, len(steps) - 2):
            prev_calm = _mean_slope_mag(steps[i - 1]) < 0.08
            now_active = _mean_slope_mag(steps[i]) > 0.12
            if not (prev_calm and now_active):
                continue
            lag = all(_response_ratio(steps[j]) < 0.12 for j in range(i, i + 3))
            if lag:
                return 1, f"Regime-transition lag after calm→active in episode {ep} @ step {i}"
    return 0, "No regime-transition lag"


def mode_misaligned_correction_streak(raw: RawArtifact) -> Tuple[int, str]:
    """Failure: >=4 consecutive active-slope steps with poor cmd–slope alignment."""
    min_run, slope_thr, cos_thr = 4, 0.12, 0.10
    for ep, steps in _iter_episodes(raw):
        run = 0
        for step in steps:
            if _mean_slope_mag(step) > slope_thr and _cmd_slope_cosine(step) < cos_thr:
                run += 1
                if run >= min_run:
                    return 1, f"Misaligned correction streak (run>={min_run}) in episode {ep}"
            else:
                run = 0
    return 0, "No misaligned correction streak"


def mode_late_episode_collapse(raw: RawArtifact) -> Tuple[int, str]:
    """Failure: late-segment ||cmd|| < 50% of early-segment on same episode."""
    for ep, steps in _iter_episodes(raw):
        if len(steps) < 40:
            continue
        early = [_cmd_norm(s) for s in steps[:15] if _mean_slope_mag(s) > 0.10]
        late = [_cmd_norm(s) for s in steps[-15:] if _mean_slope_mag(s) > 0.10]
        if len(early) < 5 or len(late) < 5:
            continue
        if float(np.mean(late)) < 0.5 * float(np.mean(early)):
            return 1, f"Late-episode collapse ep={ep} (late_mean={np.mean(late):.4f} < 0.5*early)"
    return 0, "No late-episode collapse"


def mode_cross_episode_response_inconsistency(raw: RawArtifact) -> Tuple[int, str]:
    """Failure: per-episode active-step mean ||cmd|| spread exceeds threshold."""
    episode_means: List[float] = []
    for _ep, steps in _iter_episodes(raw):
        active = [_cmd_norm(s) for s in steps if _mean_slope_mag(s) > 0.12]
        if len(active) >= 10:
            episode_means.append(float(np.mean(active)))
    if len(episode_means) < 4:
        return 0, "Too few episodes for inconsistency check"
    spread = max(episode_means) - min(episode_means)
    if spread > 0.025:
        return 1, f"Cross-episode response inconsistency (spread={spread:.4f})"
    return 0, f"Cross-episode response consistent (spread={spread:.4f})"


def mode_slopes_rising_cmd_flat(raw: RawArtifact) -> Tuple[int, str]:
    """Failure: 5-step window with rising slopes but flat cmd norm (delay mismatch)."""
    window = 5
    for ep, steps in _iter_episodes(raw):
        if len(steps) < window:
            continue
        for i in range(len(steps) - window + 1):
            chunk = steps[i : i + window]
            slope_series = [_mean_slope_mag(s) for s in chunk]
            cmd_series = [_cmd_norm(s) for s in chunk]
            if slope_series[-1] <= slope_series[0] * 1.15:
                continue
            if float(np.std(cmd_series)) < 0.004 and slope_series[-1] > 0.14:
                return 1, f"Rising slopes / flat cmd in episode {ep} @ step {i}"
    return 0, "No rising-slope / flat-cmd window"


def mode_calm_over_commanding_episodes(raw: RawArtifact) -> Tuple[int, str]:
    """Failure: majority of episodes show heavy ||cmd|| on calm steps."""
    hit_episodes = 0
    total = 0
    for ep, steps in _iter_episodes(raw):
        calm = [s for s in steps if _mean_slope_mag(s) < 0.08]
        if len(calm) < 10:
            continue
        total += 1
        frac = sum(1 for s in calm if _cmd_norm(s) > 0.06) / len(calm)
        if frac > 0.30:
            hit_episodes += 1
    if total >= 4 and hit_episodes / total > 0.50:
        return 1, f"Calm over-commanding in {hit_episodes}/{total} episodes"
    return 0, f"Calm over-commanding absent ({hit_episodes}/{total} episodes)"


def mode_stable_alignment_signature(raw: RawArtifact) -> Tuple[int, str]:
    """Success signature: low variance of episode-mean cmd–slope cosine on active steps."""
    cosines: List[float] = []
    for _ep, steps in _iter_episodes(raw):
        active_cos = [_cmd_slope_cosine(s) for s in steps if _mean_slope_mag(s) > 0.12]
        if len(active_cos) >= 10:
            cosines.append(float(np.mean(active_cos)))
    if len(cosines) < 4:
        return 0, "Too few episodes for alignment stability"
    var = float(np.var(cosines))
    if var < 0.002:
        return 1, f"Stable alignment across episodes (var={var:.5f})"
    return 0, f"Unstable alignment across episodes (var={var:.5f})"


RULE_CATALOG = [
    (
        "mode_sustained_under_correction_burst",
        "Failure mode: at least one episode has >=5 consecutive large-slope steps with ||cmd|| < 0.04.",
        mode_sustained_under_correction_burst,
    ),
    (
        "mode_regime_transition_lag",
        "Failure mode: after calm→active slope transition, response ratio stays < 0.12 for 3 consecutive steps.",
        mode_regime_transition_lag,
    ),
    (
        "mode_misaligned_correction_streak",
        "Failure mode: >=4 consecutive active-slope steps with cosine(cmd, slopes) < 0.10.",
        mode_misaligned_correction_streak,
    ),
    (
        "mode_late_episode_collapse",
        "Failure mode: on an episode, mean ||cmd|| in last 15 active steps < 50% of first 15 active steps.",
        mode_late_episode_collapse,
    ),
    (
        "mode_cross_episode_response_inconsistency",
        "Failure mode: spread of per-episode active-step mean ||cmd|| exceeds 0.025 across episodes.",
        mode_cross_episode_response_inconsistency,
    ),
    (
        "mode_slopes_rising_cmd_flat",
        "Failure mode: 5-step window with rising mean(abs(slopes)) but near-flat ||cmd|| (std < 0.004).",
        mode_slopes_rising_cmd_flat,
    ),
    (
        "mode_calm_over_commanding_episodes",
        "Failure mode: >50% of episodes have >30% of calm steps with ||cmd|| > 0.06.",
        mode_calm_over_commanding_episodes,
    ),
    (
        "mode_stable_alignment_signature",
        "Success signature: variance of episode-mean cosine(cmd, slopes) on active steps < 0.002.",
        mode_stable_alignment_signature,
    ),
]


def get_rule_functions() -> List[RuleFn]:
    return [fn for _name, _desc, fn in RULE_CATALOG]


def get_rule_descriptions() -> List[str]:
    return [desc for _name, desc, _fn in RULE_CATALOG]
# EVOLVE-BLOCK-END
