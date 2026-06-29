"""Private evaluator core for causal-filter feedback ablation."""

from __future__ import annotations

import json
import math
import os
import pickle
import random
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SEQUENCE_LENGTH = 160
DISPLAY_SHUFFLE_SEED = 42
DEFAULT_PROGRAM_TIMEOUT_SECONDS = 30


def _program_timeout_seconds() -> int:
    meta_path = Path(__file__).resolve().parent / "workspace_meta.json"
    if meta_path.is_file():
        with open(meta_path, encoding="utf-8") as f:
            return int(json.load(f).get("evaluation_timeout_seconds", DEFAULT_PROGRAM_TIMEOUT_SECONDS))
    return DEFAULT_PROGRAM_TIMEOUT_SECONDS


def _clamp(value: float, lower: float = -2.5, upper: float = 2.5) -> float:
    return max(lower, min(upper, value))


def _gauss(rng: random.Random, sigma: float) -> float:
    return rng.gauss(0.0, sigma)


def _make_smooth_case(rng: random.Random, idx: int) -> dict[str, Any]:
    phase = rng.uniform(-0.5, 0.5)
    freq = rng.uniform(1.4, 2.4)
    trend = rng.uniform(-0.25, 0.25)
    clean: list[float] = []
    for i in range(SEQUENCE_LENGTH):
        t = i / (SEQUENCE_LENGTH - 1)
        value = 0.58 * math.sin(2.0 * math.pi * (freq * t + phase))
        value += 0.18 * math.sin(2.0 * math.pi * (0.35 * t + 0.1 * idx))
        value += trend * (t - 0.5)
        clean.append(_clamp(value))
    return _with_noise(rng, f"smooth_{idx}", "periodic", clean)


def _make_chirp_case(rng: random.Random, idx: int) -> dict[str, Any]:
    clean: list[float] = []
    base = rng.uniform(0.7, 1.1)
    sweep = rng.uniform(2.3, 3.4)
    for i in range(SEQUENCE_LENGTH):
        t = i / (SEQUENCE_LENGTH - 1)
        phase = 2.0 * math.pi * (base * t + sweep * t * t)
        value = 0.48 * math.sin(phase) + 0.16 * math.sin(2.0 * phase + 0.4)
        clean.append(_clamp(value))
    return _with_noise(rng, f"chirp_{idx}", "periodic", clean)


def _make_step_case(rng: random.Random, idx: int) -> dict[str, Any]:
    levels = [rng.uniform(-0.9, 0.9) for _ in range(5)]
    transitions = sorted(rng.sample(range(28, SEQUENCE_LENGTH - 24), 4))
    clean: list[float] = []
    segment = 0
    for i in range(SEQUENCE_LENGTH):
        while segment < len(transitions) and i >= transitions[segment]:
            segment += 1
        clean.append(levels[segment])
    case = _with_noise(rng, f"step_{idx}", "step", clean)
    case["transitions"] = transitions
    return case


def _make_burst_case(rng: random.Random, idx: int) -> dict[str, Any]:
    centers = sorted(rng.sample(range(25, SEQUENCE_LENGTH - 20), 4))
    clean: list[float] = []
    for i in range(SEQUENCE_LENGTH):
        t = i / (SEQUENCE_LENGTH - 1)
        value = 0.18 * math.sin(2.0 * math.pi * (1.2 * t + 0.2 * idx))
        for center in centers:
            width = 3.5 + (center % 3)
            amp = 0.55 if center % 2 == 0 else -0.50
            value += amp * math.exp(-((i - center) ** 2) / (2.0 * width * width))
        clean.append(_clamp(value))
    case = _with_noise(rng, f"burst_{idx}", "burst", clean, outlier_rate=0.025)
    case["burst_centers"] = centers
    return case


def _make_drift_case(rng: random.Random, idx: int) -> dict[str, Any]:
    value = rng.uniform(-0.2, 0.2)
    clean: list[float] = []
    velocity = 0.0
    for i in range(SEQUENCE_LENGTH):
        t = i / (SEQUENCE_LENGTH - 1)
        velocity = 0.92 * velocity + rng.uniform(-0.018, 0.018)
        value += velocity
        value += 0.004 * math.sin(2.0 * math.pi * (0.5 * t + idx * 0.11))
        clean.append(_clamp(value, -1.2, 1.2))
    return _with_noise(rng, f"drift_{idx}", "drift", clean, noise_sigma=0.11)


