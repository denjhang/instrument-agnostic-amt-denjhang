#!/usr/bin/env python3
"""哔哩哔哩视频批量 MIDI 转换（快速模式）

从 mp4 视频中提取音频，用 AMT 快速模式转录，保持 UP 主目录结构。

用法:
  .venv\Scripts\python.exe run_bilibili.py
  .venv\Scripts\python.exe run_bilibili.py --force
"""

import io
import os
import subprocess
import sys
import tempfile
import time
from multiprocessing import Process, Queue
from pathlib import Path

if getattr(sys.stdout, 'encoding', '') != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

import imageio_ffmpeg

FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()

SOURCE = Path(r"G:\网络视频-2026\哔哩哔哩视频")
TARGET = Path(r"D:\开源合集\开源 2022.9.14\芯片音乐\自制芯片音乐\MIDI识别合集\MIDI识别 2026\快速模式")
SCRIPT_DIR = Path(__file__).parent
VENV_PY = SCRIPT_DIR / ".venv" / "Scripts" / "python.exe"
INFER_SCRIPT = SCRIPT_DIR / "infer.py"

VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".flv", ".webm"}
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".ogg", ".opus", ".m4a", ".aac", ".wma", ".aiff", ".aif"}
ALL_EXTS = VIDEO_EXTS | AUDIO_EXTS

WORKERS = 2


def find_files():
    """查找所有音频/视频文件，返回 (file, up_name, relative_subdir)"""
    files = []
    for item in SOURCE.iterdir():
        if not item.is_dir():
            continue
        up_name = item.name  # UP 主目录名
        for f in sorted(item.rglob("*")):
            if not f.is_file():
                continue
            if f.suffix.lower() not in ALL_EXTS:
                continue
            rel = f.relative_to(item)
            files.append((f, up_name, rel))
    return files


def get_missing_files(force=False):
    """返回待转换的文件列表"""
    all_files = find_files()
    if force:
        return all_files
    missing = []
    for f, up_name, rel in all_files:
        expected = TARGET / up_name / f.with_suffix(".mid").name
        if not expected.exists():
            missing.append((f, up_name, rel))
        else:
            print(f"  已存在: {up_name}/{rel}")
    return missing


def extract_audio(video_path, output_wav):
    """用 ffmpeg 从视频提取音频为 wav"""
    cmd = [
        FFMPEG_EXE,
        "-y",
        "-i", str(video_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "44100",
        "-ac", "2",
        str(output_wav),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0 or not Path(output_wav).exists():
        raise RuntimeError(f"ffmpeg failed: {result.stderr[-300:]}")


def worker(task_queue, result_queue, gpu_id):
    """每个 worker 处理一个文件"""
    os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_id)
    while True:
        item = task_queue.get()
        if item is None:
            break
        idx, total, audio_path, up_name, rel = item

        output_dir = TARGET / up_name
        output_dir.mkdir(parents=True, exist_ok=True)
        output_midi = output_dir / audio_path.with_suffix(".mid").name

        t0 = time.time()
        try:
            # 如果是视频文件，需要先提取音频
            is_video = audio_path.suffix.lower() in VIDEO_EXTS
            if is_video:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False, prefix="amt_") as tmp:
                    tmp_wav = tmp.name
                try:
                    extract_audio(audio_path, tmp_wav)
                    input_for_infer = tmp_wav
                except Exception as e:
                    os.unlink(tmp_wav)
                    raise RuntimeError(f"音频提取失败: {e}")
            else:
                input_for_infer = str(audio_path)
                tmp_wav = None

            # 调用 infer.py
            result = subprocess.run(
                [
                    str(VENV_PY), str(INFER_SCRIPT),
                    "--audio", input_for_infer,
                    "--output-midi", str(output_midi),
                ],
                capture_output=True, text=True, timeout=600,
                encoding='utf-8', errors='replace',
            )

            if tmp_wav:
                try:
                    os.unlink(tmp_wav)
                except:
                    pass

            elapsed = time.time() - t0
            if output_midi.exists():
                result_queue.put(("OK", idx, total, up_name, rel, gpu_id, elapsed))
            else:
                err = result.stderr[-300:] if result.stderr else ""
                result_queue.put(("FAIL", idx, total, up_name, rel, gpu_id, elapsed, err))

        except Exception as e:
            elapsed = time.time() - t0
            result_queue.put(("FAIL", idx, total, up_name, rel, gpu_id, elapsed, str(e)))


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="强制重新转换")
    args = parser.parse_args()

    print("=" * 60)
    print("哔哩哔哩视频 MIDI 转换（快速模式）")
    print(f"源: {SOURCE}")
    print(f"目标: {TARGET}")
    print(f"{WORKERS} 个 worker")
    print("=" * 60)

    all_files = find_files()
    files = get_missing_files(force=args.force)
    print(f"\n总文件: {len(all_files)}")
    print(f"待转换: {len(files)}")

    if not files:
        print("全部完成!")
        return

    print(f"\n待转换:")
    for f, up_name, rel in files:
        print(f"  {up_name}/{rel} ({f.suffix})")

    task_queue = Queue()
    result_queue = Queue()

    for i, (f, up_name, rel) in enumerate(files):
        task_queue.put((i + 1, len(files), f, up_name, rel))

    workers = []
    for i in range(WORKERS):
        gpu_id = i % 2
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
            item = result_queue.get(timeout=60)
        except:
            continue

        status = item[0]
        idx, total, up_name, rel, gpu, elapsed = item[1], item[2], item[3], item[4], item[5], item[6]
        err_msg = item[7] if len(item) > 7 else ""

        if status == "OK":
            done += 1
        else:
            failed += 1
            if err_msg:
                print(f"  ERR: {err_msg[:200]}")

        elapsed_total = time.time() - t_start
        rate = (done + failed) / elapsed_total * 60 if elapsed_total > 0 else 0
        remain = (total - done - failed) / rate if rate > 0 else 0
        print(f"  [{status}] [{done+failed}/{total}] GPU{gpu} {up_name}/{str(rel)[:50]} "
              f"({elapsed:.0f}s) {rate:.1f}/min ~{remain:.0f}min left")

    print("\n" + "=" * 60)
    print(f"完成: {done}, 失败: {failed}, 总计: {len(files)}")
    print(f"耗时: {(time.time()-t_start)/60:.1f} 分钟")


if __name__ == "__main__":
    main()
