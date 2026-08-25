#!/usr/bin/env python3
"""召唤之夜 5/6 代 - 分轨+力度转换

源: F:\\存储器备份\\2023.1.17 音乐档案\\MP3格式\\召唤之夜系列 下:
  - Summon Night 5 mp3 (31首, 含子目录 Summon Night 5 Soundtrack  mp3)
  - Summon Night 6 mp3 (31首, 含子目录 6 和 unlike/unlike)
输出: 20260727/召唤之夜系列/<完整源子路径>/<曲名>.mid  （和游戏任务同目录, 保留结构）
流程: 新版官方分轨流程
"""

import io
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

if getattr(sys.stdout, 'encoding', '') != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

ROOT = Path(r"D:\working\vscode-projects\instrument-agnostic-amt-main")
NEW_DIR = ROOT / "newversion-20260726"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"

# 源: 召唤之夜系列根目录下的 5/6 代子目录
SERIES_SRC = Path(r"F:\存储器备份\2023.1.17 音乐档案\MP3格式\召唤之夜系列")
SUBDIRS = ["Summon Night 5 mp3", "Summon Night 6 mp3"]

# 输出: 和游戏任务同一个 20260727 目录
TARGET = Path(r"D:\开源合集\开源 2022.9.14\芯片音乐\自制芯片音乐\MIDI识别合集\MIDI识别 2026\20260727\召唤之夜系列")
WORK_DIR = Path(r"D:\开源合集\开源 2022.9.14\芯片音乐\自制芯片音乐\MIDI识别合集\MIDI识别 2026\20260727\_work_summon")

AUDIO_EXTS = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".aiff", ".aif", ".opus"}
LOG_FILE = ROOT / "run_summon_stem.log"
GPUS = [0, 1]
WORKER_SCRIPT = NEW_DIR / "_summon_stem_worker.py"


def log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def write_worker_script():
    new_dir_str = str(NEW_DIR)
    nb_helpers_str = str(NEW_DIR / "_nb_helpers.py")
    root_str = str(ROOT)
    worker_code = '''import os, sys, shutil, hashlib
from pathlib import Path
sys.path.insert(0, r"{NEW_DIR}")
os.chdir(r"{ROOT}")
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
import importlib.util
spec = importlib.util.spec_from_file_location("nb_helpers", r"{NB_HELPERS}")
nb = importlib.util.module_from_spec(spec); spec.loader.exec_module(nb)

audio = Path(sys.argv[1])
out_root = Path(sys.argv[2])
orig_stem = audio.stem
short_stem = "n" + hashlib.md5(orig_stem.encode("utf-8")).hexdigest()[:10]
est_path_len = len(str(out_root)) + len(orig_stem) * 5 + 80
need_short = est_path_len > 240 or len(orig_stem) > 30
if need_short:
    tmp_dir = out_root.parent / "_short_inputs"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    short_audio = tmp_dir / (short_stem + audio.suffix)
    if not short_audio.exists():
        shutil.copy2(str(audio), str(short_audio))
    run_audio = short_audio
    run_out_root = out_root / short_stem
else:
    run_audio = audio
    run_out_root = out_root
r = nb.run_stem_separated_transcription(
    run_audio, checkpoint_path=None, output_root=str(run_out_root),
    window_batch_size=4, max_midi_melodic_instruments=15,
    transcribe_drum_stems=True, predict_velocity=True,
    cleanup_separated_stems=False, merge_onset_ms=50.0,
)
print("MERGED:" + str(r["merged_midi_path"]))
'''.replace("{NEW_DIR}", new_dir_str).replace("{ROOT}", root_str).replace("{NB_HELPERS}", nb_helpers_str)
    WORKER_SCRIPT.write_text(worker_code, encoding="utf-8")


def find_all_audios():
    result = []
    for sub in SUBDIRS:
        sd = SERIES_SRC / sub
        if not sd.exists():
            log(f"⚠ 子目录不存在: {sub}"); continue
        for f in sorted(sd.rglob("*")):
            if f.is_file() and f.suffix.lower() in AUDIO_EXTS:
                result.append((f, sub))
    return result


