#!/usr/bin/env python3
"""对比实验 3/3: CC11 expression 分支 (haveyouwantto/expression, 20260823)"""
import sys
from pathlib import Path

ROOT = Path(r"D:\working\vscode-projects\instrument-agnostic-amt-main")
NEW = ROOT / "expression-20260823" / "instrument-agnostic-amt-expression"
sys.path.insert(0, str(NEW))
import os
os.chdir(str(ROOT))
os.environ["CUDA_VISIBLE_DEVICES"] = "0"
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from infer_stem import run_stem_separated_transcription

audio = ROOT / "compare_ys_audio.wav"
out = ROOT / "compare3_out" / "expression"
r = run_stem_separated_transcription(
    audio, checkpoint_path=None, output_root=str(out),
    window_batch_size=4, max_midi_melodic_instruments=15,
    transcribe_drum_stems=True, predict_velocity=True,
    refine_instruments=True, predict_beat_chord=True,
    transcribe_lyrics=False, predict_expression=True,
    cleanup_separated_stems=True,
)
print("MERGED:" + str(r["merged_midi_path"]))
