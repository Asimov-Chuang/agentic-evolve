"""Shared mechanism discovery evaluator logic."""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import pickle
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Sequence, Tuple

import numpy as np

_shared_dir = Path(__file__).resolve().parent
if str(_shared_dir) not in sys.path:
    sys.path.insert(0, str(_shared_dir))

from mechanism_types import DEFAULT_MECHANISM_CONFIG, MechanismLink, merged_mechanism_config

DEFAULT_PROGRAM_TIMEOUT_SECONDS = 600
CACHE_FILENAME = "mechanism_dataset_cache.pkl"

FORBIDDEN_TRACE_STEP_KEYS = frozenset({"common", "rewards", "diagnostics"})
FORBIDDEN_CODE_NAMES = frozenset(
    {
        "open",
        "exec",
        "eval",
        "compile",
        "__import__",
        "importlib",
        "subprocess",
        "pickle",
        "json",
        "raw-artifact",
        "raw_artifact",
    }
)


def _workspace_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def _load_meta(workspace: Path | None = None) -> dict:
    root = workspace or _workspace_dir()
    meta_path = root / "workspace_meta.json"
    if not meta_path.is_file():
        raise FileNotFoundError(
            f"Missing workspace_meta.json in {root}. "
            "Run agentic-evolve with source_archive and mechanism config."
        )
    with open(meta_path, encoding="utf-8") as f:
        return json.load(f)


def _evaluation_timeout_seconds(workspace: Path | None = None) -> int:
    meta = _load_meta(workspace)
    return int(meta.get("evaluation_timeout_seconds", DEFAULT_PROGRAM_TIMEOUT_SECONDS))


def _failure_result(message: str, *, metrics: dict | None = None) -> dict:
    return {
        "score": float("-inf"),
        "is_valid": False,
        "feedback": message,
        "metrics": metrics or {},
    }


def _predicate_name(fn: Callable) -> str:
    return getattr(fn, "__name__", "predicate")


def _static_description(fn: Callable, index: int, descriptions: List[str] | None) -> str:
    if descriptions is not None and index < len(descriptions):
        text = str(descriptions[index]).strip()
        if text:
            return text
    doc = (getattr(fn, "__doc__", None) or "").strip()
    if doc:
        return doc.split("\n")[0].strip()
    return _predicate_name(fn)


def _validate_code_predicate_body(func: ast.FunctionDef) -> str | None:
    for node in ast.walk(func):
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_CODE_NAMES:
            return f"Code predicate {func.name!r} must not reference {node.id!r}"
        if isinstance(node, ast.Call):
            call_name = None
            if isinstance(node.func, ast.Name):
                call_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                call_name = node.func.attr
            if call_name in {"open", "exec", "eval", "__import__"}:
                return f"Code predicate {func.name!r} must not call {call_name}()"
    return None


def _validate_trace_predicate_program(
    program_path: str,
    *,
    extra_forbidden: frozenset[str] | None = None,
) -> str | None:
    source = Path(program_path).read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return f"Syntax error in program: {exc}"

    forbidden = FORBIDDEN_TRACE_STEP_KEYS | (extra_forbidden or frozenset())
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in forbidden:
            return (
                f"Program must not reference forbidden field {node.id!r}. "
                "Trace predicates may use only policy-visible observations/actions."
            )
        if isinstance(node, ast.Constant) and node.value in forbidden:
            return (
                f"Program must not reference forbidden field {node.value!r}. "
                "Trace predicates may use only policy-visible observations/actions."
            )
    return None


def _ensure_shared_on_path(workspace: Path | None, program_path: str) -> None:
    candidates: List[Path] = []
    if workspace is not None:
        candidates.append(workspace / "_shared")
    prog_parent = Path(program_path).resolve().parent
    candidates.append(prog_parent.parent / "_shared")
    for shared_dir in candidates:
        if shared_dir.is_dir():
            shared_str = str(shared_dir)
            if shared_str not in sys.path:
                sys.path.insert(0, shared_str)
            return


