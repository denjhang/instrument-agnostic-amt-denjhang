#!/usr/bin/env python3
"""8进程并行转换，分配到两张GPU"""

import io
import os
import subprocess
import sys
import time
from multiprocessing import Process, Queue
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

SOURCE = Path(r"E:\存储器备份\2024.10.30 音乐卡16G")
TARGET = Path(r"D:\开源合集\开源 2022.9.14\芯片音乐\自制芯片音乐\MIDI识别合集\MIDI识别 2026\分轨模式")
SCRIPT = Path(__file__).parent / "stem_infer.py"
VENV_PY = Path(__file__).parent / ".venv" / "Scripts" / "python.exe"
EXCLUDE = {"vgm", "midi音乐"}
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".ogg", ".opus", ".m4a", ".aac", ".wma", ".aiff", ".aif"}
WORKERS = 2
GPUS = [0, 1]  # 两张显卡


def get_missing_files():
    files = []
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
            files.append(f)
    return files


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
        # 长音频文件给更长的超时
        audio_size_mb = audio.stat().st_size / 1024 / 1024
        timeout = 7200 if audio_size_mb > 30 else 1800

        result = subprocess.run(
            [str(VENV_PY), str(SCRIPT), "--audio", str(audio),
             "--output-root", str(output_dir), "--cleanup-stems"],
            capture_output=True, text=True, timeout=timeout,
            encoding='utf-8', errors='replace',
        )
        elapsed = time.time() - t0

        expected_midi = output_dir / audio.with_suffix(".mid").name
        if expected_midi.exists():
            result_queue.put(("OK", idx, total, audio.name, gpu_id, elapsed))
        else:
            result_queue.put(("FAIL", idx, total, audio.name, gpu_id, elapsed,
                              result.stderr[-500:] if result.stderr else ""))


def main():
    files = get_missing_files()
    total = len(files)
    print(f"待转换: {total} 个文件, {WORKERS} 个 worker, GPU: {GPUS}")
    print("=" * 60)

    task_queue = Queue()
    result_queue = Queue()

    # 填充任务
    for i, f in enumerate(files):
        task_queue.put((i + 1, total, f))

    # 启动 workers，均匀分配到两张 GPU
    workers = []
    for i in range(WORKERS):
        gpu = GPUS[i % len(GPUS)]
        p = Process(target=worker, args=(task_queue, result_queue, gpu), daemon=True)
        p.start()
        workers.append(p)
        print(f"  Worker {i+1} -> GPU {gpu}")

    # 发送停止信号
    for _ in range(WORKERS):
        task_queue.put(None)

    # 收集结果
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
