#!/usr/bin/env python3
"""快速模式并行转换 F:\KwDownload\song 中 2026年6月的文件"""

import io
import os
import subprocess
import sys
import time
from datetime import datetime
from multiprocessing import Process, Queue
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

SOURCE = Path(r"F:\KwDownload\song")
TARGET = Path(r"D:\开源合集\开源 2022.9.14\芯片音乐\自制芯片音乐\MIDI识别合集\MIDI识别 2026\快速模式")
SCRIPT = Path(__file__).parent / "infer.py"
VENV_PY = Path(__file__).parent / ".venv" / "Scripts" / "python.exe"
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".ogg", ".opus", ".m4a", ".aac", ".wma", ".aiff", ".aif"}
WORKERS = 4
GPU = 1  # 用 GPU 1，GPU 0 给分轨模式


def get_june_2026_files():
    """找出 2026年6月修改的音频文件"""
    files = []
    for f in sorted(SOURCE.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in AUDIO_EXTS:
            continue
        stat = f.stat()
        mt = datetime.fromtimestamp(stat.st_mtime)
        if mt.year == 2026 and mt.month == 6:
            files.append(f)
    return files


def get_missing_files():
    """只返回尚未转换的文件"""
    all_files = get_june_2026_files()
    missing = []
    for f in all_files:
        rel = f.relative_to(SOURCE)
        expected = TARGET / rel.with_suffix(".mid")
        if not expected.exists():
            missing.append(f)
    return missing


def worker(task_queue, result_queue, gpu_id):
    """每个 worker 绑定一个 GPU"""
    os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_id)
    while True:
        item = task_queue.get()
        if item is None:
            break
        idx, total, audio = item
        rel = audio.relative_to(SOURCE)
        output_midi = TARGET / rel.with_suffix(".mid")
        output_midi.parent.mkdir(parents=True, exist_ok=True)

        t0 = time.time()
        audio_size_mb = audio.stat().st_size / 1024 / 1024
        timeout = 1800 if audio_size_mb > 30 else 600

        result = subprocess.run(
            [str(VENV_PY), str(SCRIPT), "--audio", str(audio),
             "--output-midi", str(output_midi)],
            capture_output=True, text=True, timeout=timeout,
            encoding='utf-8', errors='replace',
        )
        elapsed = time.time() - t0

        if output_midi.exists():
            result_queue.put(("OK", idx, total, audio.name, gpu_id, elapsed, ""))
        else:
            err = result.stderr[-500:] if result.stderr else ""
            result_queue.put(("FAIL", idx, total, audio.name, gpu_id, elapsed, err))


def main():
    files = get_missing_files()
    total = len(files)
    all_june = len(get_june_2026_files())
    already_done = all_june - total
    print(f"2026年6月文件: {all_june} 个, 已完成: {already_done}, 待转换: {total}")
    print(f"源: {SOURCE}")
    print(f"目标: {TARGET}")
    print(f"{WORKERS} 个 worker, GPU {GPU}")
    print("=" * 60)

    if total == 0:
        print("全部完成!")
        return

    task_queue = Queue()
    result_queue = Queue()

    for i, f in enumerate(files):
        task_queue.put((i + 1, total, f))

    workers = []
    for i in range(WORKERS):
        p = Process(target=worker, args=(task_queue, result_queue, GPU), daemon=True)
        p.start()
        workers.append(p)
        print(f"  Worker {i+1} -> GPU {GPU}")

    for _ in range(WORKERS):
        task_queue.put(None)

    done = 0
    failed = 0
    t_start = time.time()

    while done + failed < total:
        try:
            item = result_queue.get(timeout=10)
        except:
            continue

        status = item[0]
        idx, _, name, gpu, elapsed = item[1], item[2], item[3], item[4], item[5]
        err_msg = item[6] if len(item) > 6 else ""

        if status == "OK":
            done += 1
        else:
            failed += 1
            if err_msg:
                print(f"  ERR: {err_msg[:200]}")

        elapsed_total = time.time() - t_start
        rate = (done + failed) / elapsed_total * 60 if elapsed_total > 0 else 0
        remain = (total - done - failed) / rate if rate > 0 else 0
        print(f"  [{status}] [{done+failed}/{total}] GPU{gpu} {name[:50]} "
              f"({elapsed:.0f}s) {rate:.1f}/min ~{remain:.0f}min left")

    print("\n" + "=" * 60)
    print(f"完成: {done}, 失败: {failed}, 总计: {total}")
    print(f"耗时: {(time.time()-t_start)/60:.1f} 分钟")


if __name__ == "__main__":
    main()
