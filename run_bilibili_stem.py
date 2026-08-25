#!/usr/bin/env python3
"""哔哩哔哩视频 - 分轨+力度转换

源: G:\\网络视频-2026\\哔哩哔哩视频 下, 筛选 7/28 后的文件
特点: mp4 视频, worker 先用 ffmpeg 提取音频为 wav 再喂给 AMT (AMT 不支持直接读 mp4)
输出: 20260727/哔哩哔哩视频/<UP主>/<完整源子路径>/<曲名>.mid  (和游戏音乐同目录)
保留: 完整源目录结构 (UP主/视频合集/视频)
"""

import io
import os
import shutil
import sys
import time
import hashlib
import subprocess
from datetime import datetime
from pathlib import Path

if getattr(sys.stdout, 'encoding', '') != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

ROOT = Path(r"D:\working\vscode-projects\instrument-agnostic-amt-main")
NEW_DIR = ROOT / "newversion-20260726"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"

SOURCE = Path(r"G:\网络视频-2026\哔哩哔哩视频")
TARGET = Path(r"D:\开源合集\开源 2022.9.14\芯片音乐\自制芯片音乐\MIDI识别合集\MIDI识别 2026\20260727\哔哩哔哩视频")
WORK_DIR = Path(r"D:\开源合集\开源 2022.9.14\芯片音乐\自制芯片音乐\MIDI识别合集\MIDI识别 2026\20260727\_work_bilibili")

VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".flv", ".webm"}
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".aiff", ".aif", ".opus"}
ALL_EXTS = VIDEO_EXTS | AUDIO_EXTS
CUTOFF = datetime(2026, 7, 28, 0, 0, 0)

LOG_FILE = ROOT / "run_bilibili_stem.log"
GPUS = [0, 1]
WORKER_SCRIPT = NEW_DIR / "_bili_stem_worker.py"


def log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def write_worker_script():
    worker_code = '''import os, sys, shutil, hashlib, subprocess, tempfile
from pathlib import Path
sys.path.insert(0, r"{NEW_DIR}")
os.chdir(r"{ROOT}")
os.environ.setdefault("CUDA_VISIBLE_DEVICES","0")
os.environ.setdefault("HF_ENDPOINT","https://hf-mirror.com")
import importlib.util
spec = importlib.util.spec_from_file_location("nb_helpers", r"{NB_HELPERS}")
nb = importlib.util.module_from_spec(spec); spec.loader.exec_module(nb)

import imageio_ffmpeg
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

audio_path = Path(sys.argv[1])
out_root = Path(sys.argv[2])

# mp4/mkv 等视频: 先用 ffmpeg 提取音频为 wav
VIDEO_EXTS = {".mp4",".mkv",".avi",".mov",".flv",".webm"}
tmp_wav = None
if audio_path.suffix.lower() in VIDEO_EXTS:
    tmp_wav = out_root / "_audio_input.wav"
    tmp_wav.parent.mkdir(parents=True, exist_ok=True)
    if not tmp_wav.exists():
        cmd = [FFMPEG, "-y", "-i", str(audio_path), "-vn",
               "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2", str(tmp_wav)]
        r = subprocess.run(cmd, capture_output=True, timeout=300)
        if r.returncode != 0 or not tmp_wav.exists():
            raise RuntimeError("ffmpeg failed: " + r.stderr.decode("utf-8","replace")[-200:])
    run_input = tmp_wav
else:
    run_input = audio_path

orig_stem = audio_path.stem
short_stem = "v" + hashlib.md5(orig_stem.encode("utf-8")).hexdigest()[:10]
need_short = len(orig_stem) > 30 or len(str(out_root)) + len(orig_stem)*5 + 80 > 240
if need_short:
    tmp_dir = out_root / "_short_inputs"; tmp_dir.mkdir(parents=True, exist_ok=True)
    short_in = tmp_dir / (short_stem + run_input.suffix)
    if run_input != short_in and not short_in.exists():
        shutil.copy2(str(run_input), str(short_in))
    run_audio = short_in
    run_out_root = out_root / short_stem
else:
    run_audio = run_input
    run_out_root = out_root

r = nb.run_stem_separated_transcription(
    run_audio, checkpoint_path=None, output_root=str(run_out_root),
    window_batch_size=4, max_midi_melodic_instruments=15,
    transcribe_drum_stems=True, predict_velocity=True,
    cleanup_separated_stems=False, merge_onset_ms=50.0,
)
print("MERGED:" + str(r["merged_midi_path"]))
'''.replace("{NEW_DIR}", str(NEW_DIR)).replace("{ROOT}", str(ROOT)).replace("{NB_HELPERS}", str(NEW_DIR / "_nb_helpers.py"))
    WORKER_SCRIPT.write_text(worker_code, encoding="utf-8")


