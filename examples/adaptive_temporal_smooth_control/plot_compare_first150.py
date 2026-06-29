"""Compare best-so-far curves for two optics evolution runs (first 150 attempts)."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt


def load_best_so_far(workspace: Path, max_attempts: int = 150) -> tuple[list[int], list[float]]:
    archive = workspace / "archive"
    attempts: list[int] = []
    best: list[float] = []
    running = float("-inf")
    for p in sorted(archive.glob("attempt_*/result.json")):
        n = int(p.parent.name.split("_")[1])
        if n >= max_attempts:
            break
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("is_valid", True):
            running = max(running, float(d["score"]))
            attempts.append(n)
            best.append(running)
    return attempts, best


def load_rule_injection_milestones(
    workspace: Path,
    *,
    max_attempt: int = 150,
) -> list[tuple[int, int]]:
    """Return (cycle, attempt) for each rule-injection session start within max_attempt."""
    trajectory = workspace / "score_trajectory.jsonl"
    if not trajectory.is_file():
        return []

    milestones: list[tuple[int, int]] = []
    cycle = 0
    for line in trajectory.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        event = rec.get("event")
        if event == "discovery_end":
            cycle = int(rec.get("cycle", cycle))
        elif event == "session_start" and rec.get("mode") == "rule_injection":
            attempt = int(rec.get("session_baseline_count", rec.get("attempt_count", 0)))
            if attempt < max_attempt:
                milestones.append((cycle, attempt))
    return milestones


def main() -> None:
    base = Path(__file__).resolve().parent / "outputs"
    ws_x = base / "optics_temporal_smooth_X"
    ws_rf = base / "optics_temporal_smooth_rich_feedback"

    a_x, b_x = load_best_so_far(ws_x)
    a_rf, b_rf = load_best_so_far(ws_rf)

    fig, ax = plt.subplots(figsize=(10.5, 5.8))
    ax.plot(a_x, b_x, linewidth=2.2, label="optics_temporal_smooth_X", color="#1f77b4")
    ax.plot(a_rf, b_rf, linewidth=2.2, label="optics_temporal_smooth_rich_feedback", color="#ff7f0e")
    ax.set_title("Best score so far vs attempt (first 150)", fontsize=13, pad=12)
    ax.set_xlabel("Attempt number", fontsize=11)
    ax.set_ylabel("Score", fontsize=11)
    ax.set_xlim(-2, 152)
    ax.set_ylim(0.8420, 0.8425)
    ax.axhline(
        y=0.8421,
        color="#2ca02c",
        linestyle="--",
        linewidth=1.8,
        alpha=0.9,
        label="Frontier SOTA (0.8421)",
    )

    injection_milestones = load_rule_injection_milestones(ws_x, max_attempt=150)
    for i, (cycle, attempt) in enumerate(injection_milestones):
        x = attempt + 0.5
        ax.axvline(
            x=x,
            color="#d62728",
            linestyle="--",
            linewidth=1.8,
            alpha=0.85,
            zorder=4,
            label="Rule injection (X)" if i == 0 else None,
        )
        ax.text(
            x,
            0.84245 - (i % 3) * 0.00035,
            f"C{cycle}\n(inject @ {attempt})",
            rotation=90,
            va="top",
            ha="right",
            fontsize=8,
            color="#d62728",
            clip_on=True,
        )

    ax.grid(True, alpha=0.3)
    ax.legend(loc="lower right", framealpha=0.95, fontsize=9)

    out = base / "compare_first150_best_so_far.png"
    fig.tight_layout()
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved plot to {out}")


if __name__ == "__main__":
    main()
