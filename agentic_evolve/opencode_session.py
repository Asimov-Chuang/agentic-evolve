from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

SESSION_ID_PATTERN = re.compile(r"\bses_[A-Za-z0-9]+\b")
SESSION_FILENAME = "opencode_session.json"


def extract_session_id(text: str) -> str | None:
    match = SESSION_ID_PATTERN.search(text or "")
    return match.group(0) if match else None


def load_session_id(workspace_dir: Path) -> str | None:
    path = workspace_dir / SESSION_FILENAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    session_id = data.get("session_id")
    return str(session_id) if session_id else None


def save_session_id(workspace_dir: Path, session_id: str) -> None:
    path = workspace_dir / SESSION_FILENAME
    payload = {
        "session_id": session_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def update_session_id_from_output(workspace_dir: Path, *outputs: str) -> str | None:
    for text in outputs:
        session_id = extract_session_id(text)
        if session_id:
            save_session_id(workspace_dir, session_id)
            return session_id
    return load_session_id(workspace_dir)


def backfill_session_id_from_logs(workspace_dir: Path) -> str | None:
    """Recover a saved session id from prior agent logs when JSON is missing."""
    existing = load_session_id(workspace_dir)
    if existing:
        return existing
    for log_name in ("agent_stdout.log", "agent_stderr.log"):
        path = workspace_dir / log_name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        session_id = extract_session_id(text)
        if session_id:
            save_session_id(workspace_dir, session_id)
            return session_id
    return None
