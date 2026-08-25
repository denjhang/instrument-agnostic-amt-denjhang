import os, sys, shutil, hashlib, subprocess
from pathlib import Path
sys.path.insert(0, r"D:\working\vscode-projects\instrument-agnostic-amt-main\newversion-20260726")
os.chdir(r"D:\working\vscode-projects\instrument-agnostic-amt-main")
os.environ.setdefault("CUDA_VISIBLE_DEVICES","0")
os.environ.setdefault("HF_ENDPOINT","https://hf-mirror.com")
import importlib.util
spec = importlib.util.spec_from_file_location("nb_helpers", r"D:\working\vscode-projects\instrument-agnostic-amt-main\newversion-20260726\_nb_helpers.py")
nb = importlib.util.module_from_spec(spec); spec.loader.exec_module(nb)
import imageio_ffmpeg
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
audio_path = Path(sys.argv[1]); out_root = Path(sys.argv[2])
VIDEO_EXTS = {".mp4",".mkv",".avi",".mov",".flv",".webm"}
tmp_wav = None
if audio_path.suffix.lower() in VIDEO_EXTS:
    tmp_wav = out_root / "_audio_input.wav"
    tmp_wav.parent.mkdir(parents=True, exist_ok=True)
    if not tmp_wav.exists():
        cmd = [FFMPEG,"-y","-i",str(audio_path),"-vn","-acodec","pcm_s16le","-ar","44100","-ac","2",str(tmp_wav)]
        r = subprocess.run(cmd, capture_output=True, timeout=300)
        if r.returncode != 0 or not tmp_wav.exists():
            raise RuntimeError("ffmpeg failed: " + r.stderr.decode("utf-8","replace")[-200:])
    run_input = tmp_wav
else:
    run_input = audio_path
orig_stem = audio_path.stem
short_stem = "l" + hashlib.md5(orig_stem.encode("utf-8")).hexdigest()[:10]
need_short = len(orig_stem) > 30 or len(str(out_root)) + len(orig_stem)*5 + 80 > 240
if need_short:
    tmp = out_root / "_short_inputs"; tmp.mkdir(parents=True, exist_ok=True)
    sa = tmp / (short_stem + run_input.suffix)
    if run_input != sa and not sa.exists(): shutil.copy2(str(run_input), str(sa))
    run_audio = sa; run_out_root = out_root / short_stem
else:
    run_audio = run_input; run_out_root = out_root
r = nb.run_stem_separated_transcription(run_audio, checkpoint_path=None, output_root=str(run_out_root),
    window_batch_size=4, max_midi_melodic_instruments=15, transcribe_drum_stems=True,
    predict_velocity=True, cleanup_separated_stems=False, merge_onset_ms=50.0)
print("MERGED:" + str(r["merged_midi_path"]))
