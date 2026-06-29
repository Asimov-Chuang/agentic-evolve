"""Baseline control sequence for hidden waveform matching."""


def generate_control_sequence(n: int = 80) -> list[float]:
    """Return a constant sequence — poor match to the hidden reference."""
    return [0.2] * n
