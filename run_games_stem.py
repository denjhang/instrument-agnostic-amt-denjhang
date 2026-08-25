#!/usr/bin/env python3
"""游戏音乐批量分轨+力度转换（与 20260726 任务并行）

源: F:\\存储器备份\\2023.1.17 音乐档案\\MP3格式 下指定游戏目录
  - PopKart (跑跑卡丁车, 27个子目录, 多层嵌套)
  - QQ堂背景音乐合集
  - qq自由幻想音乐
  - 赛尔号bgm合集（素材）
  - 梦4BGM (梦幻西游)
输出: TARGET/<游戏名>/<完整源子路径>/<曲名>.mid  （完全保留源目录结构）
流程: 新版官方分轨流程（stem分离 → 各stem专用模型 → 合并 → 力度预测）
与 20260726 任务共用两张 GPU（显存充裕，并行不冲突）

用法:
  .venv\\Scripts\\python.exe run_games_stem.py
  .venv\\Scripts\\python.exe run_games_stem.py --cleanup
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

SOURCE = Path(r"F:\存储器备份\2023.1.17 音乐档案\MP3格式")
TARGET = Path(r"D:\开源合集\开源 2022.9.14\芯片音乐\自制芯片音乐\MIDI识别合集\MIDI识别 2026\20260727")
WORK_DIR = TARGET / "_work"

GAME_DIRS = ["PopKart", "QQ堂背景音乐合集", "qq自由幻想音乐", "赛尔号bgm合集（素材）", "梦4BGM"]
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".aiff", ".aif", ".opus"}
LOG_FILE = ROOT / "run_games_stem.log"

GPUS = [0, 1]  # 两张 GPU 各一个 worker（与 20260726 任务共享）
WORKER_SCRIPT = NEW_DIR / "_games_stem_worker.py"


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
short_stem = "g" + hashlib.md5(orig_stem.encode("utf-8")).hexdigest()[:10]
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
    run_audio, checkpoint_path=None, output_root=str(run_out_root),
    window_batch_size=4, max_midi_melodic_instruments=15,
    transcribe_drum_stems=True, predict_velocity=True,
    cleanup_separated_stems=False, merge_onset_ms=50.0,
)
print("MERGED:" + str(r["merged_midi_path"]))
'''.replace("{NEW_DIR}", new_dir_str).replace("{ROOT}", root_str).replace("{NB_HELPERS}", nb_helpers_str)
    WORKER_SCRIPT.write_text(worker_code, encoding="utf-8")


def find_all_audios():
    """返回 [(audio_path, game_name)] 遍历所有游戏目录"""
    result = []
    for g in GAME_DIRS:
        d = SOURCE / g
        if not d.exists():
            log(f"⚠ 游戏目录不存在: {g}"); continue
        for f in sorted(d.rglob("*")):
            if f.is_file() and f.suffix.lower() in AUDIO_EXTS:
                result.append((f, g))
    return result


def expected_final_midi(audio, game_name):
    """完全保留源目录结构: TARGET/<游戏名>/<源内相对路径>.mid"""
    rel_in_game = audio.relative_to(SOURCE / game_name)
    return TARGET / game_name / rel_in_game.with_suffix(".mid")


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


def worker_proc(task_queue, result_queue, gpu_id):
    """每个 worker 绑定一张 GPU（顶层函数, Windows spawn 可 pickle）"""
    import subprocess as sp
    while True:
        item = task_queue.get()
        if item is None:
            break
        idx, total, audio, game_name, final = item
        song_stem = audio.stem
        disp = f"{game_name}/{audio.relative_to(SOURCE / game_name)}"
        t0 = time.time()
        # work_root 用 hash 短名, 避免长游戏名+长曲名导致路径超 260
        import hashlib as _hl
        work_name = "g" + _hl.md5(f"{game_name}/{song_stem}".encode("utf-8")).hexdigest()[:12]
        work_root = WORK_DIR / work_name
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


def cleanup():
    if WORK_DIR.exists():
        total = sum(f.stat().st_size for f in WORK_DIR.rglob('*') if f.is_file())
        log(f"清理中间产物: {WORK_DIR} (约 {total//1024//1024} MB)")
        shutil.rmtree(WORK_DIR, ignore_errors=True)
        try: WORKER_SCRIPT.unlink()
        except Exception: pass
        log("清理完成")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--cleanup", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.cleanup:
        cleanup(); return

    LOG_FILE.write_text("", encoding="utf-8")
    log("=" * 50)
    log("游戏音乐批量分轨+力度转换")
    log(f"源:   {SOURCE}")
    log(f"目标: {TARGET}")
    log(f"工作: {WORK_DIR}")
    log(f"游戏: {GAME_DIRS}")
    log("=" * 50)

    write_worker_script()
    all_audios = find_all_audios()
    log(f"音频总数: {len(all_audios)}")

    # 统计每个游戏
    from collections import Counter
    cnt = Counter(g for _, g in all_audios)
    for g in GAME_DIRS:
        if g in cnt:
            log(f"  {g}: {cnt[g]} 首")

    # 过滤已完成的（断点续跑）
    tasks = []
    for audio, game_name in all_audios:
        final = expected_final_midi(audio, game_name)
        if args.force or not (final.exists() and final.stat().st_size > 100):
            tasks.append((audio, game_name, final))
    log(f"待转换: {len(tasks)}")

    if args.dry_run:
        for audio, game_name, final in tasks[:20]:
            log(f"  {game_name}/{audio.relative_to(SOURCE/game_name)} -> {final.relative_to(TARGET)}")
        if len(tasks) > 20:
            log(f"  ... 共 {len(tasks)} 个")
        return

    if not tasks:
        log("全部已转换!"); return

    from multiprocessing import Process, Queue
    total = len(tasks)
    task_queue = Queue()
    result_queue = Queue()
    for i, (audio, game_name, final) in enumerate(tasks, 1):
        task_queue.put((i, total, audio, game_name, final))
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
    log(f"\n输出: {TARGET}")
    log("确认无误后运行: python run_games_stem.py --cleanup")


if __name__ == "__main__":
    main()
