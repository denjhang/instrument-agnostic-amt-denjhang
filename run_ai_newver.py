#!/usr/bin/env python3
"""新版(20260823) AI音乐合集转换
规则: 同目录同名文件 mp3 优先, 有 mp3 的 mp4 跳过; 无对应 mp3 的 mp4 用 ffmpeg 提音频
输出: 20260824\\音乐档案\\AI音乐合集\\<相对结构>.mid
"""
import io, os, shutil, sys, time, hashlib as _hl
from datetime import datetime
from pathlib import Path

if getattr(sys.stdout, 'encoding', '') != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

ROOT = Path(r"D:\working\vscode-projects\instrument-agnostic-amt-main")
NEW_DIR = ROOT / "newversion-20260823" / "instrument-agnostic-amt-main"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
WORKER_SCRIPT = ROOT / "_ai_newver_worker.py"
LOG_FILE = ROOT / "run_ai_newver.log"

SOURCE = Path(r"F:\存储器备份\2023.1.17 音乐档案\AI音乐合集")
TARGET = Path(r"D:\开源合集\开源 2022.9.14\芯片音乐\自制芯片音乐\MIDI识别合集\MIDI识别 2026\20260824\音乐档案\AI音乐合集")
WORK_DIR = TARGET / "_work7"

AUDIO_EXTS = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".aiff", ".aif", ".opus"}
VIDEO_EXTS = {".mp4", ".mkv", ".flv", ".webm", ".mov", ".avi", ".ts", ".m4v"}


def log(msg):
    line = f"[{datetime.now().strftime('%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def write_worker_script():
    worker_code = '''import os, sys, shutil, hashlib, subprocess
from pathlib import Path
sys.path.insert(0, r"{NEW_DIR}")
os.chdir(r"{ROOT}")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
from imageio_ffmpeg import get_ffmpeg_exe
from infer_stem import run_stem_separated_transcription

audio = Path(sys.argv[1])
out_root = Path(sys.argv[2])

VIDEO_EXTS = {".mp4", ".mkv", ".flv", ".webm", ".mov", ".avi", ".ts", ".m4v"}
if audio.suffix.lower() in VIDEO_EXTS:
    wav = out_root / "_audio_input.wav"
    out_root.mkdir(parents=True, exist_ok=True)
    cmd = [get_ffmpeg_exe(), "-y", "-i", str(audio), "-vn", "-acodec", "pcm_s16le",
           "-ar", "44100", "-ac", "2", str(wav)]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0 or not wav.exists():
        print("FFMPEG_FAIL"); sys.exit(2)
    audio = wav

orig_stem = audio.stem
short_stem = "s" + hashlib.md5(orig_stem.encode("utf-8")).hexdigest()[:10]
est_path_len = len(str(out_root)) + len(orig_stem) * 5 + 80
need_short = est_path_len > 240 or len(orig_stem) > 30
if need_short:
    tmp_dir = out_root.parent / "_short_inputs"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    short_audio = tmp_dir / (short_stem + audio.suffix)
    if not short_audio.exists():
        shutil.copy2(str(audio), str(short_audio))
    run_audio, run_out_root = short_audio, out_root / short_stem
else:
    run_audio, run_out_root = audio, out_root

r = run_stem_separated_transcription(
    run_audio, checkpoint_path=None, output_root=str(run_out_root),
    window_batch_size=4, max_midi_melodic_instruments=15,
    transcribe_drum_stems=True, predict_velocity=True,
    refine_instruments=True, predict_beat_chord=True,
    cleanup_separated_stems=True, merge_onset_ms=20.0)
print("MERGED:" + str(r["merged_midi_path"]))
'''.replace("{NEW_DIR}", str(NEW_DIR)).replace("{ROOT}", str(ROOT))
    WORKER_SCRIPT.write_text(worker_code, encoding="utf-8")


def find_files():
    files = []
    for f in sorted(SOURCE.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in (AUDIO_EXTS | VIDEO_EXTS):
            continue
        # mp3优先: 若同名音频版本存在, 跳过视频版
        if f.suffix.lower() in VIDEO_EXTS:
            if any((f.with_suffix(e)).exists() for e in AUDIO_EXTS):
                continue
        files.append(f)
    return files


def expected_final(audio):
    rel = audio.relative_to(SOURCE)
    final = TARGET / rel.with_suffix(".mid")
    if len(str(final)) > 240:
        parent = final.parent
        digest = _hl.md5(final.name.encode("utf-8")).hexdigest()[:8]
        stem, ext = final.name.rsplit(".", 1)
        keep = max(8, 240 - len(str(parent)) - 1 - len(digest) - 1 - len(ext))
        final = parent / f"{stem[:keep]}~{digest}.{ext}"
    return final


def worker_proc(task_queue, result_queue, gpu_id):
    import subprocess as sp
    while True:
        item = task_queue.get()
        if item is None:
            break
        idx, total, audio, final = item
        disp = str(audio.relative_to(SOURCE))
        t0 = time.time()
        work_root = WORK_DIR / ("a" + _hl.md5(disp.encode("utf-8")).hexdigest()[:12])
        try:
            result = sp.run(
                [str(VENV_PY), "-u", str(WORKER_SCRIPT), str(audio), str(work_root)],
                capture_output=True, text=True, timeout=3600,
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
                for pat in ("*_beat_chord.mid", "*_velocity.mid"):
                    cand = list(work_root.rglob(pat))
                    if cand:
                        merged = cand[0]; break
            if merged and merged.exists() and merged.stat().st_size > 100:
                final.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(merged), str(final))
                shutil.rmtree(work_root, ignore_errors=True)
                result_queue.put(("OK", idx, total, disp, gpu_id, elapsed, final.stat().st_size))
            else:
                shutil.rmtree(work_root, ignore_errors=True)
                err = (result.stderr or result.stdout or "")[-200:]
                result_queue.put(("FAIL", idx, total, disp, gpu_id, elapsed, err.strip()[:150]))
        except Exception as e:
            shutil.rmtree(work_root, ignore_errors=True)
            result_queue.put(("FAIL", idx, total, disp, gpu_id, time.time() - t0, str(e)[:150]))


def main():
    LOG_FILE.write_text("", encoding="utf-8")
    log("AI音乐合集转换 (mp3优先去重, mp4提音频)")
    files = find_files()
    pending = [f for f in files if not (expected_final(f).exists() and expected_final(f).stat().st_size > 100)]
    log(f"总文件(去重后): {len(files)}, 待转换: {len(pending)}")
    if not pending:
        log("全部已完成"); return

    write_worker_script()
    from multiprocessing import Process, Queue
    GPUS = [0, 1]
    total = len(pending)
    task_queue = Queue(); result_queue = Queue()
    for i, f in enumerate(pending, 1):
        task_queue.put((i, total, f, expected_final(f)))
    for _ in GPUS:
        task_queue.put(None)
    procs = []
    for gpu_id in GPUS:
        p = Process(target=worker_proc, args=(task_queue, result_queue, gpu_id), daemon=True)
        p.start(); procs.append(p)
        log(f"启动 Worker GPU{gpu_id}")
        time.sleep(10)
    t_start = time.time(); done = failed = 0
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
    log(f"完成: 成功 {done}, 失败 {failed}, 总计 {total}, 耗时 {(time.time()-t_start)/60:.1f} 分钟")
    shutil.rmtree(WORK_DIR, ignore_errors=True)
    log("已清理 _work7")


if __name__ == "__main__":
    main()
