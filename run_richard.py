#!/usr/bin/env python3
"""理查德克莱德曼 16 首 - 新版分轨+力度批量转换

流程（每首）:
  1. 新版官方分轨流程: stem分离 → 各stem专用模型转录 → 合并 → 力度预测
  2. 产物落在 _work/<曲名>/merged/<曲名>_velocity.mid
  3. 整理: 提到目标目录 <曲名>.mid （平铺，保留曲名，不混杂中间产物）

用法:
  .venv\\Scripts\\python.exe run_richard.py            # 转换缺失的（断点续跑）
  .venv\\Scripts\\python.exe run_richard.py --force     # 全部重转
  .venv\\Scripts\\python.exe run_richard.py --organize  # 只整理（转换已完成时）
  .venv\\Scripts\\python.exe run_richard.py --cleanup   # 只清理中间产物
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

# ===== 路径配置 =====
ROOT = Path(r"D:\working\vscode-projects\instrument-agnostic-amt-main")
NEW_DIR = ROOT / "newversion-20260726"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"

SOURCE = Path(r"D:\开源合集\开源 2022.9.14\芯片音乐\自制芯片音乐\MIDI识别合集\midi识别 2021\理查德克莱德曼")
TARGET = Path(r"D:\开源合集\开源 2022.9.14\芯片音乐\自制芯片音乐\MIDI识别合集\MIDI识别 2026\20260726")
WORK_DIR = TARGET / "_work"   # 中间产物（stem wav / 各stem midi）

AUDIO_EXTS = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".aiff", ".aif", ".opus"}
LOG_FILE = ROOT / "run_richard.log"

# ===== 子进程: 调用新版分轨流程（独立进程，便于隔离 + log） =====
WORKER_SCRIPT = NEW_DIR / "_richard_worker.py"


def log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def write_worker_script():
    """生成子进程脚本: 单文件分轨+力度转换"""
    WORKER_SCRIPT.write_text(
        f'''import os, sys
from pathlib import Path
sys.path.insert(0, r"{NEW_DIR}")
os.chdir(r"{ROOT}")  # 让新版找到 ./checkpoints
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
import importlib.util
spec = importlib.util.spec_from_file_location("nb_helpers", r"{NEW_DIR / '_nb_helpers.py'}")
nb = importlib.util.module_from_spec(spec); spec.loader.exec_module(nb)

audio = Path(sys.argv[1])
out_root = Path(sys.argv[2])
r = nb.run_stem_separated_transcription(
    audio,
    checkpoint_path=None,
    output_root=str(out_root),
    window_batch_size=4,
    max_midi_melodic_instruments=15,
    transcribe_drum_stems=True,
    predict_velocity=True,
    cleanup_separated_stems=False,
    merge_onset_ms=50.0,
)
print("MERGED:" + str(r["merged_midi_path"]))
''',
        encoding="utf-8",
    )


def find_audio_files():
    """遍历源目录所有音频，返回 [(audio, rel_for_structure)]。
    理查德目录是平铺的，rel 就是文件名本身。"""
    files = []
    for f in sorted(SOURCE.rglob("*")):
        if f.is_file() and f.suffix.lower() in AUDIO_EXTS:
            rel = f.relative_to(SOURCE)
            files.append((f, rel))
    return files


def expected_final_midi(audio_rel):
    """源音频相对路径 -> 最终 MIDI 路径。
    保留源目录结构: TARGET/<源顶层目录名>/<相对子路径>/<曲名>.mid
    理查德源是 平铺的 mp3，所以 = TARGET/理查德克莱德曼/<曲名>.mid"""
    return TARGET / SOURCE.name / audio_rel.with_suffix(".mid")


def get_missing(force=False):
    all_files = find_audio_files()
    if force:
        return all_files
    missing = []
    for f, rel in all_files:
        final = expected_final_midi(rel)
        if not (final.exists() and final.stat().st_size > 100):
            missing.append((f, rel))
    return missing


def transcribe_one(audio, rel):
    """转换单个文件: 调用子进程跑分轨+力度，产物在 _work/<曲名>/merged/"""
    song_stem = Path(audio).stem
    work_root = WORK_DIR / song_stem  # 子进程会在这里建 <song_stem>/merged/
    # 子进程内部会再建一层 <audio.stem>，所以 merged 路径是 work_root/<song_stem>/merged/<song_stem>_velocity.mid
    return work_root


def find_merged_midi(work_root, song_stem):
    """在 work_root 下找最终 merged velocity midi"""
    # run_stem_separated_transcription 内部: out_root/<audio.stem>/merged/<audio.stem>_velocity.mid
    candidate = work_root / song_stem / "merged" / f"{song_stem}_velocity.mid"
    if candidate.exists():
        return candidate
    # 退化: 搜索
    for p in work_root.rglob("*_velocity.mid"):
        return p
    for p in work_root.rglob("*.mid"):
        if "stem_midis" not in str(p):
            return p
    return None


def organize():
    """整理: 把 _work 下的 merged velocity midi 提到 TARGET 根"""
    log("=" * 50)
    log("整理阶段: 把分轨产物提到目标根目录")
    moved = 0
    for audio, rel in find_audio_files():
        song_stem = audio.stem
        work_root = WORK_DIR / song_stem
        if not work_root.exists():
            log(f"  跳过(无工作目录): {song_stem}")
            continue
        merged = find_merged_midi(work_root, song_stem)
        final = expected_final_midi(rel)
        if merged and merged.exists():
            final.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(merged), str(final))
            sz = final.stat().st_size
            log(f"  ✓ {song_stem} -> {final.name} ({sz} bytes)")
            moved += 1
        else:
            log(f"  ✗ 未找到 merged: {song_stem}")
    log(f"整理完成: {moved} 个 MIDI 已就位 -> {TARGET}")


def cleanup():
    """清理中间产物 _work 目录"""
    if WORK_DIR.exists():
        # 统计大小
        total = sum(f.stat().st_size for f in WORK_DIR.rglob('*') if f.is_file())
        log(f"清理中间产物: {WORK_DIR} (约 {total//1024//1024} MB)")
        shutil.rmtree(WORK_DIR, ignore_errors=True)
        # 也删 worker 脚本
        try:
            WORKER_SCRIPT.unlink()
        except Exception:
            pass
        log("清理完成")
    else:
        log(f"无需清理: {WORK_DIR} 不存在")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="强制重转所有")
    parser.add_argument("--organize", action="store_true", help="只整理（不转换）")
    parser.add_argument("--cleanup", action="store_true", help="只清理中间产物")
    args = parser.parse_args()

    # 清空 log 重新开始（保留历史在 git 里）
    LOG_FILE.write_text("", encoding="utf-8")

    log("=" * 50)
    log("理查德克莱德曼 - 新版分轨+力度批量转换")
    log(f"源:   {SOURCE}")
    log(f"目标: {TARGET}")
    log(f"工作: {WORK_DIR}")
    log(f"log:  {LOG_FILE}")
    log("=" * 50)

    all_files = find_audio_files()
    log(f"源音频总数: {len(all_files)}")

    if args.cleanup:
        cleanup()
        return
    if args.organize:
        organize()
        return

    write_worker_script()
    missing = get_missing(force=args.force)
    log(f"待转换: {len(missing)}")

    if not missing:
        log("全部已转换，执行整理...")
        organize()
        return

    log("\n待转换清单:")
    for f, rel in missing:
        log(f"  {rel}")

    t_start = time.time()
    done = 0
    failed = []

    for i, (audio, rel) in enumerate(missing, 1):
        song_stem = audio.stem
        log(f"\n[{i}/{len(missing)}] 开始: {song_stem} ({audio.stat().st_size//1024} KB)")
        t0 = time.time()

        # 最终 MIDI 已存在则跳过（断点续跑）
        final = expected_final_midi(rel)
        if final.exists() and final.stat().st_size > 100 and not args.force:
            log(f"  已存在,跳过: {final.name}")
            done += 1
            continue

        work_root = transcribe_one(audio, rel)
        # 调用子进程
        import subprocess
        result = subprocess.run(
            [str(VENV_PY), "-u", str(WORKER_SCRIPT), str(audio), str(work_root)],
            capture_output=True, text=True, timeout=900,
            encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONPATH": str(NEW_DIR), "CUDA_VISIBLE_DEVICES": "0",
                 "HF_ENDPOINT": "https://hf-mirror.com", "PYTHONUNBUFFERED": "1"},
        )
        elapsed = time.time() - t0

        # 找 merged midi
        merged = find_merged_midi(work_root, song_stem)
        if merged and merged.exists() and merged.stat().st_size > 100:
            # 立即整理到目标
            final.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(merged), str(final))
            log(f"  ✓ 完成 ({elapsed:.0f}s) -> {final.name} ({final.stat().st_size} bytes)")
            done += 1
        else:
            err = (result.stderr or result.stdout or "")[-300:]
            log(f"  ✗ 失败 ({elapsed:.0f}s): {err.strip()[:200]}")
            failed.append(song_stem)

        # 进度估算
        elapsed_total = time.time() - t_start
        rate = i / elapsed_total * 60 if elapsed_total > 0 else 0
        remain = (len(missing) - i) / rate if rate > 0 else 0
        log(f"  进度: {i}/{len(missing)} ({i*100//len(missing)}%) 速度 {rate:.1f}/min 剩余 ~{remain:.0f}min")

    log("\n" + "=" * 50)
    log(f"转换完成: 成功 {done}, 失败 {len(failed)}, 总计 {len(missing)}")
    if failed:
        log(f"失败文件: {failed}")
    log(f"耗时: {(time.time()-t_start)/60:.1f} 分钟")
    log("\n执行整理...")
    organize()
    log("\n全部完成。确认无误后运行: python run_richard.py --cleanup")


if __name__ == "__main__":
    main()
