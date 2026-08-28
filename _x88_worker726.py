import os, sys, importlib.util
from pathlib import Path
sys.path.insert(0, r"D:\working\vscode-projects\instrument-agnostic-amt-main\newversion-20260726")
os.chdir(r"D:\working\vscode-projects\instrument-agnostic-amt-main")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
spec = importlib.util.spec_from_file_location("nb_helpers", r"D:\working\vscode-projects\instrument-agnostic-amt-main\newversion-20260726\_nb_helpers.py")
nb = importlib.util.module_from_spec(spec); spec.loader.exec_module(nb)
audio = Path(sys.argv[1]); out_root = Path(sys.argv[2])
r = nb.run_stem_separated_transcription(
    audio, checkpoint_path=None, output_root=str(out_root),
    window_batch_size=4, max_midi_melodic_instruments=15,
    transcribe_drum_stems=True, predict_velocity=True,
    cleanup_separated_stems=True, merge_onset_ms=50.0)
print("MERGED:" + str(r["merged_midi_path"]))
