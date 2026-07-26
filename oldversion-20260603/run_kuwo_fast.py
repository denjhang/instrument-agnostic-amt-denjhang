#!/usr/bin/env python3
"""快速模式并行转换 F:\\KwDownload\\song 中 2026-07-25 23:00 之后新增的专辑

筛选规则: 顶层专辑目录内任一音频文件 mtime >= 2026-07-25 23:00，则整个目录纳入。
输出: D:\\...\\MIDI识别 2026\\酷我\\<专辑名>\\<曲名>.mid  （保留完整子目录结构）

用法:
  .venv\\Scripts\\python.exe run_kuwo_fast.py            # 只转缺失的（断点续跑）
  .venv\\Scripts\\python.exe run_kuwo_fast.py --force     # 强制全部重转
  .venv\\Scripts\\python.exe run_kuwo_fast.py --dry-run   # 只列出待转换，不执行
"""

import io
import os
import subprocess
import sys
import time
from datetime import datetime
from multiprocessing import Process, Queue
from pathlib import Path

if getattr(sys.stdout, 'encoding', '') != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

SOURCE = Path(r"F:\KwDownload\song")
TARGET = Path(r"D:\开源合集\开源 2022.9.14\芯片音乐\自制芯片音乐\MIDI识别合集\MIDI识别 2026\酷我")
SCRIPT = Path(__file__).parent / "infer.py"
VENV_PY = Path(__file__).parent / ".venv" / "Scripts" / "python.exe"
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".ogg", ".opus", ".m4a", ".aac", ".wma", ".aiff", ".aif"}

# 筛选截止时间: 2026-07-25 23:00:00（含今晚 23:00 之后新下载的内容）
CUTOFF = datetime(2026, 7, 25, 23, 0, 0)

WORKERS = 1
GPUS = [0]  # 单 worker 串行（GPU1 留给 pianotrans；多 worker 并发会触发 checkpoint/CUDA 竞争导致 FAIL）


def find_recent_audio():
    """返回 [(audio_path, rel_to_source), ...]，rel 保留完整子目录结构"""
    # 先确定哪些顶层专辑目录符合条件（任一音频 mtime >= CUTOFF）
    qualifying_dirs = set()
    for d in SOURCE.iterdir():
        if not d.is_dir():
            continue
        for f in d.rglob("*"):
            if f.is_file() and f.suffix.lower() in AUDIO_EXTS:
                if datetime.fromtimestamp(f.stat().st_mtime) >= CUTOFF:
                    qualifying_dirs.add(d.name)
                    break

    files = []
    for d in SOURCE.iterdir():
        if not d.is_dir() or d.name not in qualifying_dirs:
            continue
        for f in sorted(d.rglob("*")):
            if f.is_file() and f.suffix.lower() in AUDIO_EXTS:
                files.append(f)
    return files, qualifying_dirs


def _safe_filename(name, max_len):
    """超长文件名截断 + 短哈希后缀，避免碰撞且保证可读"""
    if len(name) <= max_len:
        return name
    import hashlib
    stem, ext = name.rsplit(".", 1) if "." in name else (name, "")
    digest = hashlib.md5(name.encode("utf-8")).hexdigest()[:8]
    keep = max(8, max_len - len(ext) - 1 - len(digest) - 1)  # stem...hash.ext
    return f"{stem[:keep]}~{digest}.{ext}"


def expected_output(audio):
    """源文件 -> 目标 .mid 路径，保留完整相对目录结构。
    若完整路径超过 Windows MAX_PATH 限制，则截短文件名（目录结构保持不变）。"""
    rel = audio.relative_to(SOURCE)
    rel_mid = rel.with_suffix(".mid")
    full = TARGET / rel_mid
    MAX_PATH = 240  # 留余量，低于 Windows 260 限制
    if len(str(full)) <= MAX_PATH:
        return full
    # 只截短文件名部分，目录结构（专辑子目录）保持不变
    parent = full.parent
    safe_name = _safe_filename(rel_mid.name, MAX_PATH - len(str(parent)) - 1)
    return parent / safe_name


def get_missing_files(force=False):
    all_files, qual = find_recent_audio()
    if force:
        return all_files, qual
    missing = []
    for f in all_files:
        if not expected_output(f).exists():
            missing.append(f)
    return missing, qual