def _with_noise(
    rng: random.Random,
    case_id: str,
    family: str,
    clean: list[float],
    *,
    noise_sigma: float = 0.14,
    outlier_rate: float = 0.015,
) -> dict[str, Any]:
    noisy: list[float] = []
    for value in clean:
        noise = _gauss(rng, noise_sigma)
        if rng.random() < outlier_rate:
            noise += rng.choice([-1.0, 1.0]) * rng.uniform(0.35, 0.7)
        noisy.append(_clamp(value + noise))
    return {"id": case_id, "family": family, "clean": clean, "noisy": noisy}


def hidden_cases() -> list[dict[str, Any]]:
    rng = random.Random(20260622)
    cases: list[dict[str, Any]] = []
    for idx in range(3):
        cases.append(_make_smooth_case(rng, idx))
        cases.append(_make_chirp_case(rng, idx))
        cases.append(_make_step_case(rng, idx))
        cases.append(_make_burst_case(rng, idx))
        cases.append(_make_drift_case(rng, idx))
    return cases


def _rmse(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)) / max(1, len(a)))


def _mean_abs(a: list[float], b: list[float]) -> float:
    return sum(abs(x - y) for x, y in zip(a, b)) / max(1, len(a))


def _variance(values: list[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return sum((value - mean) ** 2 for value in values) / len(values)


def _corr(a: list[float], b: list[float]) -> float:
    if len(a) < 2:
        return 0.0
    mean_a = sum(a) / len(a)
    mean_b = sum(b) / len(b)
    da = [x - mean_a for x in a]
    db = [y - mean_b for y in b]
    denom = math.sqrt(sum(x * x for x in da) * sum(y * y for y in db))
    if denom <= 1e-12:
        return 0.0
    return sum(x * y for x, y in zip(da, db)) / denom


def _window_indices(center: int, n: int, radius: int) -> list[int]:
    return list(range(max(0, center - radius), min(n, center + radius + 1)))


def _best_shift_error(output: list[float], clean: list[float], max_shift: int = 6) -> tuple[int, float]:
    best_shift = 0
    best_rmse = float("inf")
    n = len(output)
    for shift in range(-max_shift, max_shift + 1):
        pairs: list[tuple[float, float]] = []
        for i in range(n):
            j = i + shift
            if 0 <= j < n:
                pairs.append((output[i], clean[j]))
        if len(pairs) < n // 2:
            continue
        err = math.sqrt(sum((x - y) ** 2 for x, y in pairs) / len(pairs))
        if err < best_rmse:
            best_shift = shift
            best_rmse = err
    return best_shift, best_rmse


def _event_mask(case: dict[str, Any], radius: int = 5) -> set[int]:
    n = len(case["clean"])
    mask: set[int] = set()
    for key in ("transitions", "burst_centers"):
        for center in case.get(key, []):
            mask.update(_window_indices(int(center), n, radius))
    return mask


def compute_signal_metrics(outputs: list[list[float]], cases: list[dict[str, Any]]) -> dict[str, float]:
    periodic_errors: list[float] = []
    transition_errors: list[float] = []
    burst_errors: list[float] = []
    lag_errors: list[float] = []
    residual_ratios: list[float] = []

    for output, case in zip(outputs, cases):
        clean = case["clean"]
        noisy = case["noisy"]
        family = case["family"]
        if family == "periodic":
            periodic_errors.append(_rmse(output, clean))

        if family == "step":
            indices: list[int] = []
            for center in case.get("transitions", []):
                indices.extend(_window_indices(int(center), len(clean), 5))
            if indices:
                transition_errors.append(
                    sum(abs(output[i] - clean[i]) for i in indices) / len(indices)
                )

        if family == "burst":
            indices = []
            for center in case.get("burst_centers", []):
                indices.extend(_window_indices(int(center), len(clean), 5))
            if indices:
                burst_errors.append(sum(abs(output[i] - clean[i]) for i in indices) / len(indices))

        best_shift, best_rmse = _best_shift_error(output, clean)
        direct_rmse = _rmse(output, clean)
        lag_errors.append(abs(best_shift) / 6.0 + max(0.0, direct_rmse - best_rmse))

        mask = _event_mask(case, radius=5)
        residual = [output[i] - clean[i] for i in range(len(clean)) if i not in mask]
        noise = [noisy[i] - clean[i] for i in range(len(clean)) if i not in mask]
        residual_var = _variance(residual)
        noise_var = _variance(noise)
        residual_ratios.append(residual_var / max(noise_var, 1e-9))

    return {
        "periodic_rmse": statistics.mean(periodic_errors) if periodic_errors else 1.0,
        "step_transition_error": statistics.mean(transition_errors) if transition_errors else 1.0,
        "transient_peak_error": statistics.mean(burst_errors) if burst_errors else 1.0,
        "lag_error": statistics.mean(lag_errors) if lag_errors else 1.0,
        "noise_suppression_error": statistics.mean(residual_ratios) if residual_ratios else 1.0,
    }


def select_display_metrics(signal_metrics: dict[str, float], noise_ratio: float = 0.0) -> dict[str, float]:
    del noise_ratio
    combined = list(signal_metrics.items())
    rng = random.Random(DISPLAY_SHUFFLE_SEED)
    rng.shuffle(combined)
    return {f"metric_{idx + 1:02d}": value for idx, (_name, value) in enumerate(combined)}


def metric_meaning_mapping() -> dict[str, str]:
    names = [
        "periodic_rmse",
        "step_transition_error",
        "transient_peak_error",
        "lag_error",
        "noise_suppression_error",
    ]
    rng = random.Random(DISPLAY_SHUFFLE_SEED)
    rng.shuffle(names)
    return {f"metric_{idx + 1:02d}": name for idx, name in enumerate(names)}


def format_processed_feedback(score: float, display_metrics: dict[str, float]) -> str:
    lines = [f"Score: {score:.6f}", "Diagnostics (lower is generally better):"]
    for name in sorted(display_metrics):
        lines.append(f"  {name}: {display_metrics[name]:.6f}")
    return "\n".join(lines)


def _score_from_outputs(outputs: list[list[float]], cases: list[dict[str, Any]]) -> tuple[float, dict[str, float]]:
    noisy_rmse = statistics.mean(_rmse(case["noisy"], case["clean"]) for case in cases)
    output_rmse = statistics.mean(_rmse(output, case["clean"]) for output, case in zip(outputs, cases))
    corrs = [_corr(output, case["clean"]) for output, case in zip(outputs, cases)]
    metrics = compute_signal_metrics(outputs, cases)

    rmse_score = max(0.0, min(1.0, 1.0 - output_rmse / max(noisy_rmse, 1e-9)))
    corr_score = max(0.0, min(1.0, (statistics.mean(corrs) + 1.0) / 2.0))
    step_score = max(0.0, min(1.0, 1.0 - metrics["step_transition_error"] / 0.65))
    burst_score = max(0.0, min(1.0, 1.0 - metrics["transient_peak_error"] / 0.65))
    lag_score = max(0.0, min(1.0, 1.0 - metrics["lag_error"] / 1.15))
    noise_score = max(0.0, min(1.0, 1.0 - metrics["noise_suppression_error"] / 1.4))

    score = (
        0.34 * rmse_score
        + 0.16 * corr_score
        + 0.14 * step_score
        + 0.14 * burst_score
        + 0.12 * lag_score
        + 0.10 * noise_score
    )
    return score, metrics


def _load_program_outputs(program_path: str, cases: list[dict[str, Any]]) -> list[list[float]]:
    with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as tmp:
        input_file = tmp.name
    with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as tmp:
        result_file = tmp.name

    payload = [{"id": case["id"], "noisy": case["noisy"]} for case in cases]
    with open(input_file, "wb") as f:
        pickle.dump(payload, f)

    script = f"""
import importlib.util
import math
import pickle
import traceback

program_path = {program_path!r}
input_file = {input_file!r}
result_file = {result_file!r}

try:
    spec = importlib.util.spec_from_file_location("program", program_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "denoise_signal"):
        raise AttributeError("program must define denoise_signal(noisy_signal, window_size=21)")
    with open(input_file, "rb") as f:
        cases = pickle.load(f)
    outputs = []
    causality_errors = []
    check_points = (20, 40, 80, 120, 159)
    for case in cases:
        noisy = [float(x) for x in case["noisy"]]
        full = module.denoise_signal(list(noisy))
        if not isinstance(full, list):
            raise TypeError("denoise_signal() must return a list")
        full = [float(x) for x in full]
        if len(full) != len(noisy):
            raise ValueError(f"Expected {{len(noisy)}} outputs, got {{len(full)}}")
        for value in full:
            if not math.isfinite(value):
                raise ValueError("All returned values must be finite")
            if abs(value) > 10.0:
                raise ValueError("Returned values are implausibly large; keep the filter numerically stable")
        for point in check_points:
            if point >= len(noisy):
                continue
            prefix = module.denoise_signal(list(noisy[: point + 1]))
            if not isinstance(prefix, list) or len(prefix) != point + 1:
                raise ValueError("Causality check requires valid same-length outputs on prefixes")
            if abs(float(prefix[-1]) - full[point]) > 1e-7:
                causality_errors.append((case["id"], point, float(prefix[-1]), full[point]))
        outputs.append(full)
    if causality_errors:
        raise ValueError(
            "Filter appears non-causal: output for a prefix differs from the same index in the full signal"
        )
    with open(result_file, "wb") as f:
        pickle.dump({{"outputs": outputs}}, f)
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
            timeout=_program_timeout_seconds(),
        )
        with open(result_file, "rb") as f:
            result = pickle.load(f)
        if "error" in result:
            raise RuntimeError(result["error"])
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr or "Program subprocess failed")
        return result["outputs"]
    finally:
        os.unlink(input_file)
        os.unlink(result_file)
        os.unlink(script_path)


def evaluate(program_path: str, output_dir: str) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    cases = hidden_cases()
    try:
        outputs = _load_program_outputs(program_path, cases)
    except Exception as exc:
        return {
            "score": -1.0,
            "is_valid": False,
            "feedback": f"Failed to evaluate causal filter: {exc}",
            "metrics": {"score": -1.0},
        }

    score, _signal_metrics = _score_from_outputs(outputs, cases)
    aggregate_rmse = statistics.mean(_rmse(output, case["clean"]) for output, case in zip(outputs, cases))
    noisy_rmse = statistics.mean(_rmse(case["noisy"], case["clean"]) for case in cases)
    return {
        "score": score,
        "is_valid": True,
        "feedback": f"Score: {score:.6f} (aggregate RMSE={aggregate_rmse:.6f}, noisy baseline RMSE={noisy_rmse:.6f})",
        "metrics": {
            "aggregate_rmse": aggregate_rmse,
            "noisy_baseline_rmse": noisy_rmse,
        },
    }


def _analyze_with_noise_ratio(program_path: str, result: dict, noise_ratio: float) -> dict:
    if not result.get("is_valid"):
        return {
            "processed_feedback": (
                "Invalid submission; fix runtime, interface, or causality errors first. "
                f"{result.get('feedback', '')}"
            ),
        }

    cases = hidden_cases()
    try:
        outputs = _load_program_outputs(program_path, cases)
    except Exception as exc:
        return {"processed_feedback": f"Could not reload program for diagnostics: {exc}"}

    score, signal_metrics = _score_from_outputs(outputs, cases)
    display_metrics = select_display_metrics(signal_metrics, noise_ratio=noise_ratio)
    return {
        "processed_feedback": format_processed_feedback(score, display_metrics),
        "analysis_metrics": display_metrics,
    }


if __name__ == "__main__":
    program = sys.argv[1] if len(sys.argv) > 1 else "initial_program.py"
    result = evaluate(program, ".")
    print(json.dumps(result, indent=2))
    print("metric mapping:", metric_meaning_mapping())