#!/usr/bin/env python3
"""对比实验 1/3: 当前版本 (newversion-20260726 官方分轨流程)"""
import importlib.util, sys
from pathlib import Path

ROOT = Path(r"D:\working\vscode-projects\instrument-agnostic-amt-main")
NEW = ROOT / "newversion-20260726"
sys.path.insert(0, str(NEW))
import os
os.chdir(str(ROOT))
os.environ["CUDA_VISIBLE_DEVICES"] = "0"
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

spec = importlib.util.spec_from_file_location("nb_helpers", str(NEW / "_nb_helpers.py"))
nb = importlib.util.module_from_spec(spec); spec.loader.exec_module(nb)

audio = ROOT / "compare_ys_audio.wav"
out = ROOT / "compare3_out" / "current"
r = nb.run_stem_separated_transcription(
    audio, checkpoint_path=None, output_root=str(out),
    window_batch_size=4, max_midi_melodic_instruments=15,
    transcribe_drum_stems=True, predict_velocity=True,
    cleanup_separated_stems=True, merge_onset_ms=50.0,
)
print("MERGED:" + str(r["merged_midi_path"]))
