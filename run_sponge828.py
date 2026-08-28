#!/usr/bin/env python3
"""AI音乐合集 0726版（7月模型）重转 — 与 0824 版并存对比
规则同 0824 任务: mp3优先去重; 无mp3的mp4先ffmpeg提音频
输出: 20260824\\音乐档案\\AI音乐合集-0726版\\
"""
import io, os, shutil, subprocess, sys, time, hashlib as _hl
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)

ROOT = Path(r"D:\working\vscode-projects\instrument-agnostic-amt-main")
NEW726 = ROOT / "newversion-20260823" / "instrument-agnostic-amt-main"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"

SRC = Path(r"D:\开源合集\开源 2022.9.14\芯片音乐\自制芯片音乐\MIDI识别合集\MIDI识别 2026\20260824\音乐档案\AI音乐合集\2026.8.28海绵")
TARGET = Path(r"D:\开源合集\开源 2022.9.14\芯片音乐\自制芯片音乐\MIDI识别合集\MIDI识别 2026\20260824\音乐档案\AI音乐合集\2026.8.28海绵")
WORK = ROOT / "_sponge828_work"
LOG = ROOT / "run_sponge828.log"

AUDIO = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".aiff", ".aif", ".opus"}
VIDEO = {".mp4", ".mkv", ".flv", ".webm", ".mov", ".avi", ".ts", ".m4v"}

WORKER = ROOT / "_sponge828_worker.py"
WORKER.write_text('''import os, sys, importlib.util
from pathlib import Path
sys.path.insert(0, r"{NEW726}")
os.chdir(r"{ROOT}")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
from infer_stem import run_stem_separated_transcription as _rst
audio = Path(sys.argv[1]); out_root = Path(sys.argv[2])
import hashlib, shutil
orig_stem = audio.stem
short_stem = "s" + hashlib.md5(orig_stem.encode("utf-8")).hexdigest()[:10]
if len(orig_stem) > 30 or len(str(out_root)) + len(orig_stem)*5 + 80 > 240:
    tmp_dir = out_root.parent / "_short_inputs"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    short_audio = tmp_dir / (short_stem + audio.suffix)
    if not short_audio.exists():
        shutil.copy2(str(audio), str(short_audio))
    run_audio, run_out_root = short_audio, out_root / short_stem
else:
    run_audio, run_out_root = audio, out_root
r = _rst(
    run_audio, checkpoint_path=None, output_root=str(run_out_root),
    window_batch_size=4, max_midi_melodic_instruments=15,
    transcribe_drum_stems=True, predict_velocity=True,
    refine_instruments=True, predict_beat_chord=True,
    cleanup_separated_stems=True, merge_onset_ms=20.0)
print("MERGED:" + str(r["merged_midi_path"]))
'''.replace("{NEW726}", str(NEW726)).replace("{NB}", str(NEW726 / "_nb_helpers.py")).replace("{ROOT}", str(ROOT)), encoding="utf-8")


def log(msg):
    print(msg, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def main():
    ff = subprocess.run([".venv/Scripts/python.exe", "-c", "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())"],
                        capture_output=True, text=True).stdout.strip()
    files = []
    for f in sorted(SRC.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in (AUDIO | VIDEO):
            continue
        if f.suffix.lower() in VIDEO and any((f.with_suffix(e)).exists() for e in AUDIO):
            continue
        files.append(f)
    log(f"海绵8.28(最新版):  {len(files)} 首")

    env = {**os.environ, "PYTHONPATH": str(NEW726), "CUDA_VISIBLE_DEVICES": "1",
           "HF_ENDPOINT": "https://hf-mirror.com", "PYTHONUNBUFFERED": "1"}
    done = fail = 0
    for i, f in enumerate(files, 1):
        rel = f.relative_to(SRC)
        final = TARGET / rel.with_suffix(".mid")
        if len(str(final)) > 240:
            parent = final.parent
            dg = _hl.md5(final.name.encode()).hexdigest()[:8]
            st, ex = final.name.rsplit(".", 1)
            final = parent / f"{st[:max(8,240-len(str(parent))-len(dg)-len(ex)-3)]}~{dg}.{ex}"
        if final.exists() and final.stat().st_size > 100:
            done += 1; continue
        # mp4 先提音频
        audio = f
        work_root = WORK / ("a" + _hl.md5(str(rel).encode()).hexdigest()[:12])
        work_root.mkdir(parents=True, exist_ok=True)
        if f.suffix.lower() in VIDEO:
            wav = work_root / "_audio_input.wav"
            r = subprocess.run([ff, "-y", "-i", str(f), "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2", str(wav)],
                               capture_output=True)
            if r.returncode != 0 or not wav.exists():
                fail += 1; log(f"[FAIL] [{i}/{len(files)}] {rel} :: ffmpeg"); continue
            audio = wav
        t0 = time.time()
        try:
            r = subprocess.run([str(VENV_PY), "-u", str(WORKER), str(audio), str(work_root / "w")],
                capture_output=True, text=True, timeout=1800, encoding="utf-8", errors="replace", env=env)
            merged = None
            for line in (r.stdout or "").splitlines():
                if line.startswith("MERGED:"):
                    merged = Path(line[7:].strip()); break
            if not merged or not merged.exists():
                for pat in ("*_velocity.mid",):
                    c = list((work_root / "w").rglob(pat))
                    if c: merged = c[0]; break
            if merged and merged.exists() and merged.stat().st_size > 100:
                final.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(merged), str(final))
                done += 1
                log(f"[OK] [{i}/{len(files)}] {str(rel)[:55]} ({time.time()-t0:.0f}s)")
            else:
                fail += 1
                log(f"[FAIL] [{i}/{len(files)}] {str(rel)[:55]} :: {(r.stderr or r.stdout or '')[-120:]}")
        except Exception as e:
            fail += 1
            log(f"[FAIL] [{i}/{len(files)}] {str(rel)[:55]} :: {e}")
        shutil.rmtree(work_root, ignore_errors=True)
    shutil.rmtree(WORK, ignore_errors=True)
    log(f"海绵8.28完成: {done} 成功 / {fail} 失败")


if __name__ == "__main__":
    main()