def worker(task_queue, result_queue, gpu_id):
    # 显式构造子进程环境，确保 CUDA_VISIBLE_DEVICES 一定传给 infer.py
    child_env = os.environ.copy()
    child_env["CUDA_VISIBLE_DEVICES"] = str(gpu_id)
    child_env["PYTHONUNBUFFERED"] = "1"
    while True:
        item = task_queue.get()
        if item is None:
            break
        idx, total, audio = item
        output_midi = expected_output(audio)
        output_midi.parent.mkdir(parents=True, exist_ok=True)

        t0 = time.time()
        audio_size_mb = audio.stat().st_size / 1024 / 1024
        timeout = 1800 if audio_size_mb > 30 else 600

        last_err = ""
        # 路径已由 expected_output() 保证安全；偶发失败（CUDA/IO 抖动）才重试
        for attempt in range(3):
            result = subprocess.run(
                [str(VENV_PY), str(SCRIPT), "--audio", str(audio),
                 "--output-midi", str(output_midi)],
                capture_output=True, text=True, timeout=timeout,
                encoding='utf-8', errors='replace', env=child_env,
                cwd=str(Path(__file__).parent),
            )
            if output_midi.exists() and output_midi.stat().st_size > 100:
                break
            combined = (result.stderr or "") + (result.stdout or "")
            last_err = combined[-400:]
            # 路径过长/确定性错误不重试，避免浪费时间
            if "FileNotFoundError" in combined and "open(filename" in combined:
                break
            time.sleep(2)
        elapsed = time.time() - t0
        elapsed = time.time() - t0

        if output_midi.exists() and output_midi.stat().st_size > 100:
            result_queue.put(("OK", idx, total, audio, gpu_id, elapsed, ""))
        else:
            result_queue.put(("FAIL", idx, total, audio, gpu_id, elapsed, last_err))


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="强制重新转换所有文件")
    parser.add_argument("--dry-run", action="store_true", help="只列出待转换文件，不执行")
    args = parser.parse_args()

    print("=" * 60)
    print(f"酷我下载 -> 快速模式转换")
    print(f"源:   {SOURCE}")
    print(f"目标: {TARGET}")
    print(f"筛选: 顶层目录内任一音频 mtime >= {CUTOFF.strftime('%Y-%m-%d %H:%M')}")
    print(f"目录结构: 保留 (酷我/<专辑>/<曲名>.mid)")
    print("=" * 60)

    files, qual = get_missing_files(force=args.force)
    total = len(files)

    print(f"符合条件的专辑目录: {len(qual)} 个")
    for name in sorted(qual):
        print(f"  - {name}")
    print(f"\n待转换音频: {total} 个")

    if args.dry_run:
        print("\n[dry-run] 待转换文件清单:")
        for f in files:
            rel = f.relative_to(SOURCE)
            print(f"  {rel}")
        return

    if total == 0:
        print("全部完成!")
        return

    task_queue = Queue()
    result_queue = Queue()
    for i, f in enumerate(files):
        task_queue.put((i + 1, total, f))

    workers = []
    for i in range(WORKERS):
        gpu = GPUS[i % len(GPUS)]
        p = Process(target=worker, args=(task_queue, result_queue, gpu), daemon=True)
        p.start()
        workers.append(p)
        if i < WORKERS - 1:
            time.sleep(8)  # 错开启动，避免多 worker 同时首次加载 checkpoint 竞争
    print(f"\n启动 {WORKERS} worker -> GPU 分配 {GPUS}")
    print("=" * 60)

    done = failed = 0
    t_start = time.time()
    while done + failed < total:
        try:
            item = result_queue.get(timeout=15)
        except Exception:
            continue
        status = item[0]
        idx, _, audio, gpu, elapsed = item[1], item[2], item[3], item[4], item[5]
        err_msg = item[6] if len(item) > 6 else ""
        rel = audio.relative_to(SOURCE)

        if status == "OK":
            done += 1
        else:
            failed += 1
            if err_msg:
                print(f"  ERR: {err_msg[:200].strip()}")

        elapsed_total = time.time() - t_start
        rate = (done + failed) / elapsed_total * 60 if elapsed_total > 0 else 0
        remain = (total - done - failed) / rate if rate > 0 else 0
        print(f"  [{status}] [{done+failed}/{total}] GPU{gpu} {str(rel)[:55]} "
              f"({elapsed:.0f}s) {rate:.1f}/min ~{remain:.0f}min")

    print("\n" + "=" * 60)
    print(f"完成: {done}, 失败: {failed}, 总计: {total}")
    print(f"耗时: {(time.time()-t_start)/60:.1f} 分钟")


if __name__ == "__main__":
    main()
