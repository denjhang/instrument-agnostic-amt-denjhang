#!/usr/bin/env python3
"""Reorganize root-level MIDI files into correct subdirectories.

Scans the target directory for MIDI files in the root,
finds their source audio files, and moves them to the
correct subdirectory matching the source structure.
"""

import shutil
from pathlib import Path
from collections import defaultdict


def reorganize(target_dir: Path, source_dir: Path, dry_run: bool = True):
    root_mids = sorted(target_dir.glob("*.mid"))
    if not root_mids:
        print("No root-level MIDI files found. Nothing to do.")
        return

    print(f"Found {len(root_mids)} root-level MIDI files to reorganize")

    moved = 0
    skipped = 0
    not_found = 0
    conflicts = 0

    for mid in root_mids:
        stem = mid.stem
        found_src = None

        for ext in [".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".aiff", ".aif", ".opus"]:
            matches = list(source_dir.rglob(f"{stem}{ext}"))
            if matches:
                found_src = matches[0]
                break

        if not found_src:
            print(f"  [NOT FOUND] {mid.name}")
            not_found += 1
            continue

        rel = found_src.relative_to(source_dir)
        dest_dir = target_dir / rel.parent
        dest_path = dest_dir / mid.name

        if dest_path.exists():
            # Already exists in correct location — remove root duplicate
            print(f"  [CONFLICT] {mid.name} already exists at {dest_path}")
            conflicts += 1
            if not dry_run:
                mid.unlink()
                print(f"    Removed root duplicate")
            continue

        dest_dir.mkdir(parents=True, exist_ok=True)

        if dry_run:
            print(f"  [MOVE] {mid.name} -> {rel.parent}/")
        else:
            shutil.move(str(mid), str(dest_path))
            print(f"  [MOVED] {mid.name} -> {rel.parent}/")

        moved += 1

    print(f"\n{'DRY RUN - ' if dry_run else ''}Summary:")
    print(f"  Would move: {moved}")
    print(f"  Conflicts (root duplicate removed): {conflicts}")
    print(f"  Source not found: {not_found}")
    print(f"  Total: {len(root_mids)}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Reorganize root-level MIDI files into subdirectories")
    parser.add_argument("--source", type=Path, default=r"E:\存储器备份\2024.10.30 音乐卡16G")
    parser.add_argument("--target", type=Path,
                        default=r"D:\开源合集\开源 2022.9.14\芯片音乐\自制芯片音乐\MIDI识别合集\MIDI识别 2026\分轨模式")
    parser.add_argument("--run", action="store_true", help="Actually move files (default: dry run)")
    args = parser.parse_args()

    reorganize(args.target, args.source, dry_run=not args.run)
