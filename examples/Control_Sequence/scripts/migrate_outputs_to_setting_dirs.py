#!/usr/bin/env python3
"""Move legacy flat replicate outputs into setting subfolders under outputs/."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

EXAMPLE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUTS = EXAMPLE_DIR / ".run_configs" / "outputs"

sys.path.insert(0, str(EXAMPLE_DIR))
from outputs_layout import (  # noqa: E402
    LEGACY_SETTING_DIRS,
    OUTPUT_GROUP_DIRS,
    nested_project_dir,
    parse_project_dir,
    setting_for_project,
)


def migrate(outputs_root: Path, *, dry_run: bool = False) -> int:
    moved = 0
    skipped = 0

    for entry in sorted(outputs_root.iterdir()):
        if not entry.is_dir() or entry.name in OUTPUT_GROUP_DIRS:
            continue
        setting = setting_for_project(entry.name)
        if setting is None:
            continue
        dest = nested_project_dir(outputs_root, setting, entry.name)
        if dest.exists():
            print(f"skip (dest exists): {entry.name} -> {dest.relative_to(outputs_root)}")
            skipped += 1
            continue
        print(f"move: {entry.name} -> {dest.relative_to(outputs_root)}")
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(entry), str(dest))
        moved += 1

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
