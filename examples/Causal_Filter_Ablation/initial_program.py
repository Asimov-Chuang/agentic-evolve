"""Baseline causal denoising filter for Causal_Filter_Ablation."""

from __future__ import annotations


def denoise_signal(noisy_signal: list[float], window_size: int = 21) -> list[float]:
    """Return a simple causal exponential moving average of the noisy signal."""
    if not noisy_signal:
        return []

    alpha = 2.0 / (max(2, int(window_size)) + 1.0)
    estimate = float(noisy_signal[0])
    filtered: list[float] = []
    for value in noisy_signal:
        estimate = alpha * float(value) + (1.0 - alpha) * estimate
        filtered.append(estimate)
    return filtered