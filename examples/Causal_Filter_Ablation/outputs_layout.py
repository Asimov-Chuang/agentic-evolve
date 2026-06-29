"""Helpers for causal-filter ablation output directory layout."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

SETTING_ORDER = ("score_only", "0pct", "0pct_metric_meanings")
LEGACY_SETTING_DIRS = frozenset(SETTING_ORDER)

BLIND_GROUP_TO_SETTING: dict[str, str] = {
    "cond_a": "score_only",
    "cond_b": "0pct",
    "cond_c": "0pct_metric_meanings",
}
SETTING_TO_BLIND_GROUP: dict[str, str] = {
    setting: group for group, setting in BLIND_GROUP_TO_SETTING.items()
}
BLIND_GROUP_DIRS = frozenset(BLIND_GROUP_TO_SETTING)
OUTPUT_GROUP_DIRS = LEGACY_SETTING_DIRS | BLIND_GROUP_DIRS

BLIND_PROJECT_PREFIX = "ablation_run"
_LEGACY_REPLICATE_PAT = re.compile(
    r"^causal_filter_(?:(score_only)_(\d+)|(0pct|0pct_metric_meanings)_(\d+))$"
)
_BLIND_REPLICATE_PAT = re.compile(rf"^{BLIND_PROJECT_PREFIX}_(\d+)$")


def blind_project_name(run_id: int) -> str:
    return f"{BLIND_PROJECT_PREFIX}_{run_id}"


def output_group_for_setting(setting: str, *, blind: bool = True) -> str:
    if blind and setting in SETTING_TO_BLIND_GROUP:
        return SETTING_TO_BLIND_GROUP[setting]
    return setting


def setting_for_output_group(group: str) -> str | None:
    if group in BLIND_GROUP_TO_SETTING:
        return BLIND_GROUP_TO_SETTING[group]
    if group in LEGACY_SETTING_DIRS:
        return group
    return None


def parse_project_dir(name: str) -> tuple[str, int] | None:
    m = _LEGACY_REPLICATE_PAT.match(name)
    if not m:
        return None
    if m.group(1):
        return m.group(1), int(m.group(2))
    return m.group(3), int(m.group(4))


def parse_blind_project_dir(group: str, name: str) -> tuple[str, int] | None:
    setting = setting_for_output_group(group)
    if setting is None:
        return None
    m = _BLIND_REPLICATE_PAT.match(name)
    if not m:
        return None
    return setting, int(m.group(1))


def setting_for_project(name: str) -> str | None:
    parsed = parse_project_dir(name)
    return parsed[0] if parsed else None


def resolve_project_setting(group: str, project_name: str) -> tuple[str, int] | None:
    blind = parse_blind_project_dir(group, project_name)
    if blind is not None:
        return blind
    legacy = parse_project_dir(project_name)
    if legacy is not None and legacy[0] == setting_for_output_group(group):
        return legacy
    if legacy is not None and group in LEGACY_SETTING_DIRS and legacy[0] == group:
        return legacy
    return None


def nested_project_dir(
    outputs_root: Path,
    setting: str,
    project_name: str,
    *,
    blind: bool = True,
) -> Path:
    group = output_group_for_setting(setting, blind=blind)
    return outputs_root / group / project_name


def iter_project_dirs(outputs_root: Path) -> Iterator[tuple[str, Path]]:
    root = Path(outputs_root)
    if not root.is_dir():
        return

    seen: set[Path] = set()

    for group in sorted(BLIND_GROUP_DIRS):
        group_dir = root / group
        if not group_dir.is_dir():
            continue
        for project_dir in sorted(group_dir.iterdir()):
            if not project_dir.is_dir():
                continue
            parsed = parse_blind_project_dir(group, project_dir.name)
            if parsed is None:
                continue
            seen.add(project_dir.resolve())
            yield parsed[0], project_dir

    for setting in SETTING_ORDER:
        setting_dir = root / setting
        if not setting_dir.is_dir():
            continue
        for project_dir in sorted(setting_dir.iterdir()):
            if not project_dir.is_dir():
                continue
            parsed = parse_project_dir(project_dir.name)
            if parsed is None or parsed[0] != setting:
                continue
            resolved = project_dir.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            yield setting, project_dir

    for project_dir in sorted(root.iterdir()):
        if not project_dir.is_dir() or project_dir.name in OUTPUT_GROUP_DIRS:
            continue
        parsed = parse_project_dir(project_dir.name)
        if parsed is None:
            continue
        resolved = project_dir.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        yield parsed[0], project_dir