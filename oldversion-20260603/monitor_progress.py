#!/usr/bin/env python3
"""每5分钟扫描一次分轨模式转换进度"""

import time
from pathlib import Path

SOURCE = Path(r"E:\存储器备份\2024.10.30 音乐卡16G")
TARGET = Path(r"D:\开源合集\开源 2022.9.14\芯片音乐\自制芯片音乐\MIDI识别合集\MIDI识别 2026\分轨模式")
EXCLUDE = {"vgm", "midi音乐"}
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".ogg", ".opus", ".m4a", ".aac", ".wma", ".aiff", ".aif"}
INTERVAL = 300  # 5分钟

def count_total():
    total = 0
    for f in SOURCE.rglob("*"):
        if f.is_file() and f.suffix.lower() in AUDIO_EXTS:
            try:
                rel = f.relative_to(SOURCE)
                if any(p in EXCLUDE for p in rel.parts):
                    continue
                total += 1
            except ValueError:
                pass
    return total

def scan():
    total = count_total()
    done = sum(1 for _ in TARGET.rglob("*.mid"))
    root = sum(1 for _ in TARGET.glob("*.mid"))
    sub = done - root
    pct = done / total * 100 if total else 0
    remaining = total - done
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {done}/{total} ({pct:.1f}%) | 子目录:{sub} 根目录:{root} | 剩余:{remaining}")

if __name__ == "__main__":
    print(f"监控启动，每{INTERVAL//60}分钟扫描一次，按 Ctrl+C 停止")
    print(f"源: {SOURCE}")
    print(f"目标: {TARGET}")
    print("-" * 60)
    try:
        while True:
            scan()
            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        scan()
        print("\n监控已停止")
