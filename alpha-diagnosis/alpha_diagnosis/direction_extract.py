from __future__ import annotations

import json
from pathlib import Path
from typing import List

from alpha_diagnosis.rule_extract import RuleSpec


def extract_directions(path: Path, *, expected_count: int) -> List[RuleSpec]:
    """Parse directions.json produced by the history-review agent."""
    if not path.is_file():
        raise ValueError(f"directions.json not found: {path}")

    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    directions = raw.get("directions")
    if not isinstance(directions, list):
        raise ValueError(f"directions.json must contain a 'directions' list: {path}")

    rules: List[RuleSpec] = []
    for i, entry in enumerate(directions):
        if not isinstance(entry, dict):
            raise ValueError(f"directions[{i}] must be an object in {path}")
        name = str(entry.get("name", "")).strip()
        description = str(entry.get("description", "")).strip()
        if not name:
            raise ValueError(f"directions[{i}].name is empty in {path}")
        if not description:
            raise ValueError(f"directions[{i}].description is empty in {path}")
        rules.append(RuleSpec(index=i, name=name, description=description))

    if len(rules) != expected_count:
        raise ValueError(
            f"Expected exactly {expected_count} direction(s) in {path}, got {len(rules)}"
        )
    return rules
