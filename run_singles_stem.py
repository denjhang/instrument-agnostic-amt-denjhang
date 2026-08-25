#!/usr/bin/env python3
"""根目录散落单曲（21首）- 分轨+力度转换
临时专辑 _root_singles/, 输出到 20260726/_root_singles/
"""
import io, os, shutil, sys, time, hashlib
from datetime import datetime
from pathlib import Path

if getattr(sys.stdout, 'encoding', '') != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

ROOT = Path(r"D:\working\vscode-projects\instrument-agnostic-amt-main")
NEW_DIR = ROOT / "newversion-20260726"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
SOURCE = Path(r"F:\KwDownload\song\_root_singles")
TARGET = Path(r"D:\开源合集\开源 2022.9.14\芯片音乐\自制芯片音乐\MIDI识别合集\MIDI识别 2026\20260726\_root_singles")
WORK_DIR = Path(r"D:\开源合集\开源 2022.9.14\芯片音乐\自制芯片音乐\MIDI识别合集\MIDI识别 2026\20260726\_work_singles")
AUDIO_EXTS = {".mp3",".wav",".flac",".ogg",".m4a",".aac",".wma",".aiff",".aif",".opus"}
LOG_FILE = ROOT / "run_singles_stem.log"
GPUS = [0,1]
WORKER_SCRIPT = NEW_DIR / "_singles_stem_worker.py"

def log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE,"a",encoding="utf-8") as f: f.write(line+"\n")
    except: pass

def write_worker_script():
    worker_code = '''import os, sys, shutil, hashlib
from pathlib import Path
sys.path.insert(0, r"{NEW_DIR}")
os.chdir(r"{ROOT}")
os.environ.setdefault("CUDA_VISIBLE_DEVICES","0")
os.environ.setdefault("HF_ENDPOINT","https://hf-mirror.com")
import importlib.util
spec = importlib.util.spec_from_file_location("nb_helpers", r"{NB_HELPERS}")
nb = importlib.util.module_from_spec(spec); spec.loader.exec_module(nb)
audio = Path(sys.argv[1]); out_root = Path(sys.argv[2])
orig_stem = audio.stem
short_stem = "x" + hashlib.md5(orig_stem.encode("utf-8")).hexdigest()[:10]
need_short = len(orig_stem) > 30 or len(str(out_root)) + len(orig_stem)*5 + 80 > 240
if need_short:
    tmp = out_root / "_short_inputs"; tmp.mkdir(parents=True, exist_ok=True)
    sa = tmp / (short_stem + audio.suffix)
    if not sa.exists(): shutil.copy2(str(audio), str(sa))
    run_audio = sa; run_out_root = out_root / short_stem
else:
    run_audio = audio; run_out_root = out_root
r = nb.run_stem_separated_transcription(run_audio, checkpoint_path=None, output_root=str(run_out_root),
    window_batch_size=4, max_midi_melodic_instruments=15, transcribe_drum_stems=True,
    predict_velocity=True, cleanup_separated_stems=False, merge_onset_ms=50.0)
print("MERGED:" + str(r["merged_midi_path"]))
'''.replace("{NEW_DIR}",str(NEW_DIR)).replace("{ROOT}",str(ROOT)).replace("{NB_HELPERS}",str(NEW_DIR/"_nb_helpers.py"))
    WORKER_SCRIPT.write_text(worker_code, encoding="utf-8")

def expected_final(audio):
    final = TARGET / audio.with_suffix(".mid").name
    if len(str(final)) > 240:
        digest = hashlib.md5(final.name.encode("utf-8")).hexdigest()[:8]
        stem, ext = final.name.rsplit(".",1)
        keep = max(8, 240 - len(str(final.parent)) - 1 - len(digest) - 1 - len(ext))
        final = final.parent / f"{stem[:keep]}~{digest}.{ext}"
    return final

