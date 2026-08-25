#!/usr/bin/env python3
"""CC11分支专门跑小提琴曲目: 网络收集/youtube one/Sonatas & Partitas (巴赫无伴奏小提琴 5首)
输出到同目录下 CC11/ 子文件夹, 不覆盖新版产物"""
import io, os, shutil, subprocess, sys, time, hashlib as _hl
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)

ROOT = Path(r"D:\working\vscode-projects\instrument-agnostic-amt-main")
EXPR_DIR = ROOT / "expression-20260823" / "instrument-agnostic-amt-expression"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"

SRC = Path(r"E:\存储器备份\2024.10.30 音乐卡16G\网络收集\youtube one\Sonatas & Partitas")
TARGET = Path(r"D:\开源合集\开源 2022.9.14\芯片音乐\自制芯片音乐\MIDI识别合集\MIDI识别 2026\20260824\音乐卡\网络收集\youtube one\Sonatas & Partitas CC11")
WORK = ROOT / "_cc11_work"

WORKER = ROOT / "_cc11_worker.py"
WORKER.write_text('''import os, sys, shutil, hashlib
from pathlib import Path
sys.path.insert(0, r"{EXPR_DIR}")
os.chdir(r"{ROOT}")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
from infer_stem import run_stem_separated_transcription

audio = Path(sys.argv[1]); out_root = Path(sys.argv[2])
orig_stem = audio.stem
short_stem = "s" + hashlib.md5(orig_stem.encode("utf-8")).hexdigest()[:10]
need_short = len(orig_stem) > 30 or len(str(out_root)) + len(orig_stem)*5 + 80 > 240
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
    transcribe_lyrics=False, predict_expression=True,
    cleanup_separated_stems=True, merge_onset_ms=20.0,
)
print("MERGED:" + str(r["merged_midi_path"]))
'''.replace("{EXPR_DIR}", str(EXPR_DIR)).replace("{ROOT}", str(ROOT)), encoding="utf-8")

AUDIO = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".aiff", ".aif", ".opus"}
files = sorted(f for f in SRC.rglob("*") if f.is_file() and f.suffix.lower() in AUDIO)
print(f"Sonatas & Partitas (CC11): {len(files)} 首", flush=True)

for i, audio in enumerate(files, 1):
    final = TARGET / (audio.stem + ".mid")
    if final.exists() and final.stat().st_size > 100:
        print(f"[SKIP] {audio.stem[:50]}", flush=True); continue
    work_root = WORK / ("c" + _hl.md5(audio.stem.encode()).hexdigest()[:10])
    t0 = time.time()
    try:
        r = subprocess.run([str(VENV_PY), "-u", str(WORKER), str(audio), str(work_root)],
            capture_output=True, text=True, timeout=3600, encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONPATH": str(EXPR_DIR), "CUDA_VISIBLE_DEVICES": "1",
                 "HF_ENDPOINT": "https://hf-mirror.com", "PYTHONUNBUFFERED": "1"})
        merged = None
        for line in (r.stdout or "").splitlines():
            if line.startswith("MERGED:"):
                merged = Path(line[7:].strip()); break
        if merged and merged.exists():
            # CC11 曲线在 _expression.mid, 优先取它
            expr = merged.with_name(merged.stem.replace("_beat_chord", "") + "_expression.mid")
            src_file = expr if expr.exists() else merged
            final.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src_file), str(final))
            shutil.rmtree(work_root, ignore_errors=True)
            print(f"[OK] [{i}/{len(files)}] {audio.stem[:50]} ({time.time()-t0:.0f}s)", flush=True)
        else:
            print(f"[FAIL] [{i}/{len(files)}] {audio.stem[:50]} :: {(r.stderr or r.stdout or '')[-200:]}", flush=True)
    except Exception as e:
        print(f"[FAIL] [{i}/{len(files)}] {audio.stem[:50]} :: {e}", flush=True)

shutil.rmtree(WORK, ignore_errors=True)
print("CC11 小提琴任务完成", flush=True)
