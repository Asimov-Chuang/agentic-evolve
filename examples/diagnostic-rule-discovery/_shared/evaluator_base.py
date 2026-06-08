"""Shared diagnostic rule discovery evaluator logic."""

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
from typing import Any, Callable, Dict, List, Tuple

import numpy as np

DEFAULT_PROGRAM_TIMEOUT_SECONDS = 600
CACHE_FILENAME = "dataset_cache_policy_visible.pkl"
FORBIDDEN_STEP_KEYS = frozenset({"common", "rewards"})


def strip_policy_visible_sustaindc(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Remove simulator-internal fields; rules may only use observations + actions."""
    scenarios_out: List[Dict[str, Any]] = []
    for block in raw.get("scenarios", []):
        steps_out: List[Dict[str, Any]] = []
        for step in block.get("steps", []):
            steps_out.append(
                {
                    "step": step.get("step"),
                    "observations": dict(step.get("observations") or {}),
                    "actions": dict(step.get("actions") or {}),
                }
            )
        scenarios_out.append(
            {
                "scenario": block.get("scenario"),
                "steps": steps_out,
            }
        )
    return {"scenarios": scenarios_out}


def strip_policy_visible_general_meio(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Keep MEIO policy-visible fields: solution, network metadata, scenario aggregates, step obs."""
    scenarios_out: List[Dict[str, Any]] = []
    for block in raw.get("scenarios", []):
        steps_out: List[Dict[str, Any]] = []
        for step in block.get("steps", []):
            steps_out.append(
                {
                    "step": step.get("step"),
                    "observations": dict(step.get("observations") or {}),
                    "actions": dict(step.get("actions") or {}),
                }
            )
        scenarios_out.append(
            {
                "scenario": block.get("scenario"),
                "demand_scale": block.get("demand_scale"),
                "periods": block.get("periods"),
                "seed": block.get("seed"),
                "aggregate": dict(block.get("aggregate") or {}),
                "steps": steps_out,
            }
        )
    return {
        "solution_base_stock": dict(raw.get("solution_base_stock") or {}),
        "network": dict(raw.get("network") or {}),
        "scenarios": scenarios_out,
        "metrics": dict(raw.get("metrics") or {}),
        "final_score": raw.get("final_score"),
    }


def _workspace_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def _load_meta(workspace: Path | None = None) -> dict:
    root = workspace or _workspace_dir()
    meta_path = root / "workspace_meta.json"
    if not meta_path.is_file():
        raise FileNotFoundError(
            f"Missing workspace_meta.json in {root}. "
            "Run agentic-evolve with a config that sets source_archive and rule_set_size."
        )
    with open(meta_path, encoding="utf-8") as f:
        return json.load(f)


def _evaluation_timeout_seconds(workspace: Path | None = None) -> int:
    meta = _load_meta(workspace)
    return int(meta.get("evaluation_timeout_seconds", DEFAULT_PROGRAM_TIMEOUT_SECONDS))


def _validate_program_uses_policy_visible_only(program_path: str) -> str | None:
    source = Path(program_path).read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return f"Syntax error in program: {exc}"

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_STEP_KEYS:
            return (
                f"Program must not reference forbidden field {node.id!r}. "
                "Rules may use only observations and actions (policy-visible trace)."
            )
        if isinstance(node, ast.Constant) and node.value in FORBIDDEN_STEP_KEYS:
            return (
                f"Program must not reference forbidden field {node.value!r}. "
                "Rules may use only observations and actions (policy-visible trace)."
            )
    return None


def _failure_result(message: str, *, metrics: dict | None = None) -> dict:
    return {
        "score": float("-inf"),
        "is_valid": False,
        "feedback": message,
        "metrics": metrics or {},
    }


def _rule_name(fn: Callable) -> str:
    return getattr(fn, "__name__", "rule")


def _rule_static_description(fn: Callable, index: int, descriptions: List[str] | None) -> str:
    if descriptions is not None and index < len(descriptions):
        text = str(descriptions[index]).strip()
        if text:
            return text
    doc = (getattr(fn, "__doc__", None) or "").strip()
    if doc:
        return doc.split("\n")[0].strip()
    return _rule_name(fn)


def _load_rules_and_descriptions(
    program_path: str,
) -> Tuple[List[Callable[[Dict], Tuple[int, str]]], List[str], List[str]]:
    spec = importlib.util.spec_from_file_location("candidate_rules", program_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load program: {program_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "get_rule_functions"):
        raise AttributeError("program must define get_rule_functions()")
    rules = module.get_rule_functions()
    if not isinstance(rules, list):
        raise TypeError("get_rule_functions() must return a list")

    descriptions: List[str] | None = None
    if hasattr(module, "get_rule_descriptions"):
        raw_desc = module.get_rule_descriptions()
        if not isinstance(raw_desc, list):
            raise TypeError("get_rule_descriptions() must return a list of strings")
        descriptions = [str(d).strip() for d in raw_desc]
        if len(descriptions) != len(rules):
            raise ValueError(
                f"get_rule_descriptions() length {len(descriptions)} != "
                f"get_rule_functions() length {len(rules)}"
            )
        if any(not d for d in descriptions):
            raise ValueError("Each rule description must be a non-empty string")

    names: List[str] = []
    catalog = getattr(module, "RULE_CATALOG", None)
    if isinstance(catalog, list) and len(catalog) == len(rules):
        for entry in catalog:
            if isinstance(entry, (tuple, list)) and entry:
                names.append(str(entry[0]))
            else:
                names.append("")
        if any(not n for n in names):
            names = []
    if not names:
        names = [_rule_name(fn) for fn in rules]
    static_desc = [
        _rule_static_description(fn, i, descriptions) for i, fn in enumerate(rules)
    ]
    return rules, names, static_desc


def _load_dataset_cache(
    dataset_dir: Path,
    cache_path: Path,
    strip_fn: Callable[[Dict[str, Any]], Dict[str, Any]],
) -> List[Tuple[str, Dict[str, Any], float]]:
    if cache_path.is_file():
        with open(cache_path, "rb") as f:
            cached = pickle.load(f)
        if isinstance(cached, list) and cached:
            return cached

    samples: List[Tuple[str, Dict[str, Any], float]] = []
    for attempt_dir in sorted(dataset_dir.glob("attempt_*")):
        raw_path = attempt_dir / "raw-artifact.json"
        result_path = attempt_dir / "result.json"
        if not raw_path.is_file() or not result_path.is_file():
            continue
        with open(result_path, encoding="utf-8") as f:
            result = json.load(f)
        score = result.get("score")
        if score is None:
            continue
        with open(raw_path, encoding="utf-8") as f:
            raw = strip_fn(json.load(f))
        samples.append((attempt_dir.name, raw, float(score)))

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "wb") as f:
        pickle.dump(samples, f)
    return samples


def _apply_rules(
    rules: List[Callable[[Dict], Tuple[int, str]]],
    samples: List[Tuple[str, Dict[str, Any], float]],
) -> Tuple[np.ndarray, np.ndarray]:
    rows: List[List[int]] = []
    labels: List[float] = []
    errors: List[str] = []

    for attempt_id, raw, score in samples:
        row: List[int] = []
        for idx, rule in enumerate(rules):
            try:
                out = rule(raw)
            except Exception as exc:
                errors.append(f"{attempt_id} rule_{idx}: {exc}")
                row.append(0)
                continue
            if not isinstance(out, (tuple, list)) or len(out) != 2:
                errors.append(f"{attempt_id} rule_{idx}: must return (binary, explanation)")
                row.append(0)
                continue
            binary, _expl = out[0], out[1]
            if binary not in (0, 1, True, False):
                errors.append(f"{attempt_id} rule_{idx}: binary must be 0 or 1, got {binary!r}")
                row.append(0)
                continue
            row.append(int(bool(binary)))
        rows.append(row)
        labels.append(score)

    if errors:
        raise ValueError("; ".join(errors[:5]) + (f" (+{len(errors) - 5} more)" if len(errors) > 5 else ""))

    return np.array(rows, dtype=float), np.array(labels, dtype=float)


def _fit_regression(X: np.ndarray, y: np.ndarray) -> Tuple[float, float, np.ndarray, int]:
    n, k = X.shape
    if n < k + 1:
        raise ValueError(f"Need at least {k + 1} samples for {k} rules plus intercept, got {n}")

    design = np.column_stack([np.ones(n), X])
    coef, _residuals, rank, _ = np.linalg.lstsq(design, y, rcond=None)

    y_pred = design @ coef
    mse = float(np.mean((y - y_pred) ** 2))
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
    return mse, r2, coef, int(rank)


def evaluate_core(
    program_path: str,
    output_dir: str,
    workspace: Path,
    *,
    strip_fn: Callable[[Dict[str, Any]], Dict[str, Any]] | None = None,
) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    strip = strip_fn or strip_policy_visible_sustaindc
    meta = _load_meta(workspace)

    dataset_dir_raw = meta.get("dataset_dir")
    rule_set_size = meta.get("rule_set_size")
    if not dataset_dir_raw:
        return _failure_result("workspace_meta.json missing dataset_dir (set source_archive in config)")
    if rule_set_size is None:
        return _failure_result("workspace_meta.json missing rule_set_size")

    dataset_dir = Path(dataset_dir_raw)
    if not dataset_dir.is_dir():
        return _failure_result(f"dataset_dir not found: {dataset_dir}")

    rule_set_size = int(rule_set_size)
    forbidden = _validate_program_uses_policy_visible_only(program_path)
    if forbidden:
        return _failure_result(forbidden)
    try:
        rules, rule_names, rule_descriptions = _load_rules_and_descriptions(program_path)
    except Exception as exc:
        return _failure_result(f"Failed to load rules: {exc}")

    if len(rules) != rule_set_size:
        return _failure_result(
            f"get_rule_functions() returned {len(rules)} rules, expected {rule_set_size}"
        )

    cache_path = workspace / "archive" / "_dataset_cache" / CACHE_FILENAME
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        samples = _load_dataset_cache(dataset_dir, cache_path, strip)
    except Exception as exc:
        return _failure_result(f"Failed to load dataset: {exc}")

    if not samples:
        return _failure_result("No samples with raw-artifact.json and result.json score found")

    try:
        X, y = _apply_rules(rules, samples)
    except ValueError as exc:
        return _failure_result(f"Rule execution failed: {exc}")

    try:
        mse, r2, coef, rank = _fit_regression(X, y)
    except ValueError as exc:
        return _failure_result(f"Regression failed: {exc}", metrics={"n_samples": len(samples)})

    trigger_rates = X.mean(axis=0).tolist() if X.size else []
    metrics: Dict[str, Any] = {
        "mse": mse,
        "r2": r2,
        "n_samples": len(samples),
        "rule_set_size": rule_set_size,
        "rank": rank,
        "rank_full": rank >= rule_set_size + 1,
        "coef_intercept": float(coef[0]),
    }
    rule_summaries: List[Dict[str, Any]] = []
    for i in range(rule_set_size):
        coef_i = float(coef[i + 1])
        rate_i = float(trigger_rates[i]) if i < len(trigger_rates) else 0.0
        name_i = rule_names[i] if i < len(rule_names) else f"rule_{i}"
        desc_i = rule_descriptions[i] if i < len(rule_descriptions) else name_i
        metrics[f"rule_name_{i}"] = name_i
        metrics[f"rule_description_{i}"] = desc_i
        metrics[f"coef_{i}"] = coef_i
        metrics[f"rule_trigger_rate_{i}"] = rate_i
        rule_summaries.append(
            {
                "index": i,
                "name": name_i,
                "description": desc_i,
                "coef": coef_i,
                "trigger_rate": rate_i,
            }
        )

    metrics["rule_names"] = rule_names
    metrics["rule_descriptions"] = rule_descriptions

    score = -mse
    feedback = f"MSE={mse:.4f}, score={score:.4f}, R²={r2:.4f}, n={len(samples)}"
    legend_lines = [
        f"  [{s['index']}] {s['name']}: {s['description']} "
        f"(coef={s['coef']:+.3f}, trigger={s['trigger_rate']:.2f})"
        for s in rule_summaries
    ]
    feedback = feedback + "\nRules:\n" + "\n".join(legend_lines)

    summary_path = Path(output_dir) / "regression_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "mse": mse,
                "r2": r2,
                "n_samples": len(samples),
                "coef": [float(c) for c in coef],
                "trigger_rates": trigger_rates,
                "rules": rule_summaries,
            },
            f,
            indent=2,
        )

    return {
        "score": score,
        "is_valid": True,
        "feedback": feedback,
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
    spec = importlib.util.spec_from_file_location("drd_evaluator", evaluator_path)
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


def make_evaluate(strip_fn: Callable[[Dict[str, Any]], Dict[str, Any]] | None = None):
    """Return an evaluate(program_path, output_dir) entry point for a task."""

    def evaluate(program_path: str, output_dir: str) -> dict:
        workspace = Path(__file__).resolve().parent.parent
        if not (workspace / "workspace_meta.json").is_file():
            workspace = Path(__file__).resolve().parent
        try:
            evaluator_path = workspace / "evaluator.py"
            if not evaluator_path.is_file():
                evaluator_path = Path(__file__).resolve()

            def _evaluate_core(prog: str, out: str, ws: Path) -> dict:
                return evaluate_core(prog, out, ws, strip_fn=strip_fn)

            # Subprocess loads evaluator module; expose _evaluate_core on workspace copy.
            import types

            mod = types.ModuleType("drd_eval")
            mod._evaluate_core = _evaluate_core  # type: ignore[attr-defined]
            return run_in_subprocess(program_path, output_dir, workspace, evaluator_path)
        except subprocess.TimeoutExpired:
            return _failure_result("Evaluation timed out")
        except Exception as exc:
            return _failure_result(f"Evaluation failed: {exc}")

    return evaluate
