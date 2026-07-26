#!/usr/bin/env python3
"""Test: run stem_infer on one file and capture all output"""
import io, os, sys, subprocess
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
from pathlib import Path

VENV_PY = Path(__file__).parent / ".venv" / "Scripts" / "python.exe"
SCRIPT = Path(__file__).parent / "stem_infer.py"

# First missing file from the list
audio = Path(r"E:\存储器备份\2024.10.30 音乐卡16G\40首曲\Various.Artists.-.[40.Most.Beautiful.Orchestral.Classics].专辑.(Mp3)\17. Vivaldi - Concerto in G major for 2 Mandolins RV532  I Allegro (Concerto in G major for 2 Mandolins RV532  I Allegro) - Claudio Scimone.mp3")
output_dir = Path(r"D:\temp_test_midi\40首曲\Various.Artists.-.[40.Most.Beautiful.Orchestral.Classics].专辑.(Mp3)")
output_dir.mkdir(parents=True, exist_ok=True)

print(f"Audio exists: {audio.exists()}")
print(f"Audio path: {audio}")
print(f"Audio str bytes: {str(audio).encode('utf-8')[:100]}")
print(f"Running subprocess...")
print(f"cmd: {[str(VENV_PY), str(SCRIPT), '--audio', str(audio)[:80]+'...', '--output-root', str(output_dir)[:80]+'...', '--cleanup-stems']}")

result = subprocess.run(
    [str(VENV_PY), str(SCRIPT), "--audio", str(audio),
     "--output-root", str(output_dir), "--cleanup-stems"],
    capture_output=True, text=True, timeout=300,
    encoding='utf-8', errors='replace',
)

print(f"\n=== EXIT CODE: {result.returncode} ===")
print(f"=== STDOUT ===\n{result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout}")
print(f"=== STDERR ===\n{result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr}")
