"""Baseline real-time adaptive signal processing algorithm."""

from __future__ import annotations

import numpy as np


def adaptive_filter(x, window_size=20):
    if len(x) < window_size:
        raise ValueError(f"Input signal length ({len(x)}) must be >= window_size ({window_size})")

    output_length = len(x) - window_size + 1
    y = np.zeros(output_length)
    for i in range(output_length):
        y[i] = np.mean(x[i : i + window_size])
    return y


def enhanced_filter_with_trend_preservation(x, window_size=20):
    if len(x) < window_size:
        raise ValueError(f"Input signal length ({len(x)}) must be >= window_size ({window_size})")

    output_length = len(x) - window_size + 1
    y = np.zeros(output_length)
    weights = np.exp(np.linspace(-2, 0, window_size))
    weights = weights / np.sum(weights)

    for i in range(output_length):
        window = x[i : i + window_size]
        y[i] = np.sum(window * weights)
    return y


def process_signal(input_signal, window_size=20, algorithm_type="enhanced"):
    if algorithm_type == "enhanced":
        return enhanced_filter_with_trend_preservation(input_signal, window_size)
    return adaptive_filter(input_signal, window_size)


def generate_test_signal(length=1000, noise_level=0.3, seed=42):
    np.random.seed(seed)
    t = np.linspace(0, 10, length)
    clean_signal = (
        2 * np.sin(2 * np.pi * 0.5 * t)
        + 1.5 * np.sin(2 * np.pi * 2 * t)
        + 0.5 * np.sin(2 * np.pi * 5 * t)
        + 0.8 * np.exp(-t / 5) * np.sin(2 * np.pi * 1.5 * t)
    )
    trend = 0.1 * t * np.sin(0.2 * t)
    clean_signal += trend
    random_walk = np.cumsum(np.random.randn(length) * 0.05)
    clean_signal += random_walk
    noisy_signal = clean_signal + np.random.normal(0, noise_level, length)
    return noisy_signal, clean_signal


def run_signal_processing(signal_length=1000, noise_level=0.3, window_size=20):
    """
    Required API for this example.

    Returns a dict with at least:
        filtered_signal: 1D array with length signal_length - window_size + 1
    """
    noisy_signal, clean_signal = generate_test_signal(signal_length, noise_level)
    filtered_signal = process_signal(noisy_signal, window_size, "enhanced")

    delay = window_size - 1
    aligned_clean = clean_signal[delay:]
    aligned_noisy = noisy_signal[delay:]
    min_length = min(len(filtered_signal), len(aligned_clean))
    filtered_signal = filtered_signal[:min_length]
    aligned_clean = aligned_clean[:min_length]
    aligned_noisy = aligned_noisy[:min_length]

    correlation = np.corrcoef(filtered_signal, aligned_clean)[0, 1] if min_length > 1 else 0.0
    noise_before = np.var(aligned_noisy - aligned_clean)
    noise_after = np.var(filtered_signal - aligned_clean)
    noise_reduction = (noise_before - noise_after) / noise_before if noise_before > 0 else 0.0

    return {
        "filtered_signal": filtered_signal,
        "clean_signal": aligned_clean,
        "noisy_signal": aligned_noisy,
        "correlation": correlation,
        "noise_reduction": noise_reduction,
        "signal_length": min_length,
    }


# if __name__ == "__main__":
#     results = run_signal_processing()
#     print(f"Correlation with clean signal: {results['correlation']:.3f}")
#     print(f"Noise reduction: {results['noise_reduction']:.3f}")
#     print(f"Processed signal length: {results['signal_length']}")
