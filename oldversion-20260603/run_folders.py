#!/usr/bin/env python3
"""按文件夹逐个转换，实时输出进度"""

import io
import subprocess
import sys
import time
from pathlib import Path

# 修复 Windows GBK 终端编码问题
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

SOURCE = Path(r"E:\存储器备份\2024.10.30 音乐卡16G")
TARGET = Path(r"D:\开源合集\开源 2022.9.14\芯片音乐\自制芯片音乐\MIDI识别合集\MIDI识别 2026\分轨模式")
SCRIPT = Path(__file__).parent / "stem_infer.py"
VENV_PY = Path(__file__).parent / ".venv" / "Scripts" / "python.exe"
EXCLUDE = {"vgm", "midi音乐"}
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".ogg", ".opus", ".m4a", ".aac", ".wma", ".aiff", ".aif"}


def get_missing():
    """返回未完成的文件列表，按目录分组"""
    from collections import defaultdict
    dirs = defaultdict(list)
    for f in sorted(SOURCE.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in AUDIO_EXTS:
            continue
        try:
            rel = f.relative_to(SOURCE)
            if any(p in EXCLUDE for p in rel.parts):
                continue
        except ValueError:
            continue
        expected = TARGET / rel.with_suffix(".mid")
        if not expected.exists():
            dirs[str(rel.parent)].append(f)
    return dirs


if __name__ == "__main__":
    dirs = get_missing()
    total_files = sum(len(v) for v in dirs.values())
    print(f"共 {len(dirs)} 个目录, {total_files} 个文件待转换")
    print("=" * 60)

    done = 0
    failed = []
    t0 = time.time()

    for i, (dir_rel, files) in enumerate(sorted(dirs.items()), 1):
        dir_files = len(files)
        print(f"\n[{i}/{len(dirs)}] {dir_rel} ({dir_files} files)")

        for audio in files:
            rel = audio.relative_to(SOURCE)
            output_dir = TARGET / rel.parent
            output_dir.mkdir(parents=True, exist_ok=True)

            result = subprocess.run(
                [str(VENV_PY), str(SCRIPT), "--audio", str(audio),
                 "--output-root", str(output_dir)],
                text=True, timeout=1800,
            )

            expected_midi = output_dir / audio.with_suffix(".mid").name
            if expected_midi.exists():
                done += 1
                elapsed = time.time() - t0
                rate = done / elapsed * 60 if elapsed > 0 else 0
                remain = (total_files - done) / rate if rate > 0 else 0
                print(f"  OK [{done}/{total_files}] {audio.name} "
                      f"({rate:.1f}/min, ~{remain:.0f}min left)")
            else:
                failed.append(str(audio))
                print(f"  FAIL {audio.name}")

    print("\n" + "=" * 60)
    print(f"完成: {done}/{total_files}")
    print(f"失败: {len(failed)}")
    if failed:
        for f in failed:
            print(f"  {f}")
