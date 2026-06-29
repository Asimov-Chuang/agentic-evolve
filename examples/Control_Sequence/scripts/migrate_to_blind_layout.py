#!/usr/bin/env python3
"""Move legacy setting-named outputs into blind cond_* / ablation_run_* layout."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

EXAMPLE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUTS = EXAMPLE_DIR / ".run_configs" / "outputs"

sys.path.insert(0, str(EXAMPLE_DIR))
from outputs_layout import (  # noqa: E402
    BLIND_GROUP_TO_SETTING,
    LEGACY_SETTING_DIRS,
    blind_project_name,
    nested_project_dir,
    parse_project_dir,
    setting_for_output_group,
)

LEGACY_TO_BLIND = {
    setting: group for group, setting in BLIND_GROUP_TO_SETTING.items()
}


def migrate(outputs_root: Path, *, dry_run: bool = False) -> int:
    moved = 0
    skipped = 0

    for group_dir in sorted(outputs_root.iterdir()):
        if not group_dir.is_dir():
            continue
        setting = setting_for_output_group(group_dir.name)
        if setting is None or group_dir.name in BLIND_GROUP_TO_SETTING:
            continue

        blind_group = LEGACY_TO_BLIND[setting]
        for project_dir in sorted(group_dir.iterdir()):
            if not project_dir.is_dir():
                continue
            parsed = parse_project_dir(project_dir.name)
            if parsed is None or parsed[0] != setting:
                continue
            run_id = parsed[1]
            dest = nested_project_dir(
                outputs_root,
                setting,
                blind_project_name(run_id),
                blind=True,
            )
            if dest.exists():
                print(
                    f"skip (dest exists): {project_dir.relative_to(outputs_root)} "
                    f"-> {dest.relative_to(outputs_root)}"
                )
                skipped += 1
                continue
            print(
                f"move: {project_dir.relative_to(outputs_root)} "
                f"-> {dest.relative_to(outputs_root)}"
            )
            if not dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(project_dir), str(dest))
            moved += 1

        if not dry_run and group_dir.is_dir() and not any(group_dir.iterdir()):
            group_dir.rmdir()
            print(f"removed empty dir: {group_dir.relative_to(outputs_root)}")

    print(f"done: moved={moved} skipped={skipped} dry_run={dry_run}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--outputs",
        type=Path,
        default=DEFAULT_OUTPUTS,
        help="outputs root (default: .run_configs/outputs)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.outputs.is_dir():
        print(f"error: outputs directory not found: {args.outputs}", file=sys.stderr)
        return 1
    return migrate(args.outputs, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
