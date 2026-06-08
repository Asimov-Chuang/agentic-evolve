"""Signal processing evaluator aligned with OpenEvolve metric exposure."""

from __future__ import annotations

import importlib.util
import json
import os
import pickle
import subprocess
import sys
import tempfile
import time
import traceback
from concurrent import futures
from pathlib import Path

import numpy as np
from scipy.stats import pearsonr

DEFAULT_PROGRAM_TIMEOUT_SECONDS = 90
WINDOW_SIZE = 20
SIGNAL_TIMEOUT_SECONDS = 10

OPENEVOLVE_METRIC_KEYS = (
    "composite_score",
    "overall_score",
    "slope_changes",
    "lag_error",
    "avg_error",
    "false_reversals",
    "correlation",
    "noise_reduction",
    "smoothness_score",
    "responsiveness_score",
    "accuracy_score",
    "efficiency_score",
    "execution_time",
    "success_rate",
)


def _program_timeout_seconds() -> int:
    meta_path = Path(__file__).resolve().parent / "workspace_meta.json"
    if meta_path.is_file():
        with open(meta_path, encoding="utf-8") as f:
            return int(json.load(f).get("evaluation_timeout_seconds", DEFAULT_PROGRAM_TIMEOUT_SECONDS))
    return DEFAULT_PROGRAM_TIMEOUT_SECONDS


def evaluate(program_path: str, output_dir: str) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    try:
        openevolve_metrics = _evaluate_like_openevolve(program_path)
    except Exception as exc:
        openevolve_metrics = {
            "composite_score": 0.0,
            "overall_score": 0.0,
            "error": str(exc),
        }

    error = openevolve_metrics.get("error")
    metrics = {
        key: safe_float(openevolve_metrics[key])
        for key in OPENEVOLVE_METRIC_KEYS
        if key in openevolve_metrics
    }
    score = safe_float(openevolve_metrics.get("overall_score", 0.0))
    success_rate = safe_float(metrics.get("success_rate", 0.0))
    is_valid = error is None and success_rate >= 1.0

    feedback = format_metrics_for_llm(openevolve_metrics)
    if error:
        feedback = f"{feedback}\n- error: {error}" if feedback else f"- error: {error}"

    return {
        "score": score,
        "is_valid": is_valid,
        "feedback": feedback,
        "metrics": metrics,
    }


def format_metrics_for_llm(metrics: dict) -> str:
    """Match OpenEvolve PromptSampler._format_metrics output."""
    lines = []
    for name in OPENEVOLVE_METRIC_KEYS:
        if name not in metrics:
            continue
        value = metrics[name]
        if isinstance(value, (int, float)):
            lines.append(f"- {name}: {value:.4f}")
        else:
            lines.append(f"- {name}: {value}")
    return "\n".join(lines)


