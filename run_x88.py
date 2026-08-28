#!/usr/bin/env python3
"""x88 放大300 松下EB-X88铃声内录 → 双版本转换
预处理: 提取有声声道为单声道 + 峰值归一化(0.9)
版本1: newversion-20260823 (infer_stem)
版本2: newversion-20260726 (nb_helpers)
输出: 20260824\\x88放大300\\0824版 / 0726版
"""
import io, os, shutil, subprocess, sys, time, hashlib as _hl
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)

ROOT = Path(r"D:\working\vscode-projects\instrument-agnostic-amt-main")
NEW824 = ROOT / "newversion-20260823" / "instrument-agnostic-amt-main"
NEW726 = ROOT / "newversion-20260726"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"

SRC = Path(r"F:\存储器备份\备份索尼录音笔 2021.4.12\x88 放大300")
TARGET = Path(r"D:\开源合集\开源 2022.9.14\芯片音乐\自制芯片音乐\MIDI识别合集\MIDI识别 2026\20260824\x88放大300")
PREP = ROOT / "_x88_prep"
WORK = ROOT / "_x88_work"
LOG = ROOT / "run_x88.log"

WORKER824 = ROOT / "_x88_worker824.py"
WORKER726 = ROOT / "_x88_worker726.py"

WORKER824.write_text('''import os, sys, shutil, hashlib
from pathlib import Path
sys.path.insert(0, r"{NEW824}")
os.chdir(r"{ROOT}")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
from infer_stem import run_stem_separated_transcription
audio = Path(sys.argv[1]); out_root = Path(sys.argv[2])
r = run_stem_separated_transcription(
    audio, checkpoint_path=None, output_root=str(out_root),
    window_batch_size=4, max_midi_melodic_instruments=15,
    transcribe_drum_stems=True, predict_velocity=True,
    refine_instruments=True, predict_beat_chord=True,
    cleanup_separated_stems=True, merge_onset_ms=20.0)
print("MERGED:" + str(r["merged_midi_path"]))
'''.replace("{NEW824}", str(NEW824)).replace("{ROOT}", str(ROOT)), encoding="utf-8")

WORKER726.write_text('''import os, sys, importlib.util
from pathlib import Path
sys.path.insert(0, r"{NEW726}")
os.chdir(r"{ROOT}")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
spec = importlib.util.spec_from_file_location("nb_helpers", r"{NB}")
nb = importlib.util.module_from_spec(spec); spec.loader.exec_module(nb)
audio = Path(sys.argv[1]); out_root = Path(sys.argv[2])
r = nb.run_stem_separated_transcription(
    audio, checkpoint_path=None, output_root=str(out_root),
    window_batch_size=4, max_midi_melodic_instruments=15,
    transcribe_drum_stems=True, predict_velocity=True,
    cleanup_separated_stems=True, merge_onset_ms=50.0)
print("MERGED:" + str(r["merged_midi_path"]))
'''.replace("{NEW726}", str(NEW726)).replace("{NB}", str(NEW726 / "_nb_helpers.py")).replace("{ROOT}", str(ROOT)), encoding="utf-8")


def log(msg):
    print(msg, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def preprocess():
    import numpy as np
    import soundfile as sf
    PREP.mkdir(exist_ok=True)
    files = sorted(SRC.glob("*.mp3"))
    out = []
    for f in files:
        wav = PREP / (f.stem + ".wav")
        if wav.exists():
            out.append(wav); continue
        data, sr = sf.read(str(f), dtype="float32", always_2d=True)
        # 取能量更大的声道作单声道
        ch = int(np.argmax(np.sqrt(np.mean(data**2, axis=0))))
        mono = data[:, ch]
        peak = float(np.max(np.abs(mono)))
        if peak > 1e-6:
            mono = mono * (0.9 / peak)
        sf.write(str(wav), mono, sr)
        out.append(wav)
    return out


def run_version(tag, worker, syspath, out_dir, files):
    env = {**os.environ, "PYTHONPATH": str(syspath), "CUDA_VISIBLE_DEVICES": "1",
           "HF_ENDPOINT": "https://hf-mirror.com", "PYTHONUNBUFFERED": "1"}
    done = fail = 0
    for i, wav in enumerate(files, 1):
        final = out_dir / (wav.stem + ".mid")
        if final.exists() and final.stat().st_size > 100:
            done += 1; continue
        work_root = WORK / tag / ("x" + _hl.md5(wav.stem.encode()).hexdigest()[:10])
        t0 = time.time()
        try:
            r = subprocess.run([str(VENV_PY), "-u", str(worker), str(wav), str(work_root)],
                capture_output=True, text=True, timeout=1800, encoding="utf-8", errors="replace", env=env)
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
                log(f"[{tag}][OK] [{i}/{len(files)}] {wav.stem} ({time.time()-t0:.0f}s, {final.stat().st_size}B)")
            else:
                fail += 1
                log(f"[{tag}][FAIL] [{i}/{len(files)}] {wav.stem} :: {(r.stderr or r.stdout or '')[-150:]}")
        except Exception as e:
            fail += 1
            log(f"[{tag}][FAIL] [{i}/{len(files)}] {wav.stem} :: {e}")
    return done, fail


def main():
    LOG.write_text("", encoding="utf-8")
    log("=== x88 放大300 双版本转换 ===")
    files = preprocess()
    log(f"预处理完成: {len(files)} 个单声道 wav")
    for tag, worker, syspath in (("0824版", WORKER824, NEW824), ("0726版", WORKER726, NEW726)):
        d, f = run_version(tag, worker, syspath, TARGET / tag, files)
        log(f"--- {tag} 完成: {d} 成功 / {f} 失败 ---")
    shutil.rmtree(WORK, ignore_errors=True)
    log("全部完成, 已清理中间产物")


if __name__ == "__main__":
    main()
