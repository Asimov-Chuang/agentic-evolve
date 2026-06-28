"""Private evaluator core for feedback-noise ablation (not copied to workspace)."""

from __future__ import annotations

import json
import math
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

SEQUENCE_LENGTH = 80
NOISE_POOL_SIZE = 20
DISPLAY_SHUFFLE_SEED = 42
DEFAULT_PROGRAM_TIMEOUT_SECONDS = 30


def _program_timeout_seconds() -> int:
    meta_path = Path(__file__).resolve().parent / "workspace_meta.json"
    if meta_path.is_file():
        with open(meta_path, encoding="utf-8") as f:
            return int(json.load(f).get("evaluation_timeout_seconds", DEFAULT_PROGRAM_TIMEOUT_SECONDS))
    return DEFAULT_PROGRAM_TIMEOUT_SECONDS


def hidden_target(n: int = SEQUENCE_LENGTH) -> list[float]:
    """Fixed reference waveform; only the evaluator knows this."""
    values: list[float] = []
    for i in range(n):
        t = i / max(n - 1, 1)
        base = 0.72 * math.sin(2.0 * math.pi * t)
        step = 0.24 if t > 0.72 else 0.0
        local_oscillation = 0.22 * math.sin(18.0 * math.pi * t) if 0.35 < t < 0.55 else 0.0
        paired_pulse = 0.0
        if 0.455 < t < 0.49:
            paired_pulse = 0.30
        elif 0.51 < t < 0.545:
            paired_pulse = -0.30
        value = base + step + local_oscillation + paired_pulse
        values.append(max(-1.0, min(1.0, value)))
    return values


def _segment_bounds(n: int) -> tuple[int, int, int]:
    third = n // 3
    return third, 2 * third, n


def _rmse(a: list[float], b: list[float]) -> float:
    if not a:
        return 0.0
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)) / len(a))


def compute_signal_metrics(sequence: list[float], target: list[float]) -> dict[str, float]:
    n = len(sequence)
    early_end, mid_end, _ = _segment_bounds(n)
    early_rmse = _rmse(sequence[:early_end], target[:early_end])
    mid_rmse = _rmse(sequence[early_end:mid_end], target[early_end:mid_end])
    late_rmse = _rmse(sequence[mid_end:], target[mid_end:])
    signed_errors = [s - t for s, t in zip(sequence, target)]
    mean_signed_error = sum(signed_errors) / len(signed_errors)
    peak_indices = sorted(range(n), key=lambda i: abs(target[i]), reverse=True)[:5]
    peak_abs_error = max(abs(sequence[i] - target[i]) for i in peak_indices)
    return {
        "early_rmse": early_rmse,
        "mid_rmse": mid_rmse,
        "late_rmse": late_rmse,
        "mean_signed_error": mean_signed_error,
        "peak_abs_error": peak_abs_error,
    }


def _hash_mix(values: list[float], salt: int) -> float:
    acc = salt * 7919
    for idx, value in enumerate(values):
        scaled = int(round(value * 10000.0))
        acc = (acc * 9973 + scaled * (idx + 1) + salt * 17) % 1_000_003
    return acc / 1_000_003.0


def compute_noise_metrics(sequence: list[float]) -> dict[str, float]:
    metrics: dict[str, float] = {}
    n = len(sequence)
    for k in range(1, NOISE_POOL_SIZE + 1):
        mix = _hash_mix(sequence, salt=k * 131)
        lag = k % max(n - 1, 1)
        autocorr = sum(sequence[i] * sequence[(i + lag) % n] for i in range(n)) / n
        phase = sum(math.sin(value * (k + 1) + i * 0.17) for i, value in enumerate(sequence)) / n
        metrics[f"noise_{k:02d}"] = abs(mix - 0.5) + 0.1 * abs(autocorr) + 0.05 * abs(phase)
    return metrics


