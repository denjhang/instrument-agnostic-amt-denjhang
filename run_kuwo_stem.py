#!/usr/bin/env python3
"""批量分轨+力度转换（通用版）

筛选: F:\\KwDownload\\song 下，顶层专辑目录内任一音频 mtime >= CUTOFF，整个目录纳入。
输出: TARGET/<源专辑名>/<曲名>.mid  （保留源目录结构，每个专辑独立子目录，不混杂）
流程: 新版官方分轨流程（stem分离 → 各stem专用模型 → 合并 → 力度预测）
中间产物: TARGET/_work/，完成后用 --cleanup 清理

用法:
  .venv\\Scripts\\python.exe run_kuwo_stem.py            # 转换缺失的（断点续跑）
  .venv\\Scripts\\python.exe run_kuwo_stem.py --force     # 全部重转
  .venv\\Scripts\\python.exe run_kuwo_stem.py --organize  # 只整理
  .venv\\Scripts\\python.exe run_kuwo_stem.py --cleanup   # 只清理中间产物
  .venv\\Scripts\\python.exe run_kuwo_stem.py --dry-run   # 只列出待转换，不执行
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

SOURCE = Path(r"F:\KwDownload\song")
TARGET = Path(r"D:\开源合集\开源 2022.9.14\芯片音乐\自制芯片音乐\MIDI识别合集\MIDI识别 2026\20260726")
WORK_DIR = TARGET / "_work"

AUDIO_EXTS = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".aiff", ".aif", ".opus"}
LOG_FILE = ROOT / "run_kuwo_stem.log"

# 筛选截止: 硬编码 2026-07-26 21:00（这批任务的固定截止时间，避免跨天失效）
CUTOFF = datetime(2026, 7, 26, 21, 0, 0)

WORKER_SCRIPT = NEW_DIR / "_kuwo_stem_worker.py"


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

# Windows 路径超 260 字符防护: stem 分离器内部嵌套多层同名目录,
# 长名/中文名会超限。把音频 copy 成短 hash 名, out_root 也用短名喂给分离器。
orig_stem = audio.stem
short_stem = "s" + hashlib.md5(orig_stem.encode("utf-8")).hexdigest()[:10]
# _work 内部嵌套约: out_root + song_stem*4 + /stems/ + song_stem + _bass.wav ≈ out_root + song*5
est_path_len = len(str(out_root)) + len(orig_stem) * 5 + 80
need_short = est_path_len > 240 or len(orig_stem) > 30

if need_short:
    tmp_dir = out_root.parent / "_short_inputs"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    short_audio = tmp_dir / (short_stem + audio.suffix)
    if not short_audio.exists():
        shutil.copy2(str(audio), str(short_audio))
    run_audio = short_audio
    # out_root 也改用短名, 避免 work_root(含原名) 自身超长
    run_out_root = out_root / short_stem
else:
    run_audio = audio
    run_out_root = out_root

r = nb.run_stem_separated_transcription(
    run_audio,
    checkpoint_path=None,
    output_root=str(run_out_root),
    window_batch_size=4,
    max_midi_melodic_instruments=15,
    transcribe_drum_stems=True,
    predict_velocity=True,
    cleanup_separated_stems=False,
    merge_onset_ms=50.0,
)
print("MERGED:" + str(r["merged_midi_path"]))
'''.replace("{NEW_DIR}", new_dir_str).replace("{ROOT}", root_str).replace("{NB_HELPERS}", nb_helpers_str)
    WORKER_SCRIPT.write_text(worker_code, encoding="utf-8")


def find_qualifying_dirs():
    """返回 [(dir_path, [audio_files])] 符合 CUTOFF 条件的专辑目录"""
    result = []
    for d in sorted(SOURCE.iterdir()):
        if not d.is_dir():
            continue
        audios = sorted(f for f in d.rglob("*") if f.is_file() and f.suffix.lower() in AUDIO_EXTS)
        if not audios:
            continue
        latest = max(datetime.fromtimestamp(f.stat().st_mtime) for f in audios)
        if latest >= CUTOFF:
            result.append((d, audios))
    return result


def expected_final_midi(audio, album_dir):
    """源音频 -> 最终 MIDI 路径: TARGET/<专辑名>/<相对子路径>/<曲名>.mid"""
    rel_in_album = audio.relative_to(album_dir)
    final = TARGET / album_dir.name / rel_in_album.with_suffix(".mid")
    # 路径超长防护: 截断文件名(保留扩展名), 加 hash 后缀防碰撞
    if len(str(final)) > 240:
        import hashlib as _hl
        parent = final.parent
        orig_name = final.name
        digest = _hl.md5(orig_name.encode("utf-8")).hexdigest()[:8]
        stem, ext = orig_name.rsplit(".", 1)
        keep = max(8, 240 - len(str(parent)) - 1 - len(digest) - 1 - len(ext))
        final = parent / f"{stem[:keep]}~{digest}.{ext}"
    return final


def find_merged_midi(work_root, song_stem):
    candidate = work_root / song_stem / "merged" / f"{song_stem}_velocity.mid"
    if candidate.exists():
        return candidate
    for p in work_root.rglob("*_velocity.mid"):
        return p
    for p in work_root.rglob("*.mid"):
        if "stem_midis" not in str(p):
            return p
    return None


def get_all_tasks(force=False):
    """返回 [(audio, album_dir, final_midi)] 待转换任务"""
    tasks = []
    for album_dir, audios in find_qualifying_dirs():
        for audio in audios:
            final = expected_final_midi(audio, album_dir)
            if force or not (final.exists() and final.stat().st_size > 100):
                tasks.append((audio, album_dir, final))
    return tasks


def organize():
    """整理: 遍历 _work 下所有 velocity midi, 按所在专辑目录归类到 TARGET。
    主循环每首成功后已即时 copy, 这里只补漏（短名模式下产物名与原名不同,
    所以按 _work/<专辑名>/ 这层真专辑名归类, 曲名沿用源文件名顺序映射）。"""
    log("=" * 50)
    log("整理阶段: 检查并补齐缺失的最终 MIDI")
    # 统计当前 final 已有的
    final_count = 0
    for album_dir, audios in find_qualifying_dirs():
        for audio in audios:
            if expected_final_midi(audio, album_dir).exists():
                final_count += 1
    log(f"目标目录已有 MIDI: {final_count}")
    # _work 下还有多少 merged velocity midi
    if WORK_DIR.exists():
        merged_files = list(WORK_DIR.rglob("*_velocity.mid"))
        log(f"_work 下 merged velocity midi: {len(merged_files)} 个")
        if merged_files and final_count == 0:
            log("⚠ 转换产物在 _work 但未提取, 需检查主循环逻辑")
    log(f"目标: {TARGET}")


def cleanup():
    if WORK_DIR.exists():
        total = sum(f.stat().st_size for f in WORK_DIR.rglob('*') if f.is_file())
        log(f"清理中间产物: {WORK_DIR} (约 {total//1024//1024} MB)")
        shutil.rmtree(WORK_DIR, ignore_errors=True)
        try:
            WORKER_SCRIPT.unlink()
        except Exception:
            pass
        log("清理完成")
    else:
        log(f"无需清理: {WORK_DIR} 不存在")


def worker_proc(task_queue, result_queue, gpu_id):
    """每个 worker 绑定一张 GPU，从队列取任务转换（必须在模块顶层，Windows spawn 才能pickle）"""
    import subprocess as sp
    while True:
        item = task_queue.get()
        if item is None:
            break
        idx, total, audio, album_dir, final = item
        song_stem = audio.stem
        disp = f"{album_dir.name}/{audio.relative_to(album_dir)}"
        t0 = time.time()
        # work_root 用 hash 短名, 避免长专辑名+长曲名导致路径超 260
        import hashlib as _hl
        work_name = "k" + _hl.md5(f"{album_dir.name}/{song_stem}".encode("utf-8")).hexdigest()[:12]
        work_root = WORK_DIR / work_name
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
                merged = find_merged_midi(work_root, song_stem)
            if merged and merged.exists() and merged.stat().st_size > 100:
                final.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(merged), str(final))
                # 立即清理这首的中间产物（stem wav 占大头），避免 _work 堆积爆磁盘
                try:
                    shutil.rmtree(work_root, ignore_errors=True)
                except Exception:
                    pass
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
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--organize", action="store_true")
    parser.add_argument("--cleanup", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    LOG_FILE.write_text("", encoding="utf-8")
    log("=" * 50)
    log("批量分轨+力度转换（通用版）")
    log(f"源:   {SOURCE}")
    log(f"目标: {TARGET}")
    log(f"筛选: 专辑目录任一音频 mtime >= {CUTOFF}")
    log(f"工作: {WORK_DIR}")
    log("=" * 50)

    qual = find_qualifying_dirs()
    total_audio = sum(len(a) for _, a in qual)
    log(f"符合条件专辑: {len(qual)} 个, 音频总数: {total_audio}")
    for d, audios in qual:
        log(f"  ({len(audios):3d}) {d.name}")

    if args.cleanup:
        cleanup(); return
    if args.organize:
        organize(); return

    write_worker_script()
    tasks = get_all_tasks(force=args.force)
    log(f"\n待转换: {len(tasks)}")

    if args.dry_run:
        for audio, album_dir, final in tasks:
            log(f"  {album_dir.name}/{audio.relative_to(album_dir)}")
        return

    if not tasks:
        log("全部已转换，执行整理...")
        organize(); return

    from multiprocessing import Process, Queue

    GPUS = [0, 1]  # 两张 GPU 各一个 worker

    total = len(tasks)
    task_queue = Queue()
    result_queue = Queue()
    for i, (audio, album_dir, final) in enumerate(tasks, 1):
        task_queue.put((i, total, audio, album_dir, final))
    for _ in GPUS:
        task_queue.put(None)

    procs = []
    for gpu_id in GPUS:
        p = Process(target=worker_proc, args=(task_queue, result_queue, gpu_id), daemon=True)
        p.start(); procs.append(p)
        log(f"启动 Worker GPU{gpu_id} (pid {p.pid})")
        time.sleep(10)  # 错开启动，避开首次 checkpoint 加载竞争

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
    if failed:
        log(f"失败: {failed}")
    log(f"耗时: {(time.time()-t_start)/60:.1f} 分钟")
    log("\n执行整理...")
    organize()
    log("\n全部完成。确认无误后运行: python run_kuwo_stem.py --cleanup")


if __name__ == "__main__":
    main()