def find_all_files():
    """返回 [(file, up_name)] 7/28 后的所有音视频文件"""
    result = []
    for up_dir in sorted(SOURCE.iterdir()):
        if not up_dir.is_dir():
            continue
        for f in sorted(up_dir.rglob("*")):
            if f.is_file() and f.suffix.lower() in ALL_EXTS:
                result.append((f, up_dir.name))
    return result


def expected_final_midi(file, up_name):
    """完整保留源目录结构: TARGET/<UP主>/<源内相对路径>.mid"""
    rel = file.relative_to(SOURCE / up_name)
    final = TARGET / up_name / rel.with_suffix(".mid")
    if len(str(final)) > 240:
        digest = hashlib.md5(final.name.encode("utf-8")).hexdigest()[:8]
        stem, ext = final.name.rsplit(".", 1)
        keep = max(8, 240 - len(str(final.parent)) - 1 - len(digest) - 1 - len(ext))
        final = final.parent / f"{stem[:keep]}~{digest}.{ext}"
    return final


def find_merged_midi(work_root, song_stem):
    c = work_root / song_stem / "merged" / f"{song_stem}_velocity.mid"
    if c.exists(): return c
    for p in work_root.rglob("*_velocity.mid"): return p
    for p in work_root.rglob("*.mid"):
        if "stem_midis" not in str(p): return p
    return None