def _evaluate_like_openevolve(program_path: str) -> dict:
    spec = importlib.util.spec_from_file_location("program", program_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load program: {program_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "run_signal_processing"):
        return {
            "composite_score": 0.0,
            "overall_score": 0.0,
            "error": "Missing run_signal_processing function",
        }

    test_signals = generate_test_signals(5)
    all_scores = []
    all_metrics = []
    successful_runs = 0

    for i, (noisy_signal, clean_signal) in enumerate(test_signals):
        try:
            start_time = time.time()
            result = run_with_timeout(
                module.run_signal_processing,
                kwargs={
                    "signal_length": len(noisy_signal),
                    "noise_level": 0.3,
                    "window_size": WINDOW_SIZE,
                },
                timeout_seconds=SIGNAL_TIMEOUT_SECONDS,
            )
            execution_time = time.time() - start_time

            if not isinstance(result, dict) or "filtered_signal" not in result:
                continue

            filtered_signal = np.asarray(result["filtered_signal"])
            if len(filtered_signal) == 0:
                continue

            slope_changes = calculate_slope_changes(filtered_signal)
            lag_error = calculate_lag_error(filtered_signal, noisy_signal, WINDOW_SIZE)
            avg_error = calculate_average_tracking_error(filtered_signal, noisy_signal, WINDOW_SIZE)
            false_reversals = calculate_false_reversal_penalty(
                filtered_signal, clean_signal, WINDOW_SIZE
            )
            composite_score = calculate_composite_score(
                slope_changes, lag_error, avg_error, false_reversals
            )

            correlation = 0.0
            noise_reduction = 0.0
            delay = WINDOW_SIZE - 1
            aligned_clean = clean_signal[delay : delay + len(filtered_signal)]
            min_length = min(len(filtered_signal), len(aligned_clean))
            if min_length > 1:
                corr_result = pearsonr(
                    filtered_signal[:min_length], aligned_clean[:min_length]
                )
                correlation = corr_result[0] if not np.isnan(corr_result[0]) else 0.0

            aligned_noisy = noisy_signal[delay : delay + len(filtered_signal)][:min_length]
            aligned_clean = aligned_clean[:min_length]
            if min_length > 0:
                noise_before = np.var(aligned_noisy - aligned_clean)
                noise_after = np.var(filtered_signal[:min_length] - aligned_clean)
                noise_reduction = (
                    (noise_before - noise_after) / noise_before if noise_before > 0 else 0.0
                )
                noise_reduction = max(0.0, noise_reduction)

            all_scores.append(composite_score)
            all_metrics.append(
                {
                    "slope_changes": safe_float(slope_changes),
                    "lag_error": safe_float(lag_error),
                    "avg_error": safe_float(avg_error),
                    "false_reversals": safe_float(false_reversals),
                    "composite_score": safe_float(composite_score),
                    "correlation": safe_float(correlation),
                    "noise_reduction": safe_float(noise_reduction),
                    "execution_time": safe_float(execution_time),
                    "signal_length": len(filtered_signal),
                }
            )
            successful_runs += 1
        except TimeoutError:
            continue
        except Exception:
            continue

    if successful_runs == 0:
        return {
            "composite_score": 0.0,
            "overall_score": 0.0,
            "slope_changes": 100.0,
            "lag_error": 1.0,
            "avg_error": 1.0,
            "false_reversals": 50.0,
            "correlation": 0.0,
            "noise_reduction": 0.0,
            "success_rate": 0.0,
            "error": "All test signals failed",
        }

    avg_composite_score = float(np.mean(all_scores))
    avg_slope_changes = float(np.mean([m["slope_changes"] for m in all_metrics]))
    avg_lag_error = float(np.mean([m["lag_error"] for m in all_metrics]))
    avg_avg_error = float(np.mean([m["avg_error"] for m in all_metrics]))
    avg_false_reversals = float(np.mean([m["false_reversals"] for m in all_metrics]))
    avg_correlation = float(np.mean([m["correlation"] for m in all_metrics]))
    avg_noise_reduction = float(np.mean([m["noise_reduction"] for m in all_metrics]))
    avg_execution_time = float(np.mean([m["execution_time"] for m in all_metrics]))
    success_rate = successful_runs / len(test_signals)

    smoothness_score = 1.0 / (1.0 + avg_slope_changes / 20.0)
    responsiveness_score = 1.0 / (1.0 + avg_lag_error)
    accuracy_score = max(0.0, avg_correlation)
    efficiency_score = min(1.0, 1.0 / max(0.001, avg_execution_time))
    overall_score = (
        0.4 * avg_composite_score
        + 0.2 * smoothness_score
        + 0.2 * accuracy_score
        + 0.1 * avg_noise_reduction
        + 0.1 * success_rate
    )

    return {
        "composite_score": safe_float(avg_composite_score),
        "overall_score": safe_float(overall_score),
        "slope_changes": safe_float(avg_slope_changes),
        "lag_error": safe_float(avg_lag_error),
        "avg_error": safe_float(avg_avg_error),
        "false_reversals": safe_float(avg_false_reversals),
        "correlation": safe_float(avg_correlation),
        "noise_reduction": safe_float(avg_noise_reduction),
        "smoothness_score": safe_float(smoothness_score),
        "responsiveness_score": safe_float(responsiveness_score),
        "accuracy_score": safe_float(accuracy_score),
        "efficiency_score": safe_float(efficiency_score),
        "execution_time": safe_float(avg_execution_time),
        "success_rate": safe_float(success_rate),
    }


def run_with_timeout(func, args=(), kwargs=None, timeout_seconds=30):
    kwargs = kwargs or {}
    with futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func, *args, **kwargs)
        try:
            return future.result(timeout=timeout_seconds)
        except futures.TimeoutError as exc:
            raise TimeoutError(f"Function timed out after {timeout_seconds} seconds") from exc


