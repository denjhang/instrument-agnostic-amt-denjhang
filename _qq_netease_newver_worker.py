import os, sys, shutil, hashlib, subprocess
from pathlib import Path
sys.path.insert(0, r"D:\working\vscode-projects\instrument-agnostic-amt-main\newversion-20260823\instrument-agnostic-amt-main")
os.chdir(r"D:\working\vscode-projects\instrument-agnostic-amt-main")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
import audioread.ffdec as _ffdec, imageio_ffmpeg as _iio
_ffdec.COMMANDS = (str(_iio.get_ffmpeg_exe()),)  # audioread 后端指向绝对路径, 免受 PATH 环境影响
from infer_stem import run_stem_separated_transcription

audio = Path(sys.argv[1])
out_root = Path(sys.argv[2])

# Windows 路径超 260 防护
orig_stem = audio.stem
short_stem = "s" + hashlib.md5(orig_stem.encode("utf-8")).hexdigest()[:10]
est_path_len = len(str(out_root)) + len(orig_stem) * 5 + 80
need_short = est_path_len > 240 or len(orig_stem) > 30

if need_short:
    tmp_dir = out_root.parent / "_short_inputs"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    short_audio = tmp_dir / (short_stem + audio.suffix)
    if not short_audio.exists():
        shutil.copy2(str(audio), str(short_audio))
    run_audio = short_audio
    run_out_root = out_root / short_stem
else:
    run_audio = audio
    run_out_root = out_root

r = run_stem_separated_transcription(
    run_audio,
    checkpoint_path=None,
    output_root=str(run_out_root),
    window_batch_size=4,
    max_midi_melodic_instruments=15,
    transcribe_drum_stems=True,
    predict_velocity=True,
    refine_instruments=True,
    predict_beat_chord=True,
    cleanup_separated_stems=True,
    merge_onset_ms=20.0,
)
print("MERGED:" + str(r["merged_midi_path"]))
