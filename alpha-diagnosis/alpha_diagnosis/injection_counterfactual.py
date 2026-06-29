"""Counterfactual injection for trajectory mode-detection rules.

Pairs baseline trajectory evidence with a higher-scoring archive attempt at the
same episode/step so the agent can see *what differed*, not only mode labels.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Sequence, Tuple

import numpy as np

from alpha_diagnosis.injection_pro import (
    _truncate_code,
    align_rule_functions_by_name,
    load_rule_functions,
    resolve_rule_program_path,
)
from alpha_diagnosis.rule_extract import RuleSpec

TrajectoryRuleFn = Callable[[Dict[str, Any]], Tuple[int, str]]

_EP_STEP_RE = re.compile(r"episode\s+(\d+)\s*@\s*step\s+(\d+)", re.IGNORECASE)
_EP_ONLY_RE = re.compile(r"episode\s+(\d+)", re.IGNORECASE)


@dataclass
class TrajectorySite:
    episode: int
    step: int
    mean_slope: float
    cmd_norm: float
    response_ratio: float
    cmd_delta: float | None = None


@dataclass
class CounterfactualEvidence:
    rule_index: int
    rule_name: str
    rule_description: str
    score_effect: str | None
    baseline_attempt_id: str
    baseline_score: float
    baseline_triggered: bool
    baseline_explanation: str
    baseline_site: TrajectorySite | None
    exemplar_attempt_id: str
    exemplar_score: float
    exemplar_triggered: bool
    exemplar_explanation: str
    exemplar_site: TrajectorySite | None
    narrative: str
    code_excerpt: str
    action_hint: str


@dataclass
class CounterfactualInjectionContext:
    rules: List[RuleSpec]
    baseline_attempt_id: str
    baseline_score: float | None
    pairs: List[CounterfactualEvidence] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def _load_strip_fn() -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    shared = Path(__file__).resolve().parents[2] / "examples" / "diagnostic-rule-discovery" / "_shared"
    base_path = shared / "evaluator_base.py"
    if not base_path.is_file():
        raise FileNotFoundError(f"Missing evaluator_base.py at {base_path}")
    spec = importlib.util.spec_from_file_location("evaluator_base_cf", base_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {base_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.strip_policy_visible_optics


def _load_raw_artifact(attempt_dir: Path) -> Dict[str, Any] | None:
    path = attempt_dir / "raw-artifact.json"
    if not path.is_file():
        return None
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    strip = _load_strip_fn()
    return strip(raw)


def _iter_episodes(raw: Dict[str, Any]) -> List[Tuple[int, List[Dict[str, Any]]]]:
    out: List[Tuple[int, List[Dict[str, Any]]]] = []
    for block in raw.get("scenarios") or []:
        steps = list(block.get("steps") or [])
        if steps:
            out.append((int(block.get("episode", 0)), steps))
    return out


def _mean_slope_mag(step: Dict[str, Any]) -> float:
    slopes = np.asarray((step.get("observations") or {}).get("slopes") or [], dtype=np.float64)
    return float(np.mean(np.abs(slopes))) if slopes.size else 0.0


def _cmd_norm(step: Dict[str, Any]) -> float:
    cmd = np.asarray((step.get("actions") or {}).get("cmd") or [], dtype=np.float64)
    return float(np.linalg.norm(cmd)) if cmd.size else 0.0


def _cmd_delta(step: Dict[str, Any]) -> float | None:
    cmd = np.asarray((step.get("actions") or {}).get("cmd") or [], dtype=np.float64)
    prev = np.asarray((step.get("observations") or {}).get("prev_commands") or [], dtype=np.float64)
    if cmd.size == 0 or prev.size == 0:
        return None
    return float(np.linalg.norm(cmd - prev))


def _response_ratio(step: Dict[str, Any]) -> float:
    ms = _mean_slope_mag(step)
    if ms < 1e-6:
        return 0.0
    return _cmd_norm(step) / ms


def _site_from_raw(raw: Dict[str, Any], episode: int, step_idx: int) -> TrajectorySite | None:
    for ep, steps in _iter_episodes(raw):
        if ep != episode or step_idx < 0 or step_idx >= len(steps):
            continue
        step = steps[step_idx]
        return TrajectorySite(
            episode=ep,
            step=step_idx,
            mean_slope=_mean_slope_mag(step),
            cmd_norm=_cmd_norm(step),
            response_ratio=_response_ratio(step),
            cmd_delta=_cmd_delta(step),
        )
    return None


def _parse_site_hint(explanation: str) -> Tuple[int | None, int | None]:
    match = _EP_STEP_RE.search(explanation)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = _EP_ONLY_RE.search(explanation)
    if match:
        return int(match.group(1)), None
    return None, None


def _first_active_site(raw: Dict[str, Any], episode: int) -> TrajectorySite | None:
    for ep, steps in _iter_episodes(raw):
        if ep != episode:
            continue
        for i, step in enumerate(steps):
            if _mean_slope_mag(step) > 0.10:
                return _site_from_raw(raw, ep, i)
    return None


def _exemplar_priority(
    *,
    score_effect: str | None,
    baseline_triggered: bool,
    exemplar_triggered: bool,
    exemplar_score: float,
    baseline_score: float,
) -> int:
    delta = exemplar_score - baseline_score
    contrast = exemplar_triggered != baseline_triggered
    if score_effect == "negative":
        if baseline_triggered and not exemplar_triggered:
            return 5 if delta > 0 else 4
        if contrast and delta > -0.002:
            return 3
        if delta > 0:
            return 2
        return 0
    if score_effect == "positive":
        if not baseline_triggered and exemplar_triggered:
            return 5 if delta > 0 else 4
        if exemplar_triggered and delta > 0:
            return 4
        if contrast and delta > -0.002:
            return 3
        if delta > 0:
            return 2
        return 0
    if contrast and delta > -0.002:
        return 3
    if delta > 0:
        return 2
    return 1 if delta > -0.005 else 0


def _action_hint(score_effect: str | None, baseline_triggered: bool, exemplar_triggered: bool) -> str:
    if score_effect == "negative":
        if baseline_triggered and not exemplar_triggered:
            return "Remove or counteract the failure mode shown in the baseline trajectory."
        return "Reduce behaviors that trigger this failure mode on the baseline."
    if score_effect == "positive":
        if not baseline_triggered and exemplar_triggered:
            return "Add the success signature the exemplar shows but baseline lacks."
        return "Strengthen the behavioral signature associated with higher scores."
    if baseline_triggered != exemplar_triggered:
        return "Align baseline trajectory behavior with the exemplar at the cited episode/step."
    return "Borrow structural changes from the exemplar that improve trajectory response."


def _format_site(site: TrajectorySite | None) -> str:
    if site is None:
        return "(no site metrics)"
    parts = [
        f"ep={site.episode} step={site.step}",
        f"mean|slope|={site.mean_slope:.4f}",
        f"||cmd||={site.cmd_norm:.4f}",
        f"response_ratio={site.response_ratio:.3f}",
    ]
    if site.cmd_delta is not None:
        parts.append(f"||cmd-prev_cmd||={site.cmd_delta:.4f}")
    return ", ".join(parts)


def _build_narrative(
    *,
    rule_name: str,
    baseline_id: str,
    baseline_score: float,
    baseline_triggered: bool,
    baseline_exp: str,
    baseline_site: TrajectorySite | None,
    exemplar_id: str,
    exemplar_score: float,
    exemplar_triggered: bool,
    exemplar_exp: str,
    exemplar_site: TrajectorySite | None,
) -> str:
    lines = [
        f"Mode `{rule_name}`: baseline {baseline_id} (score={baseline_score:.4f}, "
        f"triggered={baseline_triggered}) — {baseline_exp}",
        f"  Baseline site: {_format_site(baseline_site)}",
        f"Counterfactual {exemplar_id} (score={exemplar_score:.4f}, "
        f"triggered={exemplar_triggered}) — {exemplar_exp}",
        f"  Exemplar site: {_format_site(exemplar_site)}",
    ]
    if baseline_site and exemplar_site and baseline_site.episode == exemplar_site.episode:
        rr_delta = exemplar_site.response_ratio - baseline_site.response_ratio
        cmd_delta = exemplar_site.cmd_norm - baseline_site.cmd_norm
        lines.append(
            f"At episode {baseline_site.episode} step {baseline_site.step}: "
            f"response_ratio {baseline_site.response_ratio:.3f} → {exemplar_site.response_ratio:.3f} "
            f"(Δ{rr_delta:+.3f}), ||cmd|| {baseline_site.cmd_norm:.4f} → {exemplar_site.cmd_norm:.4f} "
            f"(Δ{cmd_delta:+.4f})."
        )
    return "\n".join(lines)


def _load_scored_attempts_with_raw(
    archive_dir: Path,
    *,
    top_k: int,
    maximize: bool,
    max_scan: int = 80,
) -> List[Tuple[str, float, Dict[str, Any] | None, str]]:
    rows: List[Tuple[str, float, Dict[str, Any] | None, str]] = []
    for attempt_dir in sorted(archive_dir.glob("attempt_*")):
        result_path = attempt_dir / "result.json"
        if not result_path.is_file():
            continue
        with open(result_path, encoding="utf-8") as f:
            result = json.load(f)
        if not result.get("is_valid", True):
            continue
        score = float(result.get("score", float("-inf") if maximize else float("inf")))
        raw = _load_raw_artifact(attempt_dir)
        if raw is None:
            continue
        code = ""
        code_path = attempt_dir / "code.py"
        if code_path.is_file():
            code = code_path.read_text(encoding="utf-8")
        rows.append((attempt_dir.name, score, raw, code))
    rows.sort(key=lambda r: r[1], reverse=maximize)
    limit = max(top_k, max_scan)
    return rows[:limit]


def build_counterfactual_injection_context(
    archive_dir: Path,
    rules: Sequence[RuleSpec],
    rule_fns: Sequence[TrajectoryRuleFn],
    rule_names: Sequence[str] | None = None,
    *,
    baseline_attempt_id: str,
    baseline_score: float | None,
    top_k: int = 15,
    max_code_lines: int = 40,
    maximize: bool = True,
) -> CounterfactualInjectionContext:
    aligned_fns, _aligned_names, align_warnings = align_rule_functions_by_name(
        rules, rule_fns, rule_names or []
    )
    ctx = CounterfactualInjectionContext(
        rules=list(rules),
        baseline_attempt_id=baseline_attempt_id,
        baseline_score=baseline_score,
    )
    ctx.warnings.extend(align_warnings)

    baseline_dir = archive_dir / baseline_attempt_id
    baseline_raw = _load_raw_artifact(baseline_dir)
    if baseline_raw is None:
        ctx.warnings.append(
            f"{baseline_attempt_id} has no raw-artifact.json; counterfactual evidence "
            "requires store_raw_artifacts: true on the primary task."
        )
        return ctx

    scored = _load_scored_attempts_with_raw(archive_dir, top_k=top_k, maximize=maximize)
    if not any(raw is not None for _, _, raw, _ in scored):
        ctx.warnings.append("No raw-artifact.json found in top-K archive attempts.")
        return ctx

    baseline_score_val = baseline_score if baseline_score is not None else float("-inf")

    for rule, rule_fn in zip(rules, aligned_fns):
        idx = rule.index
        if rule_fn is None:
            ctx.pairs.append(
                CounterfactualEvidence(
                    rule_index=idx,
                    rule_name=rule.name,
                    rule_description=rule.description,
                    score_effect=rule.score_effect,
                    baseline_attempt_id=baseline_attempt_id,
                    baseline_score=baseline_score_val,
                    baseline_triggered=False,
                    baseline_explanation="Rule function unavailable",
                    baseline_site=None,
                    exemplar_attempt_id="none",
                    exemplar_score=baseline_score_val,
                    exemplar_triggered=False,
                    exemplar_explanation="",
                    exemplar_site=None,
                    narrative=f"Mode `{rule.name}`: no trajectory rule function loaded.",
                    code_excerpt="",
                    action_hint="Address this mode using its description and archive code review.",
                )
            )
            continue

        b_trig = 0
        b_exp = "Rule not evaluated"
        try:
            b_trig, b_exp = rule_fn(baseline_raw)
        except Exception as exc:
            b_exp = f"Rule evaluation failed: {exc}"

        ep_hint, step_hint = _parse_site_hint(b_exp)
        baseline_site = None
        if ep_hint is not None and step_hint is not None:
            baseline_site = _site_from_raw(baseline_raw, ep_hint, step_hint)
        elif ep_hint is not None:
            baseline_site = _first_active_site(baseline_raw, ep_hint)

        best: Tuple[int, float, str, int, str, Dict[str, Any] | None, str] | None = None
        for attempt_id, score, raw, code in scored:
            if attempt_id == baseline_attempt_id or raw is None:
                continue
            try:
                e_trig, e_exp = rule_fn(raw)
            except Exception:
                continue
            priority = _exemplar_priority(
                score_effect=rule.score_effect,
                baseline_triggered=bool(b_trig),
                exemplar_triggered=bool(e_trig),
                exemplar_score=score,
                baseline_score=baseline_score_val,
            )
            if priority <= 0:
                continue
            candidate = (priority, score, attempt_id, e_trig, e_exp, raw, code)
            if best is None or (candidate[0], candidate[1]) > (best[0], best[1]):
                best = candidate

        if best is None:
            for attempt_id, score, raw, code in scored:
                if attempt_id == baseline_attempt_id or raw is None:
                    continue
                try:
                    e_trig, e_exp = rule_fn(raw)
                except Exception:
                    continue
                if e_trig == b_trig and abs(score - baseline_score_val) < 1e-9:
                    continue
                candidate = (1, score, attempt_id, e_trig, e_exp, raw, code)
                if best is None or (candidate[1], abs(int(e_trig) - int(b_trig))) > (
                    best[1],
                    abs(int(best[3]) - int(b_trig)),
                ):
                    best = candidate

        if best is None:
            ctx.warnings.append(f"No counterfactual exemplar for rule {rule.name}")
            ctx.pairs.append(
                CounterfactualEvidence(
                    rule_index=idx,
                    rule_name=rule.name,
                    rule_description=rule.description,
                    score_effect=rule.score_effect,
                    baseline_attempt_id=baseline_attempt_id,
                    baseline_score=baseline_score_val,
                    baseline_triggered=bool(b_trig),
                    baseline_explanation=b_exp,
                    baseline_site=baseline_site,
                    exemplar_attempt_id="none",
                    exemplar_score=baseline_score_val,
                    exemplar_triggered=False,
                    exemplar_explanation="No higher-scoring attempt with raw trajectory available.",
                    exemplar_site=None,
                    narrative=(
                        f"Mode `{rule.name}` on baseline: triggered={bool(b_trig)} — {b_exp}\n"
                        "No counterfactual exemplar found in archive top-K."
                    ),
                    code_excerpt="",
                    action_hint=_action_hint(rule.score_effect, bool(b_trig), False),
                )
            )
            continue

        _, e_score, e_id, e_trig, e_exp, e_raw, e_code = best
        exemplar_site = None
        if baseline_site is not None:
            exemplar_site = _site_from_raw(e_raw, baseline_site.episode, baseline_site.step)
            if exemplar_site is None:
                exemplar_site = _first_active_site(e_raw, baseline_site.episode)
        if exemplar_site is None:
            ep2, step2 = _parse_site_hint(e_exp)
            if ep2 is not None and step2 is not None:
                exemplar_site = _site_from_raw(e_raw, ep2, step2)
            elif ep2 is not None:
                exemplar_site = _first_active_site(e_raw, ep2)

        narrative = _build_narrative(
            rule_name=rule.name,
            baseline_id=baseline_attempt_id,
            baseline_score=baseline_score_val,
            baseline_triggered=bool(b_trig),
            baseline_exp=b_exp,
            baseline_site=baseline_site,
            exemplar_id=e_id,
            exemplar_score=e_score,
            exemplar_triggered=bool(e_trig),
            exemplar_exp=e_exp,
            exemplar_site=exemplar_site,
        )
        ctx.pairs.append(
            CounterfactualEvidence(
                rule_index=idx,
                rule_name=rule.name,
                rule_description=rule.description,
                score_effect=rule.score_effect,
                baseline_attempt_id=baseline_attempt_id,
                baseline_score=baseline_score_val,
                baseline_triggered=bool(b_trig),
                baseline_explanation=b_exp,
                baseline_site=baseline_site,
                exemplar_attempt_id=e_id,
                exemplar_score=e_score,
                exemplar_triggered=bool(e_trig),
                exemplar_explanation=e_exp,
                exemplar_site=exemplar_site,
                narrative=narrative,
                code_excerpt=_truncate_code(e_code, max_code_lines) if e_code else "",
                action_hint=_action_hint(rule.score_effect, bool(b_trig), bool(e_trig)),
            )
        )

    return ctx