def _load_mechanism_program(
    program_path: str,
    *,
    workspace: Path | None = None,
) -> Tuple[
    List[Callable[[str], Tuple[int, str]]],
    List[str],
    List[str],
    List[Callable[[Dict], Tuple[int, str]]],
    List[str],
    List[str],
    List[MechanismLink],
]:
    _ensure_shared_on_path(workspace, program_path)
    spec = importlib.util.spec_from_file_location("candidate_mechanism", program_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load program: {program_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    for attr, label in (
        ("get_code_predicates", "code predicates"),
        ("get_trace_predicates", "trace predicates"),
        ("get_mechanism_links", "mechanism links"),
    ):
        if not hasattr(module, attr):
            raise AttributeError(f"program must define {attr}()")

    code_preds = module.get_code_predicates()
    trace_preds = module.get_trace_predicates()
    links_raw = module.get_mechanism_links()
    if not isinstance(code_preds, list):
        raise TypeError("get_code_predicates() must return a list")
    if not isinstance(trace_preds, list):
        raise TypeError("get_trace_predicates() must return a list")
    if not isinstance(links_raw, list):
        raise TypeError("get_mechanism_links() must return a list")

    code_desc: List[str] | None = None
    if hasattr(module, "get_code_predicate_descriptions"):
        raw = module.get_code_predicate_descriptions()
        if not isinstance(raw, list):
            raise TypeError("get_code_predicate_descriptions() must return a list")
        code_desc = [str(x).strip() for x in raw]
        if len(code_desc) != len(code_preds):
            raise ValueError("get_code_predicate_descriptions() length mismatch")

    trace_desc: List[str] | None = None
    if hasattr(module, "get_trace_predicate_descriptions"):
        raw = module.get_trace_predicate_descriptions()
        if not isinstance(raw, list):
            raise TypeError("get_trace_predicate_descriptions() must return a list")
        trace_desc = [str(x).strip() for x in raw]
        if len(trace_desc) != len(trace_preds):
            raise ValueError("get_trace_predicate_descriptions() length mismatch")

    code_names = [_predicate_name(fn) for fn in code_preds]
    trace_names = [_predicate_name(fn) for fn in trace_preds]
    code_descriptions = [
        _static_description(fn, i, code_desc) for i, fn in enumerate(code_preds)
    ]
    trace_descriptions = [
        _static_description(fn, i, trace_desc) for i, fn in enumerate(trace_preds)
    ]

    links: List[MechanismLink] = []
    for idx, item in enumerate(links_raw):
        try:
            link = MechanismLink.from_mapping(item)
        except (KeyError, TypeError) as exc:
            raise ValueError(f"link[{idx}] invalid: {exc}") from exc
        err = link.validate_schema()
        if err:
            raise ValueError(f"link[{idx}] {err}")
        links.append(link)

    return (
        code_preds,
        code_names,
        code_descriptions,
        trace_preds,
        trace_names,
        trace_descriptions,
        links,
    )


def _extract_metrics(result: dict[str, Any], metric_nodes: Sequence[str]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    flat_metrics = result.get("metrics") or {}
    if result.get("score") is not None:
        out["score"] = float(result["score"])
    for key in ("mean_slew", "mean_rms", "mean_strehl", "score_0_to_1_higher_is_better"):
        if key in flat_metrics:
            out[key if key != "score_0_to_1_higher_is_better" else "score"] = float(
                flat_metrics[key]
            )
    construction = result.get("construction") or {}
    baseline = construction.get("baseline") or {}
    utility = baseline.get("utility_breakdown") or {}
    for key, value in utility.items():
        out[str(key)] = float(value)
    for key in metric_nodes:
        if key in flat_metrics and key not in out:
            out[key] = float(flat_metrics[key])
    return out


def _load_dataset_cache(
    dataset_dir: Path,
    cache_path: Path,
    strip_fn: Callable[[Dict[str, Any]], Dict[str, Any]],
    metric_nodes: Sequence[str],
) -> List[Tuple[str, str, Dict[str, Any], Dict[str, float]]]:
    if cache_path.is_file():
        with open(cache_path, "rb") as f:
            cached = pickle.load(f)
        if isinstance(cached, list) and cached:
            return cached

    samples: List[Tuple[str, str, Dict[str, Any], Dict[str, float]]] = []
    for attempt_dir in sorted(dataset_dir.glob("attempt_*")):
        raw_path = attempt_dir / "raw-artifact.json"
        code_path = attempt_dir / "code.py"
        result_path = attempt_dir / "result.json"
        if not raw_path.is_file() or not code_path.is_file() or not result_path.is_file():
            continue
        with open(result_path, encoding="utf-8") as f:
            result = json.load(f)
        if result.get("score") is None:
            continue
        with open(raw_path, encoding="utf-8") as f:
            raw = strip_fn(json.load(f))
        code_text = code_path.read_text(encoding="utf-8")
        metrics = _extract_metrics(result, metric_nodes)
        samples.append((attempt_dir.name, code_text, raw, metrics))

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "wb") as f:
        pickle.dump(samples, f)
    return samples


def _apply_binary_predicates(
    preds: Sequence[Callable],
    values: Sequence[Any],
) -> Tuple[np.ndarray, List[str]]:
    rows: List[List[int]] = []
    errors: List[str] = []
    for idx_value, value in enumerate(values):
        row: List[int] = []
        for pidx, pred in enumerate(preds):
            try:
                out = pred(value)
            except Exception as exc:
                errors.append(f"sample {idx_value} predicate {pidx}: {exc}")
                row.append(0)
                continue
            if not isinstance(out, (tuple, list)) or len(out) != 2:
                errors.append(f"sample {idx_value} predicate {pidx}: must return (binary, explanation)")
                row.append(0)
                continue
            binary = out[0]
            if binary not in (0, 1, True, False):
                errors.append(
                    f"sample {idx_value} predicate {pidx}: binary must be 0 or 1, got {binary!r}"
                )
                row.append(0)
                continue
            row.append(int(bool(binary)))
        rows.append(row)
    if errors:
        raise ValueError("; ".join(errors[:5]) + (f" (+{len(errors) - 5} more)" if len(errors) > 5 else ""))
    if not rows:
        return np.zeros((0, len(preds)), dtype=float), errors
    return np.array(rows, dtype=float), errors


def _binary_delta(source: np.ndarray, target: np.ndarray) -> Tuple[float, int, int]:
    s1 = source == 1
    s0 = source == 0
    n1 = int(s1.sum())
    n0 = int(s0.sum())
    p1 = float(target[s1].mean()) if n1 else 0.0
    p0 = float(target[s0].mean()) if n0 else 0.0
    return p1 - p0, n1, n0


def _metric_delta(source: np.ndarray, metric_values: np.ndarray) -> Tuple[float, int, int]:
    s1 = source == 1
    s0 = source == 0
    n1 = int(s1.sum())
    n0 = int(s0.sum())
    m1 = float(metric_values[s1].mean()) if n1 else 0.0
    m0 = float(metric_values[s0].mean()) if n0 else 0.0
    return m1 - m0, n1, n0


def _direction_matches(effect: str, delta: float, threshold: float) -> Tuple[bool, float]:
    if effect == "increase":
        if delta >= threshold:
            return True, min(1.0, delta / max(threshold, 1e-9))
        if delta <= -threshold:
            return False, -min(1.0, abs(delta) / max(threshold, 1e-9))
        return False, 0.0
    if delta <= -threshold:
        return True, min(1.0, abs(delta) / max(threshold, 1e-9))
    if delta >= threshold:
        return False, -min(1.0, delta / max(threshold, 1e-9))
    return False, 0.0


def _score_link(
    link: MechanismLink,
    *,
    code_matrix: np.ndarray,
    code_name_to_idx: Dict[str, int],
    trace_matrix: np.ndarray,
    trace_name_to_idx: Dict[str, int],
    metrics_by_name: Dict[str, np.ndarray],
    cfg: dict[str, Any],
) -> Dict[str, Any]:
    min_support = int(cfg["min_support"])
    threshold = float(cfg["effect_threshold"])
    threshold_metric = float(cfg["effect_threshold_metric"])
    wrong_penalty = float(cfg["wrong_direction_penalty"])

    if link.source_kind == "code":
        if link.source_id not in code_name_to_idx:
            return {"scored": False, "reason": f"unknown code predicate {link.source_id!r}"}
        source = code_matrix[:, code_name_to_idx[link.source_id]]
    else:
        if link.source_id not in trace_name_to_idx:
            return {"scored": False, "reason": f"unknown trace predicate {link.source_id!r}"}
        source = trace_matrix[:, trace_name_to_idx[link.source_id]]

    if link.target_kind == "trace":
        if link.target_id not in trace_name_to_idx:
            return {"scored": False, "reason": f"unknown trace target {link.target_id!r}"}
        target = trace_matrix[:, trace_name_to_idx[link.target_id]]
        delta, n1, n0 = _binary_delta(source, target)
        thr = threshold
    else:
        if link.target_id not in metrics_by_name:
            return {"scored": False, "reason": f"unknown metric {link.target_id!r}"}
        metric_values = metrics_by_name[link.target_id]
        delta, n1, n0 = _metric_delta(source, metric_values)
        std = float(np.std(metric_values))
        delta_norm = delta / (std + 1e-9)
        thr = threshold_metric
        delta = delta_norm

    if n1 < min_support or n0 < min_support:
        return {
            "scored": False,
            "reason": f"insufficient support (n1={n1}, n0={n0}, need>={min_support})",
            "delta": delta,
            "n1": n1,
            "n0": n0,
        }

    ok, magnitude = _direction_matches(link.effect, delta, thr)
    if ok:
        link_score = magnitude
    elif magnitude < 0:
        link_score = -wrong_penalty * abs(magnitude)
    else:
        link_score = 0.0

    return {
        "scored": True,
        "link_score": float(link_score),
        "delta": float(delta),
        "n1": n1,
        "n0": n0,
        "direction_ok": ok,
    }


def _path_coherence(
    links: Sequence[MechanismLink],
    link_results: Sequence[Dict[str, Any]],
    *,
    code_names: Sequence[str],
    trace_names: Sequence[str],
    metric_nodes: Sequence[str],
) -> Tuple[float, List[Dict[str, Any]], int]:
    link_key_to_result = {}
    for link, result in zip(links, link_results):
        key = (link.source_kind, link.source_id, link.target_kind, link.target_id)
        link_key_to_result[key] = result

    code_to_trace = {
        (link.source_id, link.target_id): link
        for link in links
        if link.source_kind == "code" and link.target_kind == "trace"
    }
    trace_to_metric = {
        (link.source_id, link.target_id): link
        for link in links
        if link.source_kind == "trace" and link.target_kind == "metric"
    }

    paths: List[Dict[str, Any]] = []
    for (code_id, trace_id), _ in code_to_trace.items():
        for (trace_id2, metric_id), _ in trace_to_metric.items():
            if trace_id2 != trace_id:
                continue
            if metric_id not in metric_nodes:
                continue
            r1 = link_key_to_result.get(("code", code_id, "trace", trace_id))
            r2 = link_key_to_result.get(("trace", trace_id, "metric", metric_id))
            if not r1 or not r2 or not r1.get("scored") or not r2.get("scored"):
                paths.append(
                    {
                        "code_id": code_id,
                        "trace_id": trace_id,
                        "metric_id": metric_id,
                        "coherent": False,
                        "reason": "missing or unscored link",
                    }
                )
                continue
            coherent = float(r1.get("link_score", 0)) >= 0.5 and float(r2.get("link_score", 0)) >= 0.5
            paths.append(
                {
                    "code_id": code_id,
                    "trace_id": trace_id,
                    "metric_id": metric_id,
                    "coherent": coherent,
                    "link1_score": r1.get("link_score"),
                    "link2_score": r2.get("link_score"),
                }
            )

    if not paths:
        return 0.0, paths, 0
    coherent_count = sum(1 for p in paths if p.get("coherent"))
    return coherent_count / len(paths), paths, len(paths)


def _predictive_r2(
    code_matrix: np.ndarray,
    trace_matrix: np.ndarray,
    scores: np.ndarray,
) -> Tuple[float, float]:
    if code_matrix.size == 0 and trace_matrix.size == 0:
        return 0.0, float("inf")
    X = np.column_stack([m for m in (code_matrix, trace_matrix) if m.size])
    n, k = X.shape
    if n < k + 1:
        return 0.0, float("inf")
    design = np.column_stack([np.ones(n), X])
    coef, _, _, _ = np.linalg.lstsq(design, scores, rcond=None)
    y_pred = design @ coef
    mse = float(np.mean((scores - y_pred) ** 2))
    ss_res = float(np.sum((scores - y_pred) ** 2))
    ss_tot = float(np.sum((scores - np.mean(scores)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
    return float(r2), mse


def _degeneracy_penalty(
    matrix: np.ndarray,
    names: Sequence[str],
    *,
    low: float,
    high: float,
    penalty: float,
) -> Tuple[float, List[str]]:
    if matrix.size == 0:
        return 0.0, []
    rates = matrix.mean(axis=0)
    flagged: List[str] = []
    total = 0.0
    for name, rate in zip(names, rates):
        if rate < low or rate > high:
            flagged.append(f"{name} (rate={rate:.2f})")
            total += penalty
    return total, flagged


def evaluate_core(
    program_path: str,
    output_dir: str,
    workspace: Path,
    *,
    strip_fn: Callable[[Dict[str, Any]], Dict[str, Any]] | None = None,
    extra_forbidden: frozenset[str] | None = None,
) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    if strip_fn is None:
        return _failure_result("strip_fn is required for mechanism discovery")

    meta = _load_meta(workspace)
    cfg = merged_mechanism_config(meta)
    metric_nodes = [str(x) for x in cfg.get("metric_nodes") or DEFAULT_MECHANISM_CONFIG["metric_nodes"]]

    dataset_dir_raw = meta.get("dataset_dir")
    if not dataset_dir_raw:
        return _failure_result("workspace_meta.json missing dataset_dir (set source_archive in config)")
    dataset_dir = Path(dataset_dir_raw)
    if not dataset_dir.is_dir():
        return _failure_result(f"dataset_dir not found: {dataset_dir}")

    forbidden_err = _validate_trace_predicate_program(
        program_path, extra_forbidden=extra_forbidden
    )
    if forbidden_err:
        return _failure_result(forbidden_err)

    source = Path(program_path).read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return _failure_result(f"Syntax error in program: {exc}")
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("code_"):
            err = _validate_code_predicate_body(node)
            if err:
                return _failure_result(err)

    try:
        (
            code_preds,
            code_names,
            code_descriptions,
            trace_preds,
            trace_names,
            trace_descriptions,
            links,
        ) = _load_mechanism_program(program_path, workspace=workspace)
    except Exception as exc:
        return _failure_result(f"Failed to load mechanism program: {exc}")

    max_code = int(cfg["max_code_predicates"])
    max_trace = int(cfg["max_trace_predicates"])
    max_links = int(cfg["max_links"])
    if len(code_preds) > max_code:
        return _failure_result(f"Too many code predicates ({len(code_preds)} > {max_code})")
    if len(trace_preds) > max_trace:
        return _failure_result(f"Too many trace predicates ({len(trace_preds)} > {max_trace})")
    if len(links) > max_links:
        return _failure_result(f"Too many links ({len(links)} > {max_links})")

    name_sets = {
        "code": set(code_names),
        "trace": set(trace_names),
        "metric": set(metric_nodes),
    }
    for idx, link in enumerate(links):
        if link.source_id not in name_sets[link.source_kind]:
            return _failure_result(f"link[{idx}] unknown source_id {link.source_id!r}")
        if link.target_kind == "trace" and link.target_id not in name_sets["trace"]:
            return _failure_result(f"link[{idx}] unknown trace target {link.target_id!r}")
        if link.target_kind == "metric" and link.target_id not in name_sets["metric"]:
            return _failure_result(f"link[{idx}] unknown metric target {link.target_id!r}")

    cache_path = workspace / "archive" / "_dataset_cache" / CACHE_FILENAME
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        samples = _load_dataset_cache(dataset_dir, cache_path, strip_fn, metric_nodes)
    except Exception as exc:
        return _failure_result(f"Failed to load dataset: {exc}")

    if not samples:
        return _failure_result(
            "No samples with code.py, raw-artifact.json, and result.json score found"
        )

    codes = [s[1] for s in samples]
    raws = [s[2] for s in samples]
    attempt_ids = [s[0] for s in samples]

    try:
        code_matrix, _ = _apply_binary_predicates(code_preds, codes)
        trace_matrix, _ = _apply_binary_predicates(trace_preds, raws)
    except ValueError as exc:
        return _failure_result(f"Predicate execution failed: {exc}")

    metrics_by_name: Dict[str, np.ndarray] = {}
    for key in metric_nodes:
        metrics_by_name[key] = np.array(
            [sample_metrics.get(key, float("nan")) for _aid, _c, _r, sample_metrics in samples],
            dtype=float,
        )
    scores = metrics_by_name.get("score")
    if scores is None or np.isnan(scores).all():
        scores = np.array([float("nan")] * len(samples), dtype=float)

    code_name_to_idx = {name: i for i, name in enumerate(code_names)}
    trace_name_to_idx = {name: i for i, name in enumerate(trace_names)}

    link_results: List[Dict[str, Any]] = []
    scored_link_scores: List[float] = []
    for link in links:
        result = _score_link(
            link,
            code_matrix=code_matrix,
            code_name_to_idx=code_name_to_idx,
            trace_matrix=trace_matrix,
            trace_name_to_idx=trace_name_to_idx,
            metrics_by_name=metrics_by_name,
            cfg=cfg,
        )
        link_results.append(
            {
                "source_kind": link.source_kind,
                "source_id": link.source_id,
                "target_kind": link.target_kind,
                "target_id": link.target_id,
                "effect": link.effect,
                "rationale": link.rationale,
                **result,
            }
        )
        if result.get("scored"):
            scored_link_scores.append(float(result["link_score"]))

    link_consistency = (
        float(np.mean(scored_link_scores)) if scored_link_scores else 0.0
    )
    path_coherence, path_details, path_count = _path_coherence(
        links,
        link_results,
        code_names=code_names,
        trace_names=trace_names,
        metric_nodes=metric_nodes,
    )

    enable_predictive = bool(cfg.get("enable_predictive_r2", False))
    predictive_r2 = 0.0
    predictive_mse = float("nan")
    if enable_predictive and not np.isnan(scores).all():
        valid = ~np.isnan(scores)
        if int(valid.sum()) >= 2:
            predictive_r2, predictive_mse = _predictive_r2(
                code_matrix[valid],
                trace_matrix[valid],
                scores[valid],
            )

    penalty = 0.0
    degenerate_notes: List[str] = []
    for matrix, names, label in (
        (code_matrix, code_names, "code"),
        (trace_matrix, trace_names, "trace"),
    ):
        p, flagged = _degeneracy_penalty(
            matrix,
            names,
            low=float(cfg["degenerate_rate_low"]),
            high=float(cfg["degenerate_rate_high"]),
            penalty=float(cfg["degenerate_penalty"]),
        )
        penalty += p
        degenerate_notes.extend(f"{label}:{item}" for item in flagged)

    w_link = float(cfg["link_consistency_weight"])
    w_path = float(cfg["path_coherence_weight"])
    w_pred = float(cfg["predictive_r2_weight"])
    if enable_predictive:
        weight_sum = w_link + w_path + w_pred
        if weight_sum <= 0:
            w_link, w_path, w_pred = 0.625, 0.375, 0.25
            weight_sum = 1.25
        w_link /= weight_sum
        w_path /= weight_sum
        w_pred /= weight_sum
        score = (
            w_link * link_consistency
            + w_path * path_coherence
            + w_pred * max(0.0, predictive_r2)
            - penalty
        )
    else:
        weight_sum = w_link + w_path
        if weight_sum <= 0:
            w_link, w_path = 0.625, 0.375
            weight_sum = 1.0
        w_link /= weight_sum
        w_path /= weight_sum
        score = w_link * link_consistency + w_path * path_coherence - penalty

    metrics: Dict[str, Any] = {
        "link_consistency": link_consistency,
        "path_coherence": path_coherence,
        "path_count": path_count,
        "n_samples": len(samples),
        "n_links": len(links),
        "n_scored_links": len(scored_link_scores),
        "n_code_predicates": len(code_preds),
        "n_trace_predicates": len(trace_preds),
        "penalty": penalty,
        "enable_predictive_r2": enable_predictive,
        "predictive_r2": predictive_r2 if enable_predictive else None,
        "predictive_mse": predictive_mse if enable_predictive else None,
        "code_predicate_names": code_names,
        "trace_predicate_names": trace_names,
    }

    feedback_lines = [
        f"score={score:.4f}",
        f"link_consistency={link_consistency:.4f} ({len(scored_link_scores)}/{len(links)} scored links)",
        f"path_coherence={path_coherence:.4f} ({path_count} paths)",
    ]
    if enable_predictive:
        feedback_lines.append(f"predictive_r2={predictive_r2:.4f}")
    if penalty > 0:
        feedback_lines.append(f"penalty={penalty:.4f}")
    if degenerate_notes:
        feedback_lines.append("Degenerate predicates: " + ", ".join(degenerate_notes[:5]))

    feedback_lines.append("Links:")
    for item in link_results:
        if not item.get("scored"):
            feedback_lines.append(
                f"  {item['source_kind']}:{item['source_id']} -> "
                f"{item['target_kind']}:{item['target_id']} "
                f"[{item['effect']}] SKIP ({item.get('reason', '?')})"
            )
        else:
            feedback_lines.append(
                f"  {item['source_kind']}:{item['source_id']} -> "
                f"{item['target_kind']}:{item['target_id']} "
                f"[{item['effect']}] score={item['link_score']:+.3f} delta={item['delta']:+.4f}"
            )

    if path_details:
        feedback_lines.append("Paths:")
        for path in path_details[:8]:
            mark = "OK" if path.get("coherent") else "FAIL"
            feedback_lines.append(
                f"  {path['code_id']} -> {path['trace_id']} -> {path['metric_id']} [{mark}]"
            )

    summary_path = Path(output_dir) / "mechanism_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "score": score,
                "link_consistency": link_consistency,
                "path_coherence": path_coherence,
                "predictive_r2": predictive_r2 if enable_predictive else None,
                "penalty": penalty,
                "n_samples": len(samples),
                "attempt_ids": attempt_ids,
                "links": link_results,
                "paths": path_details,
                "code_predicates": [
                    {"name": n, "description": d} for n, d in zip(code_names, code_descriptions)
                ],
                "trace_predicates": [
                    {"name": n, "description": d} for n, d in zip(trace_names, trace_descriptions)
                ],
            },
            f,
            indent=2,
        )

    return {
        "score": float(score),
        "is_valid": True,
        "feedback": "\n".join(feedback_lines),
        "metrics": metrics,
    }


def run_in_subprocess(
    program_path: str,
    output_dir: str,
    workspace: Path,
    evaluator_path: Path,
) -> dict:
    with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as tmp:
        result_file = tmp.name

    script = f"""
import importlib.util
import pickle
import traceback
from pathlib import Path

evaluator_path = {str(evaluator_path)!r}
program_path = {program_path!r}
output_dir = {output_dir!r}
workspace = Path({str(workspace)!r})
result_file = {result_file!r}

try:
    spec = importlib.util.spec_from_file_location("md_evaluator", evaluator_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module._evaluate_core(program_path, output_dir, workspace)
    with open(result_file, "wb") as f:
        pickle.dump({{"result": result}}, f)
except Exception:
    with open(result_file, "wb") as f:
        pickle.dump({{"error": traceback.format_exc()}}, f)
"""

    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8") as tmp_script:
        tmp_script.write(script)
        script_path = tmp_script.name

    try:
        completed = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=_evaluation_timeout_seconds(workspace),
        )
        with open(result_file, "rb") as f:
            payload = pickle.load(f)
        if "error" in payload:
            raise RuntimeError(payload["error"])
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr or "Evaluation subprocess failed")
        return payload["result"]
    finally:
        os.unlink(result_file)
        os.unlink(script_path)


# Re-export strip helpers from diagnostic-rule-discovery for task evaluators.
def _find_drd_evaluator_base() -> Path | None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "diagnostic-rule-discovery" / "_shared" / "evaluator_base.py"
        if candidate.is_file():
            return candidate
    return None


_drd_base_path = _find_drd_evaluator_base()
if _drd_base_path is not None:
    _spec = importlib.util.spec_from_file_location("drd_strip", _drd_base_path)
    if _spec and _spec.loader:
        _drd = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_drd)
        strip_policy_visible_sustaindc = _drd.strip_policy_visible_sustaindc
        strip_policy_visible_optics = _drd.strip_policy_visible_optics
        strip_policy_visible_general_meio = _drd.strip_policy_visible_general_meio
        strip_policy_visible_ev2gym = _drd.strip_policy_visible_ev2gym
        strip_policy_visible_pid_tuning = _drd.strip_policy_visible_pid_tuning
        strip_policy_visible_high_reliable_simulation = (
            _drd.strip_policy_visible_high_reliable_simulation
        )
        FORBIDDEN_OPTICS_ROOT_KEYS = _drd.FORBIDDEN_OPTICS_ROOT_KEYS
        FORBIDDEN_EV2GYM_ROOT_KEYS = _drd.FORBIDDEN_EV2GYM_ROOT_KEYS
else:
    strip_policy_visible_sustaindc = None  # type: ignore[assignment,misc]
    strip_policy_visible_optics = None  # type: ignore[assignment,misc]
    strip_policy_visible_general_meio = None  # type: ignore[assignment,misc]
    strip_policy_visible_ev2gym = None  # type: ignore[assignment,misc]
    strip_policy_visible_pid_tuning = None  # type: ignore[assignment,misc]
    strip_policy_visible_high_reliable_simulation = None  # type: ignore[assignment,misc]
    FORBIDDEN_OPTICS_ROOT_KEYS = frozenset()
    FORBIDDEN_EV2GYM_ROOT_KEYS = frozenset()
