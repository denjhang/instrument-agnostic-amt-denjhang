#!/usr/bin/env python3
"""Test multiprocessing queue with Chinese file paths"""
import io, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
from multiprocessing import Process, Queue
from pathlib import Path
import subprocess

SOURCE = Path(r"E:\存储器备份\2024.10.30 音乐卡16G")
VENV_PY = Path(__file__).parent / ".venv" / "Scripts" / "python.exe"
SCRIPT = Path(__file__).parent / "stem_infer.py"

def worker(task_queue, result_queue, gpu_id):
    os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_id)
    while True:
        item = task_queue.get()
        if item is None:
            break
        idx, total, audio = item
        print(f"Worker received: idx={idx}, path={audio}, exists={audio.exists()}")

        # Just test if subprocess can see the file
        rel = audio.relative_to(SOURCE)
        output_dir = Path(r"D:\temp_test_midi") / rel.parent
        output_dir.mkdir(parents=True, exist_ok=True)

        result = subprocess.run(
            [str(VENV_PY), str(SCRIPT), "--help"],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=30,
        )
        print(f"subprocess --help exit: {result.returncode}")

        # Test with actual audio arg but just validate
        result2 = subprocess.run(
            [str(VENV_PY), "-c", f"from pathlib import Path; p=Path(r'{audio}'); print(f'exists={{p.exists()}}')"],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=10,
        )
        print(f"path check stdout: {result2.stdout.strip()}")
        print(f"path check stderr: {result2.stderr.strip()}")

        result_queue.put(("OK", idx, total, audio.name, gpu_id, 0))

if __name__ == "__main__":
    # Find one actual audio file with Chinese chars in path
    AUDIO_EXTS = {".mp3", ".wav", ".flac"}
    test_file = None
    for f in sorted(SOURCE.rglob("*")):
        if f.is_file() and f.suffix.lower() in AUDIO_EXTS:
            test_file = f
            break

    if not test_file:
        print("No test file found")
        sys.exit(1)

    print(f"Main process test file: {test_file}")
    print(f"Main exists: {test_file.exists()}")

    q = Queue()
    rq = Queue()
    q.put((1, 1, test_file))
    q.put(None)

    p = Process(target=worker, args=(q, rq, 0))
    p.start()
    p.join(timeout=30)

    try:
        status, idx, total, name, gpu, elapsed = rq.get(timeout=5)
        print(f"Result: {status}")
    except:
        print("No result from queue")
