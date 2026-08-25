import os, sys, shutil, hashlib
from pathlib import Path
sys.path.insert(0, r"D:\working\vscode-projects\instrument-agnostic-amt-main\newversion-20260726")
os.chdir(r"D:\working\vscode-projects\instrument-agnostic-amt-main")
os.environ.setdefault("CUDA_VISIBLE_DEVICES","0")
os.environ.setdefault("HF_ENDPOINT","https://hf-mirror.com")
import importlib.util
spec = importlib.util.spec_from_file_location("nb_helpers", r"D:\working\vscode-projects\instrument-agnostic-amt-main\newversion-20260726\_nb_helpers.py")
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
