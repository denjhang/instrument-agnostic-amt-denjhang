import os, sys, shutil, hashlib
from pathlib import Path
sys.path.insert(0, r"D:\working\vscode-projects\instrument-agnostic-amt-main\newversion-20260823\instrument-agnostic-amt-main")
os.chdir(r"D:\working\vscode-projects\instrument-agnostic-amt-main")
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
