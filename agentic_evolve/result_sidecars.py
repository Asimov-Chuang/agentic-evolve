from __future__ import annotations

import json
from pathlib import Path
from typing import Any

RAW_ARTIFACT_FILENAME = "raw-artifact.json"

_RESULT_SIDECAR_KEYS: dict[str, str] = {
    "raw_artifacts": RAW_ARTIFACT_FILENAME,
    "stepwise_raw_artifacts": RAW_ARTIFACT_FILENAME,
}

AGENT_DISPLAY_OMIT_KEYS = frozenset({"construction", "per_case", "analysis"})


def json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _strip_construction_stepwise(construction: Any) -> Any:
    if not isinstance(construction, dict):
        return construction
    cleaned = dict(construction)
    cleaned.pop("stepwise_raw_artifacts", None)
    return cleaned


def strip_raw_artifact_keys(payload: dict) -> None:
    """Remove raw artifact keys from payload in place."""
    payload.pop("raw_artifacts", None)
    payload.pop("stepwise_raw_artifacts", None)
    if "construction" in payload:
        payload["construction"] = _strip_construction_stepwise(payload["construction"])


def remove_raw_artifact_file(attempt_dir: Path) -> None:
    (attempt_dir / RAW_ARTIFACT_FILENAME).unlink(missing_ok=True)


def finalize_attempt_result(
    attempt_dir: Path,
    payload: dict,
    *,
    store_raw_artifacts: bool,
) -> dict:
    """Persist or discard raw artifacts; return payload ready for result.json."""
    if store_raw_artifacts:
        for key, filename in _RESULT_SIDECAR_KEYS.items():
            if key not in payload:
                continue
            sidecar_path = attempt_dir / filename
            with open(sidecar_path, "w", encoding="utf-8") as f:
                json.dump(json_safe(payload.pop(key)), f, indent=2)
            break
        if "construction" in payload:
            payload["construction"] = _strip_construction_stepwise(payload["construction"])
    else:
        strip_raw_artifact_keys(payload)
        remove_raw_artifact_file(attempt_dir)
    return payload


def result_for_agent_display(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if key not in AGENT_DISPLAY_OMIT_KEYS}
