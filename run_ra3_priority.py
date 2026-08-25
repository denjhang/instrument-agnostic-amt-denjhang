#!/usr/bin/env python3
"""临时优先任务: 小飞熊886 红警3原版OST(44首, 含41.The Red March Reprise) 单worker GPU0"""
import io, os, shutil, subprocess, sys, time, hashlib as _hl
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)

ROOT = Path(r"D:\working\vscode-projects\instrument-agnostic-amt-main")
NEW_DIR = ROOT / "newversion-20260823" / "instrument-agnostic-amt-main"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
WORKER = ROOT / "_bili_newver_worker.py"

SRC = Path(r"G:\网络视频-2026\哔哩哔哩视频\小飞熊886\【音乐】红色警戒3 原版 Original Videogame Score 游戏原声OST音乐集")
SOURCE = Path(r"G:\网络视频-2026\哔哩哔哩视频")
TARGET = Path(r"D:\开源合集\开源 2022.9.14\芯片音乐\自制芯片音乐\MIDI识别合集\MIDI识别 2026\20260824\哔哩哔哩视频")
WORK_DIR = TARGET / "_work_ra3"

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

files = sorted(f for f in SRC.rglob("*") if f.is_file() and f.suffix.lower() in
               {".mp3",".wav",".flac",".ogg",".m4a",".aac",".wma",".aiff",".aif",".opus",".mp4",".mkv",".flv",".webm",".mov",".avi",".ts",".m4v"})
pending = [f for f in files if not (expected_final(f).exists() and expected_final(f).stat().st_size > 100)]
print(f"RA3原版OST: 总{len(files)} 待转{len(pending)}", flush=True)

done = failed = 0
t0 = time.time()
for i, audio in enumerate(pending, 1):
    disp = str(audio.relative_to(SOURCE))
    final = expected_final(audio)
    work_root = WORK_DIR / ("r" + _hl.md5(disp.encode()).hexdigest()[:12])
    try:
        r = subprocess.run([str(VENV_PY), "-u", str(WORKER), str(audio), str(work_root)],
            capture_output=True, text=True, timeout=3600, encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONPATH": str(NEW_DIR), "CUDA_VISIBLE_DEVICES": "0",
                 "HF_ENDPOINT": "https://hf-mirror.com", "PYTHONUNBUFFERED": "1"})
        merged = None
        for line in (r.stdout or "").splitlines():
            if line.startswith("MERGED:"):
                merged = Path(line[7:].strip()); break
        if not merged or not merged.exists():
            for pat in ("*_beat_chord.mid", "*_velocity.mid"):
                c = list(work_root.rglob(pat))
                if c: merged = c[0]; break
        if merged and merged.exists() and merged.stat().st_size > 100:
            final.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(merged), str(final))
            shutil.rmtree(work_root, ignore_errors=True)
            done += 1
            print(f"[OK] [{i}/{len(pending)}] {disp[-60:]} ({time.time()-t0:.0f}s)", flush=True)
        else:
            failed += 1
            print(f"[FAIL] [{i}/{len(pending)}] {disp[-60:]} :: {(r.stderr or r.stdout or '')[-150:]}", flush=True)
    except Exception as e:
        failed += 1
        print(f"[FAIL] [{i}/{len(pending)}] {disp[-60:]} :: {e}", flush=True)

shutil.rmtree(WORK_DIR, ignore_errors=True)
print(f"RA3原版OST完成: {done}/{len(pending)} 失败{failed}", flush=True)
