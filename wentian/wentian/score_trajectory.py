from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TRAJECTORY_FILENAME = "score_trajectory.jsonl"


def trajectory_path(output_root: Path) -> Path:
    return output_root / "wentian" / TRAJECTORY_FILENAME


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_event(output_root: Path, event: str, **fields: Any) -> None:
    path = trajectory_path(output_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    row: dict[str, Any] = {"event": event, "ts": _now()}
    row.update(fields)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