def expected_final_midi(audio, subdir):
    """保留完整源目录结构: TARGET/<子目录名>/<源内相对路径>.mid"""
    rel = audio.relative_to(SERIES_SRC / subdir)
    return TARGET / subdir / rel.with_suffix(".mid")


def find_merged_midi(work_root, song_stem):
    candidate = work_root / song_stem / "merged" / f"{song_stem}_velocity.mid"
    if candidate.exists(): return candidate
    for p in work_root.rglob("*_velocity.mid"): return p
    for p in work_root.rglob("*.mid"):
        if "stem_midis" not in str(p): return p
    return None


def worker_proc(task_queue, result_queue, gpu_id):
    import subprocess as sp
    while True:
        item = task_queue.get()
        if item is None: break
        idx, total, audio, subdir, final = item
        song_stem = audio.stem
        disp = f"{subdir}/{audio.relative_to(SERIES_SRC / subdir)}"
        t0 = time.time()
        work_root = WORK_DIR / subdir / song_stem
        try:
            result = sp.run(
                [str(VENV_PY), "-u", str(WORKER_SCRIPT), str(audio), str(work_root)],
                capture_output=True, text=True, timeout=1200,
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
            if not merged or not merged.exists():
                merged = find_merged_midi(work_root, song_stem)
            if merged and merged.exists() and merged.stat().st_size > 100:
                final.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(merged), str(final))
                # 立即清理这首的中间产物
                try: shutil.rmtree(work_root, ignore_errors=True)
                except Exception: pass
                result_queue.put(("OK", idx, total, disp, gpu_id, elapsed, final.stat().st_size))
            else:
                err = (result.stderr or result.stdout or "")[-200:]
                result_queue.put(("FAIL", idx, total, disp, gpu_id, elapsed, err.strip()[:150]))
        except Exception as e:
            elapsed = time.time() - t0
            result_queue.put(("FAIL", idx, total, disp, gpu_id, elapsed, str(e)[:150]))


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
    log("召唤之夜 5/6 代 - 分轨+力度转换")
    log(f"源:   {SERIES_SRC}")
    log(f"子目录: {SUBDIRS}")
    log(f"目标: {TARGET}")
    log(f"工作: {WORK_DIR}")
    log("=" * 50)

    write_worker_script()
    all_audios = find_all_audios()
    log(f"音频总数: {len(all_audios)}")
    from collections import Counter
    cnt = Counter(s for _, s in all_audios)
    for s in SUBDIRS:
        if s in cnt: log(f"  {s}: {cnt[s]} 首")

    tasks = []
    for audio, subdir in all_audios:
        final = expected_final_midi(audio, subdir)
        if not (final.exists() and final.stat().st_size > 100):
            tasks.append((audio, subdir, final))
    log(f"待转换: {len(tasks)}")

    if args.dry_run:
        for audio, subdir, final in tasks:
            log(f"  {subdir}/{audio.relative_to(SERIES_SRC/subdir)} -> {final.relative_to(TARGET)}")
        return

    if not tasks:
        log("全部已转换!"); return

    from multiprocessing import Process, Queue
    total = len(tasks)
    task_queue = Queue()
    result_queue = Queue()
    for i, (audio, subdir, final) in enumerate(tasks, 1):
        task_queue.put((i, total, audio, subdir, final))
    for _ in GPUS:
        task_queue.put(None)

    procs = []
    for gpu_id in GPUS:
        p = Process(target=worker_proc, args=(task_queue, result_queue, gpu_id), daemon=True)
        p.start(); procs.append(p)
        log(f"启动 Worker GPU{gpu_id} (pid {p.pid})")
        time.sleep(10)

    t_start = time.time()
    done = failed = 0
    while done + failed < total:
        try:
            item = result_queue.get(timeout=30)
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
