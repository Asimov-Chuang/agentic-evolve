from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


VALID_ACTIONS = frozenset({"spawn_subtasks", "finish"})
VALID_INITIAL_SOURCES = frozenset({"global_best", "attempt_id", "path", "base"})
VALID_SEED_SOURCES = frozenset({"global"})


@dataclass
class InitialProgramSpec:
    source: str
    attempt_id: str | None = None
    path: str | None = None


@dataclass
class SeedArchiveSpec:
    source: str = "global"
    top_n: int | None = None
    attempt_ids: list[str] = field(default_factory=list)


@dataclass
class SubtaskSpec:
    id: str
    max_improvements: int | None = None
    agent_timeout_seconds: int | None = None
    initial_program: InitialProgramSpec | None = None
    seed_archive: SeedArchiveSpec | None = None
    evolve_focus: str | None = None
    prompt_append: str = ""


@dataclass
class BestRefSpec:
    source: str
    attempt_id: str


@dataclass
class HubPlan:
    action: str
    reasoning: str
    subtasks: list[SubtaskSpec] = field(default_factory=list)
    best_ref: BestRefSpec | None = None
    final_summary: str = ""


class HubPlanError(ValueError):
    pass


def _parse_initial_program(raw: Any) -> InitialProgramSpec | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise HubPlanError("initial_program must be an object")
    source = str(raw.get("source", "global_best"))
    if source not in VALID_INITIAL_SOURCES:
        raise HubPlanError(f"initial_program.source must be one of {sorted(VALID_INITIAL_SOURCES)}")
    return InitialProgramSpec(
        source=source,
        attempt_id=str(raw["attempt_id"]) if raw.get("attempt_id") else None,
        path=str(raw["path"]) if raw.get("path") else None,
    )


def _parse_seed_archive(raw: Any) -> SeedArchiveSpec | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise HubPlanError("seed_archive must be an object or null")
    source = str(raw.get("source", "global"))
    if source not in VALID_SEED_SOURCES:
        raise HubPlanError(f"seed_archive.source must be one of {sorted(VALID_SEED_SOURCES)}")
    attempt_ids = [str(x) for x in (raw.get("attempt_ids") or [])]
    top_n = int(raw["top_n"]) if raw.get("top_n") is not None else None
    if top_n is not None and top_n < 1:
        raise HubPlanError("seed_archive.top_n must be >= 1")
    return SeedArchiveSpec(source=source, top_n=top_n, attempt_ids=attempt_ids)


def _parse_subtask(raw: Any) -> SubtaskSpec:
    if not isinstance(raw, dict):
        raise HubPlanError("each subtask must be an object")
    sub_id = raw.get("id")
    if not sub_id or not isinstance(sub_id, str):
        raise HubPlanError("subtask.id is required")
    if not re.match(r"^[a-zA-Z0-9_-]+$", sub_id):
        raise HubPlanError(f"subtask.id invalid: {sub_id!r}")
    return SubtaskSpec(
        id=sub_id,
        max_improvements=int(raw["max_improvements"]) if raw.get("max_improvements") is not None else None,
        agent_timeout_seconds=(
            int(raw["agent_timeout_seconds"]) if raw.get("agent_timeout_seconds") is not None else None
        ),
        initial_program=_parse_initial_program(raw.get("initial_program")),
        seed_archive=_parse_seed_archive(raw.get("seed_archive")),
        evolve_focus=str(raw["evolve_focus"]) if raw.get("evolve_focus") else None,
        prompt_append=str(raw.get("prompt_append") or ""),
    )


def parse_hub_plan(raw: dict[str, Any]) -> HubPlan:
    action = str(raw.get("action", ""))
    if action not in VALID_ACTIONS:
        raise HubPlanError(f"action must be one of {sorted(VALID_ACTIONS)}")

    reasoning = str(raw.get("reasoning") or "")

    if action == "spawn_subtasks":
        subtasks_raw = raw.get("subtasks")
        if not isinstance(subtasks_raw, list) or not subtasks_raw:
            raise HubPlanError("spawn_subtasks requires non-empty subtasks array")
        subtasks = [_parse_subtask(s) for s in subtasks_raw]
        ids = [s.id for s in subtasks]
        if len(ids) != len(set(ids)):
            raise HubPlanError("duplicate subtask ids in plan")
        return HubPlan(action=action, reasoning=reasoning, subtasks=subtasks)

    best_ref_raw = raw.get("best_ref")
    if not isinstance(best_ref_raw, dict):
        raise HubPlanError("finish requires best_ref object")
    attempt_id = str(best_ref_raw.get("attempt_id", ""))
    if not attempt_id:
        raise HubPlanError("finish.best_ref.attempt_id is required")
    best_ref = BestRefSpec(
        source=str(best_ref_raw.get("source", "global")),
        attempt_id=attempt_id,
    )
    return HubPlan(
        action=action,
        reasoning=reasoning,
        best_ref=best_ref,
        final_summary=str(raw.get("final_summary") or ""),
    )


def load_hub_plan(path: Path) -> HubPlan:
    if not path.is_file():
        raise HubPlanError(f"hub plan not found: {path}")
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise HubPlanError("hub plan must be a JSON object")
    return parse_hub_plan(raw)


def extract_json_from_text(text: str) -> dict[str, Any]:
    """Best-effort extract JSON object from agent output."""
    text = text.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        parsed = json.loads(match.group())
        if isinstance(parsed, dict):
            return parsed
    raise HubPlanError("could not parse JSON from hub agent output")