def select_display_metrics(
    signal_metrics: dict[str, float],
    noise_metrics: dict[str, float],
    noise_ratio: float,
) -> dict[str, float]:
    """Pick signal/noise subset and relabel with neutral metric_XX names."""
    if noise_ratio <= 0.0:
        selected_noise: dict[str, float] = {}
    else:
        ratio = min(max(noise_ratio, 0.0), 0.99)
        n_noise = round(ratio / (1.0 - ratio) * len(signal_metrics))
        n_noise = min(n_noise, len(noise_metrics))
        selected_noise = dict(list(noise_metrics.items())[:n_noise])

    combined = list(signal_metrics.items()) + list(selected_noise.items())
    rng = random.Random(DISPLAY_SHUFFLE_SEED)
    rng.shuffle(combined)

    return {f"metric_{i + 1:02d}": value for i, (_, value) in enumerate(combined)}


def format_processed_feedback(score: float, display_metrics: dict[str, float]) -> str:
    lines = [f"Score: {score:.6f}", "Diagnostics (lower is generally better):"]
    for name in sorted(display_metrics):
        lines.append(f"  {name}: {display_metrics[name]:.6f}")
    return "\n".join(lines)


def _analyze_with_noise_ratio(program_path: str, result: dict, noise_ratio: float) -> dict:
    if not result.get("is_valid"):
        return {
            "processed_feedback": (
                "Invalid submission; fix runtime or constraint errors first. "
                f"{result.get('feedback', '')}"
            ),
        }

    try:
        sequence = _load_program(program_path)
    except Exception as exc:
        return {
            "processed_feedback": f"Could not reload program for diagnostics: {exc}",
        }

    target = hidden_target(SEQUENCE_LENGTH)
    signal_metrics = compute_signal_metrics(sequence, target)
    noise_metrics = compute_noise_metrics(sequence)
    display_metrics = select_display_metrics(signal_metrics, noise_metrics, noise_ratio)
    score = float(result.get("score", 0.0))
    return {
        "processed_feedback": format_processed_feedback(score, display_metrics),
        "analysis_metrics": display_metrics,
    }


def evaluate(program_path: str, output_dir: str) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    target = hidden_target(SEQUENCE_LENGTH)

    try:
        sequence = _load_program(program_path)
    except Exception as exc:
        return {
            "score": -1.0,
            "is_valid": False,
            "feedback": f"Failed to run program: {exc}",
            "metrics": {"rmse": 1.0},
        }

    if len(sequence) != SEQUENCE_LENGTH:
        return {
            "score": -1.0,
            "is_valid": False,
            "feedback": f"Expected {SEQUENCE_LENGTH} values, got {len(sequence)}",
            "metrics": {"rmse": 1.0},
        }

    out_of_range = [i for i, value in enumerate(sequence) if value < -1.0 or value > 1.0]
    if out_of_range:
        return {
            "score": -1.0,
            "is_valid": False,
            "feedback": f"Values out of [-1, 1] at indices: {out_of_range[:5]}",
            "metrics": {"rmse": 1.0},
        }

    rmse = _rmse(sequence, target)
    score = -rmse

    return {
        "score": score,
        "is_valid": True,
        "feedback": f"Score: {score:.6f} (RMSE={rmse:.6f})",
        "metrics": {"rmse": rmse},
        "construction": {"rmse": rmse},
    }


def _load_program(program_path: str) -> list[float]:
    with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as tmp:
        result_file = tmp.name

    script = f"""
import importlib.util
import pickle
import traceback

program_path = {program_path!r}
result_file = {result_file!r}

try:
    spec = importlib.util.spec_from_file_location("program", program_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sequence = module.generate_control_sequence()
    with open(result_file, "wb") as f:
        pickle.dump({{"sequence": sequence}}, f)
except Exception:
    with open(result_file, "wb") as f:
        pickle.dump({{"error": traceback.format_exc()}}, f)
"""

    with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as tmp_script:
        tmp_script.write(script.encode("utf-8"))
        script_path = tmp_script.name

    try:
        completed = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=_program_timeout_seconds(),
        )
        import pickle

        with open(result_file, "rb") as f:
            payload = pickle.load(f)
        if "error" in payload:
            raise RuntimeError(payload["error"])
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr or "Program subprocess failed")
        sequence = payload["sequence"]
        if not isinstance(sequence, list):
            raise TypeError("generate_control_sequence() must return a list")
        return [float(value) for value in sequence]
    finally:
        os.unlink(result_file)
        os.unlink(script_path)


if __name__ == "__main__":
    program = sys.argv[1] if len(sys.argv) > 1 else "initial_program.py"
    result = evaluate(program, ".")
    print(json.dumps(result, indent=2))
