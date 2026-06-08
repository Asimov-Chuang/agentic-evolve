from __future__ import annotations

import json
from pathlib import Path
from typing import List, Set, Tuple

import matplotlib.pyplot as plt

from alpha_diagnosis.orchestrator import AlphaState, _state_path


def _load_scores(archive: Path) -> Tuple[List[int], List[float]]:
    attempts: List[int] = []
    scores: List[float] = []
    for p in sorted(archive.glob("attempt_*/result.json")):
        n = int(p.parent.name.split("_")[1])
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("is_valid", True):
            attempts.append(n)
            scores.append(float(d["score"]))
    return attempts, scores


def _dataset_attempts_from_symlinks(dataset_dir: Path) -> Set[int]:
    if not dataset_dir.is_dir():
        return set()
    out: Set[int] = set()
    for p in dataset_dir.iterdir():
        if p.name.startswith("attempt_"):
            out.add(int(p.name.split("_")[1]))
    return out


def _rule_inspired_attempts(state_path: Path) -> Set[int]:
    if not state_path.is_file():
        return set()
    state = AlphaState.load(state_path)
    inspired: Set[int] = set()
    for entry in state.rule_inspired_ranges:
        first = int(entry["first"])
        last = int(entry["last"])
        inspired.update(range(first, last + 1))
    return inspired


def _diagnosis_milestones(workspace: Path) -> List[tuple[int, int]]:
    """Return (cycle, stuck_attempt) for each stuck detection."""
    trajectory = workspace / "score_trajectory.jsonl"
    if trajectory.is_file():
        stuck_attempts: List[int] = []
        cycles: List[int] = []
        for line in trajectory.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            event = rec.get("event")
            if event == "stuck":
                count = rec.get("attempt_count")
                if count is not None:
                    stuck_attempts.append(int(count))
            elif event == "discovery_start":
                cycles.append(int(rec.get("cycle", len(cycles) + 1)))
        if stuck_attempts:
            return [
                (cycles[i] if i < len(cycles) else i + 1, stuck_attempts[i])
                for i in range(len(stuck_attempts))
            ]

    state_path = _state_path(workspace)
    if state_path.is_file():
        state = AlphaState.load(state_path)
        if state.rule_inspired_ranges:
            return [
                (int(entry["cycle"]), int(entry["first"]))
                for entry in state.rule_inspired_ranges
            ]
    return []


def plot_best_so_far(
    workspace: Path,
    *,
    dataset_dir: Path | None = None,
    output_path: Path | None = None,
) -> Path:
    archive = workspace / "archive"
    attempts, scores = _load_scores(archive)
    if not attempts:
        raise ValueError(f"No attempts in {archive}")

    best_so_far: List[float] = []
    running = float("-inf")
    for s in scores:
        running = max(running, s)
        best_so_far.append(running)

    state_path = _state_path(workspace)
    rule_inspired = _rule_inspired_attempts(state_path)
    dataset_attempts = _dataset_attempts_from_symlinks(dataset_dir) if dataset_dir else set()

    regular_x, regular_y = [], []
    dataset_x, dataset_y = [], []
    rule_x, rule_y = [], []

    for a, s in zip(attempts, scores):
        if a in rule_inspired:
            rule_x.append(a)
            rule_y.append(s)
        elif a in dataset_attempts:
            dataset_x.append(a)
            dataset_y.append(s)
        else:
            regular_x.append(a)
            regular_y.append(s)

    diagnosis_milestones = _diagnosis_milestones(workspace)

    fig, ax = plt.subplots(figsize=(10.5, 5.8))
    ax.scatter(regular_x, regular_y, s=18, c="#b0b0b0", alpha=0.55, zorder=2, label="Per attempt score")
    if dataset_x:
        ax.scatter(
            dataset_x,
            dataset_y,
            s=34,
            c="#9467bd",
            alpha=0.95,
            zorder=4,
            edgecolors="white",
            linewidths=0.7,
            label=f"Rule regression dataset (n={len(dataset_x)})",
        )
    if rule_x:
        ax.scatter(
            rule_x,
            rule_y,
            s=34,
            c="#ff7f0e",
            alpha=0.95,
            zorder=5,
            edgecolors="white",
            linewidths=0.7,
            label="Rule-inspired submissions",
        )
    ax.step(attempts, best_so_far, where="post", color="#1f77b4", linewidth=2.2, zorder=3, label="Best so far")

    ymax = max(scores) * 1.05
    for i, (cycle, stuck_attempt) in enumerate(diagnosis_milestones):
        x = stuck_attempt + 0.5
        ax.axvline(
            x=x,
            color="#d62728",
            linestyle="--",
            linewidth=1.8,
            alpha=0.85,
            zorder=4,
            label="Stuck detected" if i == 0 else None,
        )
        ax.text(
            x,
            ymax * (0.97 - (i % 4) * 0.06),
            f"C{cycle}\n(stuck @ {stuck_attempt})",
            rotation=90,
            va="top",
            ha="right",
            fontsize=8,
            color="#d62728",
            clip_on=True,
        )

    title = workspace.name + " — Best score so far vs attempt"
    ax.set_title(title, fontsize=13, pad=12)
    ax.set_xlabel("Attempt number", fontsize=11)
    ax.set_ylabel("Score", fontsize=11)
    ax.set_xlim(-2, max(attempts) + 3)
    ax.set_ylim(0, ymax)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="lower right", framealpha=0.95, fontsize=9)

    out = output_path or (workspace / "best_so_far_vs_attempts.png")
    fig.tight_layout()
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out
