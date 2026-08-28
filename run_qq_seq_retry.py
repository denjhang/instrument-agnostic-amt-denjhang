#!/usr/bin/env python3
"""qq+网易云失败补跑 — 顺序执行版(绕开multiprocessing环境问题)
用法: run_qq_seq_retry.py 0   # 处理奇数序号, GPU0
      run_qq_seq_retry.py 1   # 处理偶数序号, GPU1
"""
import io, os, shutil, subprocess, sys, time, hashlib as _hl
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)

SLOT = int(sys.argv[1])
ROOT = Path(r"D:\working\vscode-projects\instrument-agnostic-amt-main")
NEW_DIR = ROOT / "newversion-20260823" / "instrument-agnostic-amt-main"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
WORKER = ROOT / "_qq_netease_newver_worker.py"
LOG = ROOT / f"run_qq_seq_retry{SLOT}.log"

SOURCE = Path(r"F:\存储器备份\2023.1.17 音乐档案\未分类\Music SD")
TARGET = Path(r"D:\开源合集\开源 2022.9.14\芯片音乐\自制芯片音乐\MIDI识别合集\MIDI识别 2026\20260824\音乐档案\未分类\Music SD")
WORK_DIR = TARGET / "_work_seq"

AUDIO_EXTS = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".aiff", ".aif", ".opus"}


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


def log(msg):
    print(msg, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


files = sorted(f for f in SOURCE.rglob("*")
               if f.is_file() and f.suffix.lower() in AUDIO_EXTS
               and f.relative_to(SOURCE).parts[0] in ("qq音乐", "网易云音乐"))
pending = [f for f in files if not (expected_final(f).exists() and expected_final(f).stat().st_size > 100)]
mine = [f for i, f in enumerate(pending) if i % 2 == SLOT]
log(f"[slot{SLOT}] 总待转{len(pending)}, 本进程 {len(mine)} 首, GPU{SLOT}")

import imageio_ffmpeg
_ffdir = str(Path(imageio_ffmpeg.get_ffmpeg_exe()).parent)
env = {**os.environ, "PYTHONPATH": str(NEW_DIR), "CUDA_VISIBLE_DEVICES": str(SLOT),
       "HF_ENDPOINT": "https://hf-mirror.com", "PYTHONUNBUFFERED": "1",
       "PATH": os.environ.get("PATH","") + os.pathsep + _ffdir}
done = fail = 0
for i, audio in enumerate(mine, 1):
    disp = str(audio.relative_to(SOURCE))
    final = expected_final(audio)
    work_root = WORK_DIR / ("q" + _hl.md5(disp.encode("utf-8")).hexdigest()[:12] + f"_{SLOT}")
    t0 = time.time()
    try:
        # 补跑曲目一律 ffmpeg 预转 wav(这些mp3多为表头可读但解码中途崩的特殊编码)
        run_audio = audio
        import imageio_ffmpeg as _iio
        wav = work_root / "_audio_input.wav"
        work_root.mkdir(parents=True, exist_ok=True)
        rc = subprocess.run([_iio.get_ffmpeg_exe(), "-y", "-i", str(audio), "-vn",
                             "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2", str(wav)],
                            capture_output=True).returncode
        if rc == 0 and wav.exists() and wav.stat().st_size > 1000:
            run_audio = wav
        else:
            print("PRECONVERT_FAIL " + disp, flush=True)
        r = subprocess.run([str(VENV_PY), "-u", str(WORKER), str(run_audio), str(work_root)],
                           capture_output=True, text=True, timeout=3600,
                           encoding="utf-8", errors="replace", env=env)
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
            done += 1
            log(f"[OK] [{i}/{len(mine)}] {disp[:60]} ({time.time()-t0:.0f}s)")
        else:
            fail += 1
            log(f"[FAIL] [{i}/{len(mine)}] {disp[:60]} :: {(r.stderr or r.stdout or '')[-150:]}")
    except Exception as e:
        fail += 1
        log(f"[FAIL] [{i}/{len(mine)}] {disp[:60]} :: {e}")
    shutil.rmtree(work_root, ignore_errors=True)

log(f"[slot{SLOT}] 完成: {done} 成功 / {fail} 失败")
