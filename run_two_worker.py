#!/usr/bin/env python3
"""双worker收尾任务 (各占一卡)
用法: run_two_worker.py ai     # GPU0: AI音乐扫描转换
      run_two_worker.py queue  # GPU1: 网络视频零头 + 酷我排队
"""
import io, os, shutil, subprocess, sys, time, hashlib as _hl
from pathlib import Path

MODE = sys.argv[1]
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)

ROOT = Path(r"D:\working\vscode-projects\instrument-agnostic-amt-main")
NEW_DIR = ROOT / "newversion-20260823" / "instrument-agnostic-amt-main"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
WORKER = ROOT / "_bili_newver_worker.py"  # 通用worker: 音频直接喂/视频自动ffmpeg提音频
LOG = ROOT / f"run_two_worker_{MODE}.log"
OUTROOT = Path(r"D:/开源合集/开源 2022.9.14/芯片音乐/自制芯片音乐/MIDI识别合集/MIDI识别 2026")
AUDIO = {".mp3",".wav",".flac",".ogg",".m4a",".aac",".wma",".aiff",".aif",".opus"}
VIDEO = {".mp4",".mkv",".flv",".webm",".mov",".avi",".ts",".m4v"}

import imageio_ffmpeg
_ffdir = str(Path(imageio_ffmpeg.get_ffmpeg_exe()).parent)
env = {**os.environ, "PYTHONPATH": str(NEW_DIR), "CUDA_VISIBLE_DEVICES": "0" if MODE=="ai" else "1",
       "HF_ENDPOINT": "https://hf-mirror.com", "PYTHONUNBUFFERED": "1",
       "PATH": os.environ.get("PATH","") + os.pathsep + _ffdir}
WORK = ROOT / f"_tw_work_{MODE}"


def log(m):
    print(m, flush=True)
    with open(LOG, "a", encoding="utf-8") as f: f.write(m + "\n")


def expected(src_root, tgt_root, f):
    rel = f.relative_to(src_root)
    final = tgt_root / rel.with_suffix(".mid")
    if len(str(final)) > 240:
        parent = final.parent
        dg = _hl.md5(final.name.encode("utf-8")).hexdigest()[:8]
        st, ex = final.name.rsplit(".", 1)
        final = parent / f"{st[:max(8,240-len(str(parent))-len(dg)-len(ex)-3)]}~{dg}.{ex}"
    return final


def collect():
    tasks = []  # (src_root, tgt_root, file)
    if MODE == "ai":
        S = Path(r"F:\存储器备份\2023.1.17 音乐档案\AI音乐合集")
        T = OUTROOT / "20260824" / "音乐档案" / "AI音乐合集"
        for f in sorted(S.rglob("*")):
            if f.is_file() and f.suffix.lower() in AUDIO:
                if not expected(S, T, f).exists():
                    tasks.append((S, T, f))
    else:
        G = Path(r"G:\网络视频-2026")
        T = OUTROOT / "20260824" / "网络视频"
        # 建立全库已转文件名索引(按mid文件名去重, 避免目录名不一致导致重转)
        done_names = set()
        for root in ("20260824",):  # 只认0824版产物, 旧版不算
            for m in (OUTROOT / root).rglob("*.mid"):
                done_names.add(m.stem.split("~")[0])
        for f in sorted(G.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in (AUDIO | VIDEO): continue
            rel = f.relative_to(G)
            if rel.parts[0] == "哔哩哔哩视频": continue  # 已全部完成
            if f.stem in done_names: continue
            tasks.append((G, T, f))
        # 酷我排队(20260823版流程, 跳过7月版专辑逻辑同 run_kuwo_newver)
        K = Path(r"F:\KwDownload\song")
        KT = OUTROOT / "20260824" / "酷我"
        kuwo_done = set()
        for m in KT.rglob("*.mid"):
            kuwo_done.add(m.stem.split("~")[0])
        for f in sorted(K.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in AUDIO: continue
            if f.stem in kuwo_done: continue
            tasks.append((K, KT, f))
    return tasks


def main():
    tasks = collect()
    log(f"[{MODE}] 待转 {len(tasks)} 首, GPU{'0' if MODE=='ai' else '1'}")
    done = fail = 0
    for i, (S, T, f) in enumerate(tasks, 1):
        final = expected(S, T, f)
        work_root = WORK / ("t" + _hl.md5(str(f.relative_to(S)).encode("utf-8")).hexdigest()[:12])
        t0 = time.time()
        # 可疑mp3一律预转wav
        run_audio = f
        if f.suffix.lower() in AUDIO and f.suffix.lower() != ".wav":
            try:
                import soundfile as _sf
                _sf.read(str(f), frames=10)
            except Exception:
                pass  # 表头ok也可能中途崩, 但soundfile完全ok的直接走
        try:
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
                log(f"[OK] [{i}/{len(tasks)}] {str(f.relative_to(S))[:60]} ({time.time()-t0:.0f}s)")
            else:
                fail += 1
                log(f"[FAIL] [{i}/{len(tasks)}] {str(f.relative_to(S))[:60]} :: {(r.stderr or r.stdout or '')[-130:]}")
        except Exception as e:
            fail += 1
            log(f"[FAIL] [{i}/{len(tasks)}] {str(f.relative_to(S))[:60]} :: {e}")
        # rmtree 对超长 stem 路径会静默失败(ignore_errors), 用 \\?\ 前缀强制删除防泄漏
        shutil.rmtree("\\\\?\\" + os.path.abspath(str(work_root)), ignore_errors=True)
        shutil.rmtree(work_root, ignore_errors=True)
    shutil.rmtree(WORK, ignore_errors=True)
    log(f"[{MODE}] 完成: {done} 成功 / {fail} 失败")


if __name__ == "__main__":
    main()