def find_merged_midi(work_root, song_stem):
    c = work_root / song_stem / "merged" / f"{song_stem}_velocity.mid"
    if c.exists(): return c
    for p in work_root.rglob("*_velocity.mid"): return p
    for p in work_root.rglob("*.mid"):
        if "stem_midis" not in str(p): return p
    return None

def worker_proc(task_queue, result_queue, gpu_id):
    import subprocess as sp
    while True:
        item = task_queue.get()
        if item is None: break
        idx, total, audio, final = item
        song_stem = audio.stem
        work_name = "x" + hashlib.md5(song_stem.encode("utf-8")).hexdigest()[:12]
        work_root = WORK_DIR / work_name
        t0 = time.time()
        try:
            result = sp.run([str(VENV_PY),"-u",str(WORKER_SCRIPT),str(audio),str(work_root)],
                capture_output=True, text=True, timeout=1800, encoding="utf-8", errors="replace",
                env={**os.environ,"PYTHONPATH":str(NEW_DIR),"CUDA_VISIBLE_DEVICES":str(gpu_id),
                     "HF_ENDPOINT":"https://hf-mirror.com","PYTHONUNBUFFERED":"1"})
            elapsed = time.time()-t0
            merged = None
            for line in (result.stdout or "").splitlines():
                if line.startswith("MERGED:"): merged = Path(line[7:].strip()); break
            if not merged or not merged.exists():
                merged = find_merged_midi(work_root, song_stem)
            if merged and merged.exists() and merged.stat().st_size > 100:
                final.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(merged), str(final))
                try: shutil.rmtree(work_root, ignore_errors=True)
                except: pass
                result_queue.put(("OK",idx,total,audio.name,gpu_id,elapsed,final.stat().st_size))
            else:
                err = (result.stderr or result.stdout or "")[-200:]
                result_queue.put(("FAIL",idx,total,audio.name,gpu_id,elapsed,err.strip()[:150]))
        except Exception as e:
            result_queue.put(("FAIL",idx,total,audio.name,gpu_id,time.time()-t0,str(e)[:150]))

def main():
    LOG_FILE.write_text("",encoding="utf-8")
    log("="*50); log("根目录单曲 21首 - 分轨+力度"); log("="*50)
    write_worker_script()
    all_audios = sorted(f for f in SOURCE.iterdir() if f.is_file() and f.suffix.lower() in AUDIO_EXTS)
    tasks = [(a, expected_final(a)) for a in all_audios if not (expected_final(a).exists() and expected_final(a).stat().st_size>100)]
    log(f"待转换: {len(tasks)}")
    if not tasks: log("全部完成!"); return
    from multiprocessing import Process, Queue
    total = len(tasks)
    tq, rq = Queue(), Queue()
    for i,(a,final) in enumerate(tasks,1): tq.put((i,total,a,final))
    for _ in GPUS: tq.put(None)
    procs=[]
    for gpu_id in GPUS:
        p=Process(target=worker_proc,args=(tq,rq,gpu_id),daemon=True); p.start(); procs.append(p)
        log(f"启动 Worker GPU{gpu_id}"); time.sleep(10)
    t0=time.time(); done=failed=0
    while done+failed<total:
        try: item=rq.get(timeout=30)
        except: continue
        st,idx,_,name,gpu,el,extra=item
        if st=="OK": done+=1; log(f"  [OK] [{done+failed}/{total}] GPU{gpu} {name[:55]} ({el:.0f}s,{extra}B)")
        else: failed+=1; log(f"  [FAIL] [{done+failed}/{total}] GPU{gpu} {name[:55]} ({el:.0f}s) {extra[:120]}")
        et=time.time()-t0; rate=(done+failed)/et*60 if et>0 else 0
        log(f"  进度: {done+failed}/{total} ({(done+failed)*100//total}%) {rate:.1f}/min")
    for p in procs: p.join(timeout=5)
    log(f"\n完成: 成功{done} 失败{failed}")

if __name__=="__main__": main()