def generate_test_signals(num_signals: int = 5) -> list[tuple[np.ndarray, np.ndarray]]:
    test_signals = []
    for i in range(num_signals):
        np.random.seed(42 + i)
        length = 500 + i * 100
        noise_level = 0.2 + i * 0.1
        t = np.linspace(0, 10, length)

        if i == 0:
            clean = 2 * np.sin(2 * np.pi * 0.5 * t) + 0.1 * t
        elif i == 1:
            clean = (
                np.sin(2 * np.pi * 0.5 * t)
                + 0.5 * np.sin(2 * np.pi * 2 * t)
                + 0.2 * np.sin(2 * np.pi * 5 * t)
            )
        elif i == 2:
            clean = np.sin(2 * np.pi * (0.5 + 0.2 * t) * t)
        elif i == 3:
            clean = np.concatenate(
                [
                    np.ones(length // 3),
                    2 * np.ones(length // 3),
                    0.5 * np.ones(length - 2 * (length // 3)),
                ]
            )
        else:
            clean = np.cumsum(np.random.randn(length) * 0.1) + 0.05 * t

        noisy = clean + np.random.normal(0, noise_level, length)
        test_signals.append((noisy, clean))
    return test_signals


def calculate_slope_changes(signal_data: np.ndarray) -> int:
    if len(signal_data) < 3:
        return 0
    diffs = np.diff(signal_data)
    sign_changes = 0
    for i in range(1, len(diffs)):
        if np.sign(diffs[i]) != np.sign(diffs[i - 1]) and diffs[i - 1] != 0:
            sign_changes += 1
    return sign_changes


def calculate_lag_error(filtered_signal: np.ndarray, original_signal: np.ndarray, window_size: int) -> float:
    if len(filtered_signal) == 0:
        return 1.0
    delay = window_size - 1
    if len(original_signal) <= delay:
        return 1.0
    recent_filtered = filtered_signal[-1]
    recent_original = original_signal[delay + len(filtered_signal) - 1]
    return float(abs(recent_filtered - recent_original))


def calculate_average_tracking_error(
    filtered_signal: np.ndarray, original_signal: np.ndarray, window_size: int
) -> float:
    if len(filtered_signal) == 0:
        return 1.0
    delay = window_size - 1
    if len(original_signal) <= delay:
        return 1.0
    aligned_original = original_signal[delay : delay + len(filtered_signal)]
    min_length = min(len(filtered_signal), len(aligned_original))
    if min_length == 0:
        return 1.0
    return float(np.mean(np.abs(filtered_signal[:min_length] - aligned_original[:min_length])))


def calculate_false_reversal_penalty(
    filtered_signal: np.ndarray, clean_signal: np.ndarray, window_size: int
) -> int:
    if len(filtered_signal) < 3 or len(clean_signal) < 3:
        return 0
    delay = window_size - 1
    if len(clean_signal) <= delay:
        return 1.0
    aligned_clean = clean_signal[delay : delay + len(filtered_signal)]
    min_length = min(len(filtered_signal), len(aligned_clean))
    if min_length < 3:
        return 0

    filtered_aligned = filtered_signal[:min_length]
    clean_aligned = aligned_clean[:min_length]
    filtered_diffs = np.diff(filtered_aligned)
    clean_diffs = np.diff(clean_aligned)

    false_reversals = 0
    for i in range(1, len(filtered_diffs)):
        filtered_change = (
            np.sign(filtered_diffs[i]) != np.sign(filtered_diffs[i - 1])
            and filtered_diffs[i - 1] != 0
        )
        clean_change = (
            np.sign(clean_diffs[i]) != np.sign(clean_diffs[i - 1]) and clean_diffs[i - 1] != 0
        )
        if filtered_change and not clean_change:
            false_reversals += 1
    return false_reversals


def calculate_composite_score(
    slope_changes: float, lag_error: float, avg_error: float, false_reversals: float
) -> float:
    s_norm = min(slope_changes / 50.0, 2.0)
    lag_norm = min(lag_error, 2.0)
    avg_norm = min(avg_error, 2.0)
    reversal_norm = min(false_reversals / 25.0, 2.0)
    penalty = 0.3 * s_norm + 0.2 * lag_norm + 0.2 * avg_norm + 0.3 * reversal_norm
    return float(1.0 / (1.0 + penalty))


def safe_float(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if np.isnan(number) or np.isinf(number):
        return 0.0
    return number


if __name__ == "__main__":
    program = sys.argv[1] if len(sys.argv) > 1 else "initial_program.py"
    print(evaluate(program, "."))
