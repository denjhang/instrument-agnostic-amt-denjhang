#!/usr/bin/env python3
"""分轨模式转换 F:\\KwDownload\\song 中的 Fantasy Project 音乐

文件分布:
  Best Of/         - 14 个 mp3（含 2 个重复后缀 "1"）
  根目录/          - 12 个 mp3
  Fall In Love/    - 1 个 mp3
  Gimme Love/      - 3 个 mp3
  Higher/          - 1 个 mp3
  Корабли любви/   - 12 个 mp3
  总计: 43 个 mp3
"""

import io
import os
import subprocess
import sys
import time
from multiprocessing import Process, Queue
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

SOURCE = Path(r"F:\KwDownload\song")
TARGET = Path(r"D:\开源合集\开源 2022.9.14\芯片音乐\自制芯片音乐\MIDI识别合集\MIDI识别 2026\分轨模式")
SCRIPT = Path(__file__).parent / "stem_infer.py"
VENV_PY = Path(__file__).parent / ".venv" / "Scripts" / "python.exe"
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".ogg", ".opus", ".m4a", ".aac", ".wma", ".aiff", ".aif"}
WORKERS = 2
GPU_IDS = [0, 1]  # 2 张 GPU


def find_fantasy_files():
    """找出所有 Fantasy Project 音频文件"""
    files = []
    for f in sorted(SOURCE.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in AUDIO_EXTS:
            continue
        if "fantasy project" not in f.name.lower():
            continue
        files.append(f)
    return files


def get_missing_files(force=False):
    """返回待转换的文件。force=True 时返回全部文件（强制重新转换）"""
    all_files = find_fantasy_files()
    if force:
        return all_files
    missing = []
    for f in all_files:
        rel = f.relative_to(SOURCE)
        expected = TARGET / rel.with_suffix(".mid")
        if not expected.exists():
            missing.append(f)
        else:
            print(f"  已存在: {rel}")
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
        output_dir = TARGET / rel.parent
        output_dir.mkdir(parents=True, exist_ok=True)

        t0 = time.time()
        audio_size_mb = audio.stat().st_size / 1024 / 1024
        timeout = 1800 if audio_size_mb > 30 else 600

        result = subprocess.run(
            [str(VENV_PY), str(SCRIPT), "--audio", str(audio),
             "--output-root", str(output_dir), "--cleanup-stems", "--no-skip-drum"],
            capture_output=True, text=True, timeout=timeout,
            encoding='utf-8', errors='replace',
        )
        elapsed = time.time() - t0

        output_midi = output_dir / audio.with_suffix(".mid").name
        if output_midi.exists():
            result_queue.put(("OK", idx, total, rel, gpu_id, elapsed, ""))
        else:
            err = result.stderr[-500:] if result.stderr else result.stdout[-500:]
            result_queue.put(("FAIL", idx, total, rel, gpu_id, elapsed, err))


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="强制重新转换所有文件")
    args = parser.parse_args()

    print("=" * 60)
    print("Fantasy Project 分轨模式转换")
    print(f"源: {SOURCE}")
    print(f"目标: {TARGET}")
    print(f"{WORKERS} 个 worker, GPU {GPU_IDS}")
    print("=" * 60)

    all_files = find_fantasy_files()
    files = get_missing_files(force=args.force)
    print(f"\nFantasy Project 总文件: {len(all_files)}")
    print(f"待转换: {len(files)}")

    if len(files) == 0:
        print("全部完成!")
        return

    print(f"\n待转换文件:")
    for f in files:
        print(f"  {f.relative_to(SOURCE)}")

    task_queue = Queue()
    result_queue = Queue()

    for i, f in enumerate(files):
        task_queue.put((i + 1, len(files), f))

    workers = []
    for i in range(WORKERS):
        gpu_id = GPU_IDS[i % len(GPU_IDS)]
        p = Process(target=worker, args=(task_queue, result_queue, gpu_id), daemon=True)
        p.start()
        workers.append(p)
        print(f"  Worker {i+1} -> GPU {gpu_id}")

    for _ in range(WORKERS):
        task_queue.put(None)

    done = 0
    failed = 0
    t_start = time.time()

    while done + failed < len(files):
        try:
            item = result_queue.get(timeout=30)
        except:
            continue

        status = item[0]
        idx, total, rel, gpu, elapsed = item[1], item[2], item[3], item[4], item[5]
        err_msg = item[6] if len(item) > 6 else ""

        if status == "OK":
            done += 1
        else:
            failed += 1
            if err_msg:
                print(f"  ERR: {err_msg[:300]}")

        elapsed_total = time.time() - t_start
        rate = (done + failed) / elapsed_total * 60 if elapsed_total > 0 else 0
        remain = (total - done - failed) / rate if rate > 0 else 0
        print(f"  [{status}] [{done+failed}/{total}] GPU{gpu} {str(rel)[:60]} "
              f"({elapsed:.0f}s) {rate:.1f}/min ~{remain:.0f}min left")

    print("\n" + "=" * 60)
    print(f"完成: {done}, 失败: {failed}, 总计: {len(files)}")
    print(f"耗时: {(time.time()-t_start)/60:.1f} 分钟")


if __name__ == "__main__":
    main()
