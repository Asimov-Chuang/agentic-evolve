"""Pro rule injection: exemplars per rule + top-K coverage matrix for synthesis prompts."""

from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Sequence, Tuple

from alpha_diagnosis.rule_extract import RuleSpec

RuleFn = Callable[[str], Tuple[int, str]]


@dataclass
class RuleExemplar:
    attempt_id: str
    score: float
    code_excerpt: str
    rule_explanation: str


@dataclass
class TopKAttemptCoverage:
    attempt_id: str
    score: float
    satisfied_rule_indices: List[int]
    satisfied_rule_names: List[str]
    code_excerpt: str


@dataclass
class RuleCooccurrence:
    rule_names: List[str]
    attempt_count: int
    best_score: float
    best_attempt_id: str
    avg_score: float


@dataclass
class SynthesisSeed:
    attempt_id: str
    score: float
    added_positive_rules: List[str]
    satisfied_rule_names: List[str]
    code_excerpt: str


@dataclass
class BaselineGapAnalysis:
    satisfied_positive: List[str]
    satisfied_negative: List[str]
    missing_positive: List[str]
    missing_positive_descriptions: List[str]


@dataclass
class ProInjectionContext:
    rules: List[RuleSpec]
    rule_exemplars: dict[int, List[RuleExemplar]] = field(default_factory=dict)
    top_k_coverage: List[TopKAttemptCoverage] = field(default_factory=list)
    baseline_attempt_id: str = "none"
    baseline_score: float | None = None
    baseline_gaps: BaselineGapAnalysis | None = None
    rule_cooccurrence: List[RuleCooccurrence] = field(default_factory=list)
    synthesis_seeds: List[SynthesisSeed] = field(default_factory=list)


