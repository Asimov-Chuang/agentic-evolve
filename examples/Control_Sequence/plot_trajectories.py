"""Plot best_score trajectories for feedback-noise ablation runs."""

from __future__ import annotations

import json
from pathlib import Path

PROJECTS = [
    ("score_only", "feedback_ablation_score_only"),
    ("0pct_noise", "feedback_ablation_0pct"),
    ("50pct_noise", "feedback_ablation_50pct"),
    ("80pct_noise", "feedback_ablation_80pct"),
]


def load_trajectory(path: Path) -> list[tuple[int, float]]:
    points: list[tuple[int, float]] = []
    if not path.is_file():
        return points
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("event") != "submit":
            continue
        points.append((int(row["submission_index"]), float(row["best_score"])))
    return points


def main() -> None:
    base = Path(__file__).resolve().parent / "outputs"
    for label, project in PROJECTS:
        traj = base / project / "score_trajectory.jsonl"
        points = load_trajectory(traj)
        if not points:
            print(f"{label}: (no data — run config first)")
            continue
        last_idx, last_score = points[-1]
        print(f"{label}: {len(points)} submissions, best_score={last_score:.6f} at #{last_idx}")


if __name__ == "__main__":
    main()