def worker_proc(task_queue, result_queue, gpu_id):
    import subprocess as sp
    while True:
        item = task_queue.get()
        if item is None: break
        idx, total, file, up_name, final = item
        song_stem = file.stem
        disp = f"{up_name}/{file.relative_to(SOURCE/up_name)}"
        work_name = "v" + hashlib.md5(f"{up_name}/{song_stem}".encode("utf-8")).hexdigest()[:12]
        work_root = WORK_DIR / work_name
        t0 = time.time()
        try:
            result = sp.run(
                [str(VENV_PY), "-u", str(WORKER_SCRIPT), str(file), str(work_root)],
                capture_output=True, text=True, timeout=1800,
                encoding="utf-8", errors="replace",
                env={**os.environ, "PYTHONPATH": str(NEW_DIR),
                     "CUDA_VISIBLE_DEVICES": str(gpu_id),
                     "HF_ENDPOINT": "https://hf-mirror.com", "PYTHONUNBUFFERED": "1"},
            )
            elapsed = time.time() - t0
            merged = None
            for line in (result.stdout or "").splitlines():
                if line.startswith("MERGED:"):
                    merged = Path(line[len("MERGED:"):].strip()); break
            # short_stem 前缀 v, 用它找
            if not merged or not merged.exists():
                short_stem = "v" + hashlib.md5(song_stem.encode("utf-8")).hexdigest()[:10]
                merged = find_merged_midi(work_root, short_stem)
            if not merged or not merged.exists():
                merged = find_merged_midi(work_root, song_stem)
            if merged and merged.exists() and merged.stat().st_size > 100:
                final.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(merged), str(final))
                try: shutil.rmtree(work_root, ignore_errors=True)
                except: pass
                result_queue.put(("OK", idx, total, disp, gpu_id, elapsed, final.stat().st_size))
            else:
                err = (result.stderr or result.stdout or "")[-200:]
                # 失败也要清理 work_root (含提取的 wav), 避免堆积爆磁盘
                try: shutil.rmtree(work_root, ignore_errors=True)
                except: pass
                result_queue.put(("FAIL", idx, total, disp, gpu_id, elapsed, err.strip()[:150]))
        except Exception as e:
            # 异常也清理
            try: shutil.rmtree(work_root, ignore_errors=True)
            except: pass
            result_queue.put(("FAIL", idx, total, disp, gpu_id, time.time()-t0, str(e)[:150]))


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--cleanup", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.cleanup:
        if WORK_DIR.exists():
            shutil.rmtree(WORK_DIR, ignore_errors=True)
            log(f"已清理 {WORK_DIR}")
        return

    LOG_FILE.write_text("", encoding="utf-8")
    log("=" * 50)
    log("哔哩哔哩视频 - 分轨+力度转换 (mp4→wav→AMT)")
    log(f"源:   {SOURCE}")
    log(f"筛选: mtime >= {CUTOFF}")
    log(f"目标: {TARGET}")
    log("=" * 50)

    write_worker_script()
    all_files = find_all_files()
    log(f"7/28 后文件总数: {len(all_files)}")
    from collections import Counter
    cnt = Counter(up for _, up in all_files)
    for up, c in sorted(cnt.items()):
        log(f"  ({c:3d}) {up}")

    tasks = []
    for f, up in all_files:
        final = expected_final_midi(f, up)
        if not (final.exists() and final.stat().st_size > 100):
            tasks.append((f, up, final))
    log(f"待转换: {len(tasks)}")

    if args.dry_run:
        for f, up, final in tasks[:10]:
            log(f"  {up}/{f.relative_to(SOURCE/up)} -> {final.relative_to(TARGET)}")
        if len(tasks) > 10:
            log(f"  ... 共 {len(tasks)}")
        return

    if not tasks:
        log("全部已转换!"); return

    from multiprocessing import Process, Queue
    total = len(tasks)
    tq, rq = Queue(), Queue()
    for i, (f, up, final) in enumerate(tasks, 1):
        tq.put((i, total, f, up, final))
    for _ in GPUS:
        tq.put(None)
    procs = []
    for gpu_id in GPUS:
        p = Process(target=worker_proc, args=(tq, rq, gpu_id), daemon=True)
        p.start(); procs.append(p)
        log(f"启动 Worker GPU{gpu_id} (pid {p.pid})")
        time.sleep(10)

    t_start = time.time()
    done = failed = 0
    while done + failed < total:
        try:
            item = rq.get(timeout=30)
        except Exception:
            continue
        status, idx, _, disp, gpu, elapsed, extra = item
        if status == "OK":
            done += 1
            log(f"  [OK] [{done+failed}/{total}] GPU{gpu} {disp[:55]} ({elapsed:.0f}s, {extra}B)")
        else:
            failed += 1
            log(f"  [FAIL] [{done+failed}/{total}] GPU{gpu} {disp[:55]} ({elapsed:.0f}s) {extra[:120]}")
        et = time.time() - t_start
        rate = (done + failed) / et * 60 if et > 0 else 0
        remain = (total - done - failed) / rate if rate > 0 else 0
        log(f"  进度: {done+failed}/{total} ({(done+failed)*100//total}%) {rate:.1f}/min 剩余 ~{remain:.0f}min")

    for p in procs:
        p.join(timeout=5)
    log("\n" + "=" * 50)
    log(f"转换完成: 成功 {done}, 失败 {failed}, 总计 {total}")
    log(f"耗时: {(time.time()-t_start)/60:.1f} 分钟")
    log(f"输出: {TARGET}")


if __name__ == "__main__":
    main()