def load_rule_functions(program_path: Path) -> Tuple[List[RuleFn], List[str]]:
    """Load get_rule_functions() from a discovery rule-set program."""
    shared_candidates = [
        program_path.resolve().parent.parent.parent / "_shared",
        program_path.resolve().parent.parent / "_shared",
    ]
    for shared_dir in shared_candidates:
        if shared_dir.is_dir():
            shared_str = str(shared_dir)
            import sys

            if shared_str not in sys.path:
                sys.path.insert(0, shared_str)
            break

    spec = importlib.util.spec_from_file_location("pro_rule_program", str(program_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load rule program: {program_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "get_rule_functions"):
        catalog = getattr(module, "RULE_CATALOG", None)
        if isinstance(catalog, list) and catalog:
            rules = []
            names = []
            for entry in catalog:
                fn = None
                name = ""
                if isinstance(entry, (tuple, list)):
                    if len(entry) >= 3 and callable(entry[2]):
                        name, fn = str(entry[0]), entry[2]
                    elif len(entry) >= 2 and callable(entry[1]):
                        name, fn = str(entry[0]), entry[1]
                    elif len(entry) >= 1:
                        name = str(entry[0])
                if fn is not None:
                    rules.append(fn)
                    names.append(name or getattr(fn, "__name__", f"rule_{len(rules) - 1}"))
            if rules:
                return rules, names
        raise AttributeError(f"{program_path} must define get_rule_functions()")
    rules = module.get_rule_functions()
    if not isinstance(rules, list) or not rules:
        raise ValueError(f"{program_path}: get_rule_functions() returned empty list")

    names: List[str] = []
    catalog = getattr(module, "RULE_CATALOG", None)
    if isinstance(catalog, list) and len(catalog) == len(rules):
        for entry in catalog:
            if isinstance(entry, (tuple, list)) and entry:
                names.append(str(entry[0]))
            else:
                names.append("")
    if not names or any(not n for n in names):
        names = [getattr(fn, "__name__", f"rule_{i}") for i, fn in enumerate(rules)]
    return rules, names


def align_rule_functions_by_name(
    rules: Sequence[RuleSpec],
    rule_fns: Sequence[RuleFn],
    rule_names: Sequence[str],
) -> Tuple[List[RuleFn | None], List[str], List[str]]:
    """Map discovery RuleSpec order to rule functions by name (not list index)."""
    lookup: dict[str, RuleFn] = {}
    for name, fn in zip(rule_names, rule_fns):
        if name:
            lookup[name] = fn
        fn_name = getattr(fn, "__name__", "")
        if fn_name:
            lookup[fn_name] = fn

    aligned_fns: List[RuleFn | None] = []
    warnings: List[str] = []
    for rule in rules:
        fn = lookup.get(rule.name)
        if fn is None and rule.index < len(rule_fns):
            fn = rule_fns[rule.index]
            warnings.append(f"Rule `{rule.name}` resolved by index fallback (name mismatch)")
        if fn is None:
            warnings.append(f"No rule function for `{rule.name}`")
        aligned_fns.append(fn)
    return aligned_fns, [r.name for r in rules], warnings


def _truncate_code(code: str, max_lines: int) -> str:
    lines = code.splitlines()
    if len(lines) <= max_lines:
        return code.strip()
    head = max_lines - 2
    return "\n".join(lines[:head] + ["    # ... truncated ..."] + lines[-1:]).strip()


def _load_archive_attempts(archive_dir: Path) -> List[Tuple[str, str, float]]:
    rows: List[Tuple[str, str, float]] = []
    for attempt_dir in sorted(archive_dir.glob("attempt_*")):
        code_path = attempt_dir / "code.py"
        result_path = attempt_dir / "result.json"
        if not code_path.is_file() or not result_path.is_file():
            continue
        with open(result_path, encoding="utf-8") as f:
            result = json.load(f)
        if not result.get("is_valid", True):
            continue
        score = result.get("score")
        if score is None:
            continue
        code = code_path.read_text(encoding="utf-8")
        rows.append((attempt_dir.name, code, float(score)))
    return rows


def _evaluate_rules_on_code(
    rules: Sequence[RuleFn],
    code: str,
) -> List[Tuple[int, str]]:
    out: List[Tuple[int, str]] = []
    for rule in rules:
        try:
            binary, explanation = rule(code)
            out.append((int(bool(binary)), str(explanation)))
        except Exception as exc:
            out.append((0, f"rule error: {exc}"))
    return out


def _rule_is_positive(rules: Sequence[RuleSpec], idx: int) -> bool:
    if idx >= len(rules):
        return False
    effect = rules[idx].score_effect
    return effect != "negative"


def _rule_is_negative(rules: Sequence[RuleSpec], idx: int) -> bool:
    return idx < len(rules) and rules[idx].score_effect == "negative"


def _satisfied_indices(matches: Sequence[Tuple[int, str]]) -> List[int]:
    return [i for i, (bit, _expl) in enumerate(matches) if bit == 1]


def _analyze_baseline_gaps(
    rules: Sequence[RuleSpec],
    rule_names: Sequence[str],
    baseline_matches: Sequence[Tuple[int, str]],
) -> BaselineGapAnalysis:
    satisfied_pos: List[str] = []
    satisfied_neg: List[str] = []
    missing_pos: List[str] = []
    missing_desc: List[str] = []

    for i, rule in enumerate(rules):
        bit = baseline_matches[i][0] if i < len(baseline_matches) else 0
        name = rule_names[i] if i < len(rule_names) else rule.name
        if bit == 1:
            if _rule_is_negative(rules, i):
                satisfied_neg.append(name)
            else:
                satisfied_pos.append(name)
        elif _rule_is_positive(rules, i):
            missing_pos.append(name)
            missing_desc.append(f"{name}: {rule.description}")

    return BaselineGapAnalysis(
        satisfied_positive=satisfied_pos,
        satisfied_negative=satisfied_neg,
        missing_positive=missing_pos,
        missing_positive_descriptions=missing_desc,
    )


def _exemplar_rank_key(
    row: Tuple[str, str, float, List[Tuple[int, str]]],
    *,
    rule_idx: int,
    baseline_id: str | None,
    missing_positive: set[int],
) -> Tuple[float, int, float]:
    attempt_id, _code, score, matches = row
    if baseline_id and attempt_id == baseline_id:
        return (-1.0, 0, score)
    extra_missing = sum(
        1 for i in missing_positive if i != rule_idx and i < len(matches) and matches[i][0] == 1
    )
    return (score, extra_missing, score)


def _compute_cooccurrence(
    scored_rows: Sequence[Tuple[str, str, float, List[Tuple[int, str]]]],
    rules: Sequence[RuleSpec],
    rule_names: Sequence[str],
    *,
    top_n: int,
    min_rules_in_combo: int,
    max_rules_in_combo: int,
    maximize: bool,
    score_pool_size: int = 15,
) -> List[RuleCooccurrence]:
    pool = sorted(scored_rows, key=lambda r: r[2], reverse=maximize)[:score_pool_size]
    combo_stats: dict[tuple[str, ...], List[Tuple[str, float]]] = {}

    for attempt_id, _code, score, matches in pool:
        pos_names = [
            rule_names[i]
            for i in _satisfied_indices(matches)
            if _rule_is_positive(rules, i) and i < len(rule_names)
        ]
        if len(pos_names) < min_rules_in_combo:
            continue
        pos_names = sorted(set(pos_names))
        for size in range(min_rules_in_combo, min(max_rules_in_combo, len(pos_names)) + 1):
            for start in range(len(pos_names) - size + 1):
                combo = tuple(pos_names[start : start + size])
                combo_stats.setdefault(combo, []).append((attempt_id, score))

    ranked: List[RuleCooccurrence] = []
    for combo, entries in combo_stats.items():
        best_attempt, best_score = max(entries, key=lambda e: e[1]) if maximize else min(entries, key=lambda e: e[1])
        avg = sum(s for _, s in entries) / len(entries)
        ranked.append(
            RuleCooccurrence(
                rule_names=list(combo),
                attempt_count=len(entries),
                best_score=best_score,
                best_attempt_id=best_attempt,
                avg_score=avg,
            )
        )
    ranked.sort(key=lambda c: (c.best_score, c.attempt_count), reverse=maximize)
    return ranked[:top_n]


def _compute_synthesis_seeds(
    scored_rows: Sequence[Tuple[str, str, float, List[Tuple[int, str]]]],
    rules: Sequence[RuleSpec],
    rule_names: Sequence[str],
    baseline_gaps: BaselineGapAnalysis,
    *,
    seed_count: int,
    max_code_lines: int,
    baseline_id: str | None,
    maximize: bool,
) -> List[SynthesisSeed]:
    missing_set = set(baseline_gaps.missing_positive)
    seeds: List[SynthesisSeed] = []

    for attempt_id, code, score, matches in scored_rows:
        if baseline_id and attempt_id == baseline_id:
            continue
        added = [
            rule_names[i]
            for i in _satisfied_indices(matches)
            if i < len(rule_names) and rule_names[i] in missing_set
        ]
        if not added:
            continue
        seeds.append(
            SynthesisSeed(
                attempt_id=attempt_id,
                score=score,
                added_positive_rules=sorted(set(added)),
                satisfied_rule_names=[
                    rule_names[i] for i in _satisfied_indices(matches) if i < len(rule_names)
                ],
                code_excerpt=_truncate_code(code, max_code_lines),
            )
        )

    seeds.sort(key=lambda s: s.score, reverse=maximize)
    return seeds[:seed_count]


def build_pro_injection_context(
    archive_dir: Path,
    rules: List[RuleSpec],
    rule_fns: Sequence[RuleFn],
    rule_names: Sequence[str],
    *,
    exemplars_per_rule: int = 2,
    top_k: int = 10,
    max_code_lines: int = 35,
    maximize: bool = True,
    best_attempt_id: str | None = None,
    best_score: float | None = None,
    exclude_baseline_from_exemplars: bool = True,
    cooccurrence_top_n: int = 5,
    cooccurrence_min_rules: int = 2,
    cooccurrence_max_rules: int = 3,
    synthesis_seed_count: int = 3,
) -> ProInjectionContext:
    attempts = _load_archive_attempts(archive_dir)
    if not attempts:
        raise ValueError(f"No valid attempts in {archive_dir}")

    scored_rows: List[Tuple[str, str, float, List[Tuple[int, str]]]] = []
    for attempt_id, code, score in attempts:
        matches = _evaluate_rules_on_code(rule_fns, code)
        scored_rows.append((attempt_id, code, score, matches))

    ctx = ProInjectionContext(
        rules=rules,
        baseline_attempt_id=best_attempt_id or "none",
        baseline_score=best_score,
    )

    baseline_matches: List[Tuple[int, str]] = []
    if best_attempt_id:
        baseline_row = next((r for r in scored_rows if r[0] == best_attempt_id), None)
        if baseline_row:
            baseline_matches = baseline_row[3]
    if not baseline_matches and best_attempt_id:
        for attempt_id, code, _score, _m in scored_rows:
            if attempt_id == best_attempt_id:
                baseline_matches = _evaluate_rules_on_code(rule_fns, code)
                break

    baseline_gaps = _analyze_baseline_gaps(rules, rule_names, baseline_matches)
    ctx.baseline_gaps = baseline_gaps
    missing_positive_indices = {
        i for i, name in enumerate(rule_names) if name in set(baseline_gaps.missing_positive)
    }

    ctx.rule_cooccurrence = _compute_cooccurrence(
        scored_rows,
        rules,
        rule_names,
        top_n=cooccurrence_top_n,
        min_rules_in_combo=cooccurrence_min_rules,
        max_rules_in_combo=cooccurrence_max_rules,
        maximize=maximize,
    )
    ctx.synthesis_seeds = _compute_synthesis_seeds(
        scored_rows,
        rules,
        rule_names,
        baseline_gaps,
        seed_count=synthesis_seed_count,
        max_code_lines=max_code_lines,
        baseline_id=best_attempt_id if exclude_baseline_from_exemplars else None,
        maximize=maximize,
    )

    for rule_idx in range(len(rules)):
        if _rule_is_negative(rules, rule_idx):
            ctx.rule_exemplars[rule_idx] = []
            continue

        matching = [
            row
            for row in scored_rows
            if row[3][rule_idx][0] == 1
            and (not exclude_baseline_from_exemplars or row[0] != best_attempt_id)
        ]
        matching.sort(
            key=lambda row: _exemplar_rank_key(
                row,
                rule_idx=rule_idx,
                baseline_id=best_attempt_id,
                missing_positive=missing_positive_indices,
            ),
            reverse=maximize,
        )
        exemplars: List[RuleExemplar] = []
        for attempt_id, code, score, matches in matching[:exemplars_per_rule]:
            exemplars.append(
                RuleExemplar(
                    attempt_id=attempt_id,
                    score=score,
                    code_excerpt=_truncate_code(code, max_code_lines),
                    rule_explanation=matches[rule_idx][1],
                )
            )
        ctx.rule_exemplars[rule_idx] = exemplars

    top_sorted = sorted(scored_rows, key=lambda row: row[2], reverse=maximize)[:top_k]
    for attempt_id, code, score, matches in top_sorted:
        satisfied_indices = [i for i, (bit, _expl) in enumerate(matches) if bit == 1]
        satisfied_names = [rule_names[i] for i in satisfied_indices if i < len(rule_names)]
        ctx.top_k_coverage.append(
            TopKAttemptCoverage(
                attempt_id=attempt_id,
                score=score,
                satisfied_rule_indices=satisfied_indices,
                satisfied_rule_names=satisfied_names,
                code_excerpt=_truncate_code(code, max_code_lines),
            )
        )

    return ctx


def resolve_rule_program_path(
    *,
    explicit: Path | None,
    workspace_dir: Path,
    cycle: int,
    discovery_project: str | None = None,
    fallback_task_dir: Path | None = None,
) -> Path:
    if explicit is not None:
        path = explicit.resolve()
        if not path.is_file():
            raise FileNotFoundError(f"pro_rule_program not found: {path}")
        return path

    artifact = workspace_dir / "alpha-diagnosis" / f"discovery_cycle_{cycle:02d}.json"
    if artifact.is_file():
        data = json.loads(artifact.read_text(encoding="utf-8"))
        project = discovery_project or data.get("project_name")
        best_id = data.get("best_attempt_id")
        if project and best_id:
            candidate = (
                workspace_dir
                / "alpha-diagnosis"
                / "discovery_configs"
                / f"cycle_{cycle:02d}"
                / "outputs"
                / project
                / "archive"
                / best_id
                / "code.py"
            )
            if candidate.is_file():
                return candidate

    persisted = workspace_dir / "alpha-diagnosis" / "rule_programs" / f"cycle_{cycle:02d}.py"
    if persisted.is_file():
        return persisted

    workspace_rules = workspace_dir / f"_rules_c{cycle}.py"
    if workspace_rules.is_file():
        return workspace_rules.resolve()

    if fallback_task_dir is not None:
        initial = fallback_task_dir / "initial_program.py"
        if initial.is_file():
            return initial.resolve()

    raise FileNotFoundError(
        "Cannot resolve rule program: set injection.pro_rule_program / cf_rule_program "
        f"or provide --rules-program (looked for {artifact})"
    )
