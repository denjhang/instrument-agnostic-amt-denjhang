#!/usr/bin/env python3
"""Stem-Separated Transcription Script

Separates audio into stems, transcribes each with specialized models, and merges results.
"""

import argparse
import io
import os
import shutil
import sys
from collections import defaultdict
from pathlib import Path

# 修复 Windows 260 字符路径限制
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    except Exception:
        pass

def _safe_path(p):
    """确保路径在 Windows 上不超过 260 字符限制"""
    sp = os.path.normpath(str(p))
    if sys.platform == "win32" and len(sp) > 200:
        drive, rest = os.path.splitdrive(sp)
        parts = rest.split(os.sep)
        filename = parts[-1]
        name, ext = os.path.splitext(filename)
        max_total = 200
        overhead = len(drive) + sum(len(p) + 1 for p in parts[:-1])
        max_name = max_total - overhead - len(ext)
        if max_name < 10:
            max_name = 10
        filename = name[:max_name] + ext
        parts[-1] = filename
        sp = drive + os.sep.join(parts)
    return sp
def _fix_stdio():
    """确保 UTF-8 编码输出，若已是 UTF-8 wrapper 则跳过"""
    if getattr(sys.stdout, 'encoding', '') == 'utf-8':
        return
    _orig_stdout = sys.stdout
    _orig_stderr = sys.stderr
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    except (AttributeError, ValueError):
        sys.stdout = _orig_stdout
        sys.stderr = _orig_stderr

_orig_print = print
def print(*args, **kwargs):
    try:
        _orig_print(*args, **kwargs)
    except (ValueError, OSError):
        pass
_fix_stdio()

import numpy as np
import pretty_midi
import soundfile as sf
import torch

import infer
from stem_splitter.inference import SeparationConfig, _separate_one_file, load_mss_model


# 全局缓存，避免重复加载模型
STEM_PIPELINE_CACHE = {}


def merge_midis(midi_paths, output_file, max_melodic=15):
    """合并多个 MIDI 文件为一个"""
    if not midi_paths:
        raise ValueError("No MIDI files to merge")

    master_pm = pretty_midi.PrettyMIDI(str(midi_paths[0]))

    all_notes = defaultdict(list)
    all_ccs = defaultdict(list)
    all_pbends = defaultdict(list)
    instrument_names = {}

    for path in midi_paths:
        pm = pretty_midi.PrettyMIDI(str(path))
        for inst in pm.instruments:
            key = (inst.program, inst.is_drum, inst.name)
            filtered_notes = [n for n in inst.notes if (n.end - n.start) < 15.0]
            all_notes[key].extend(filtered_notes)
            all_ccs[key].extend(inst.control_changes)
            all_pbends[key].extend(inst.pitch_bends)
            if key not in instrument_names:
                instrument_names[key] = inst.name

    melodic_keys = [k for k in all_notes.keys() if not k[1]]
    drum_keys = [k for k in all_notes.keys() if k[1]]
    melodic_keys.sort(key=lambda k: len(all_notes[k]), reverse=True)

    final_instruments = []
    if len(melodic_keys) > max_melodic:
        kept_keys = melodic_keys[:max_melodic - 1]
        overflow_keys = melodic_keys[max_melodic - 1:]

        for key in kept_keys:
            inst = pretty_midi.Instrument(
                program=key[0], is_drum=key[1], name=instrument_names[key]
            )
            inst.notes = all_notes[key]
            inst.control_changes = all_ccs[key]
            inst.pitch_bends = all_pbends[key]
            final_instruments.append(inst)

        base_key = overflow_keys[0]
        overflow_inst = pretty_midi.Instrument(
            program=base_key[0], is_drum=base_key[1], name="Other / Merged"
        )
        for key in overflow_keys:
            overflow_inst.notes.extend(all_notes[key])
            overflow_inst.control_changes.extend(all_ccs[key])
            overflow_inst.pitch_bends.extend(all_pbends[key])
        final_instruments.append(overflow_inst)
    else:
        for key in melodic_keys:
            inst = pretty_midi.Instrument(
                program=key[0], is_drum=key[1], name=instrument_names[key]
            )
            inst.notes = all_notes[key]
            inst.control_changes = all_ccs[key]
            inst.pitch_bends = all_pbends[key]
            final_instruments.append(inst)

    for key in drum_keys:
        inst = pretty_midi.Instrument(
            program=key[0], is_drum=key[1], name=instrument_names[key]
        )
        inst.notes = all_notes[key]
        inst.control_changes = all_ccs[key]
        inst.pitch_bends = all_pbends[key]
        final_instruments.append(inst)

    master_pm.instruments = final_instruments
    for inst in master_pm.instruments:
        inst.notes.sort(key=lambda note: note.start)
        inst.control_changes.sort(key=lambda x: x.time)
        inst.pitch_bends.sort(key=lambda x: x.time)
    master_pm.write(_safe_path(output_file))
    print(f"Merged {len(midi_paths)} MIDI files -> {output_file}")


def transcribe_drum_stem(drum_audio_path, output_midi_path):
    """用 onset detection 转录鼓声 stem，直接生成 MIDI 鼓轨道

    分频段独立检测，带交叉抑制：snare onset 如果 kick 频段同时触发则视为底鼓。
    """
    import scipy.signal as sig
    import numpy as np

    data, sr = sf.read(str(drum_audio_path))
    if data.ndim == 1:
        data = data[:, None]
    audio = data[:, 0]
    duration = len(audio) / sr

    if np.abs(audio).max() < 1e-6:
        print(f"Skipping empty drum stem")
        return None

    nyq = sr / 2.0
    hop_ms = 10
    hop = int(sr * hop_ms / 1000)
    n_frames = len(audio) // hop

    # snare 频段上移到 200-500Hz 避开 kick 泛音
    bands = [
        (20, 200, "kick"),
        (200, 500, "snare"),
        (300, 800, "tom"),
        (5000, 20000, "hihat"),
    ]

    envelopes = {}
    for lo, hi, label in bands:
        lo_n = max(lo / nyq, 0.001)
        hi_n = min(hi / nyq, 0.999)
        try:
            b, a = sig.butter(2, [lo_n, hi_n], btype='band')
            filtered = sig.filtfilt(b, a, audio)
        except Exception:
            continue
        env = np.abs(filtered)
        win = max(int(0.005 * sr / hop), 2)
        kernel = np.ones(win) / win
        env = np.convolve(env[::hop], kernel, mode='same')
        envelopes[label] = env[:n_frames]

    midi = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(program=0, is_drum=True, name="drums")

    min_interval_ms = {
        "kick": 100,
        "snare": 80,
        "tom": 100,
        "hihat": 40,
    }

    gm_map = {
        "kick": 36,
        "snare": 38,
        "tom": 45,
        "hihat": 42,
    }

    threshold_mult = {
        "kick": 2.5,
        "snare": 3.5,
        "tom": 4.0,
        "hihat": 3.0,
    }

    # 先检测所有频段的 peaks
    all_peaks = {}
    for label, env in envelopes.items():
        if len(env) < 10:
            continue

        diff = np.diff(env, prepend=0)
        diff = np.maximum(diff, 0)

        mean_diff = np.mean(diff)
        std_diff = np.std(diff)
        threshold = mean_diff + threshold_mult[label] * std_diff
        if threshold < 0.001:
            threshold = 0.001

        min_gap = int(min_interval_ms[label] / hop_ms)
        peaks = []
        last_peak = -min_gap
        for i in range(1, len(diff)):
            if diff[i] > threshold and (i - last_peak) >= min_gap:
                if i + 1 < len(env) and env[i] > env[max(0, i - 3)]:
                    peaks.append(i)
                    last_peak = i

        all_peaks[label] = set(peaks)

    # 交叉抑制: snare peak 如果 kick 同时有 onset (±3帧=±30ms)，则从 snare 中移除
    kick_peaks = all_peaks.get("kick", set())
    snare_peaks = all_peaks.get("snare", set())
    suppressed = snare_peaks & {p + d for p in kick_peaks for d in range(-3, 4)}
    snare_peaks -= suppressed
    # 被抑制的 snare 归入 kick
    all_peaks["kick"] = kick_peaks | suppressed
    all_peaks["snare"] = snare_peaks

    # 生成 MIDI notes
    dur_ms = {"kick": 80, "snare": 50, "tom": 60, "hihat": 30}
    for label, peak_set in all_peaks.items():
        note_number = gm_map[label]
        for pf in sorted(peak_set):
            start = pf * hop_ms / 1000.0
            dur = dur_ms[label] / 1000.0
            if start + dur > duration:
                dur = duration - start
            if dur <= 0:
                continue
            inst.notes.append(pretty_midi.Note(
                velocity=100,
                pitch=note_number,
                start=start,
                end=start + dur,
            ))

    if len(inst.notes) == 0:
        print(f"No drum onsets detected")
        return None

    inst.notes.sort(key=lambda n: n.start)
    midi.instruments.append(inst)

    from collections import Counter
    types = Counter(n.pitch for n in inst.notes)
    gm_rev = {36: "Bass Drum", 38: "Snare", 42: "HH", 45: "Tom"}
    parts = [f"{gm_rev.get(p, str(p))}:{types[p]}" for p in sorted(types)]
    print(f"Drum onset detection: {len(inst.notes)} hits ({', '.join(parts)})")

    midi.write(_safe_path(output_midi_path))
    return midi


def resolve_stem_paths(song_path, stem_dir, stem_names):
    """查找已存在的 stem 文件"""
    song_file = Path(song_path)
    song_id = song_file.stem
    stem_root = Path(stem_dir) / song_id
    resolved = {}

    for stem_name in stem_names:
        expected_path = stem_root / f"{song_id}_{stem_name}.wav"
        if expected_path.exists():
            resolved[stem_name] = expected_path

    if resolved:
        return resolved

    if not stem_root.exists():
        return resolved

    for wav_path in sorted(stem_root.glob("*.wav")):
        stem_key = wav_path.stem
        for stem_name in stem_names:
            if stem_key.endswith(f"_{stem_name}"):
                resolved.setdefault(stem_name, wav_path)
                break

    return resolved


def prepare_audio_for_stem_separation(audio_path, temp_dir):
    """准备音频用于 stem 分离"""
    audio_file = Path(audio_path)

    try:
        import librosa
        waveform, sample_rate = librosa.load(str(audio_file), sr=None, mono=False)
    except Exception as e:
        # 如果 librosa 加载失败，尝试 soundfile
        data, sample_rate = sf.read(str(audio_file), always_2d=True)
        waveform = data.T

    if waveform.ndim == 1:
        waveform = waveform[None, :]
    elif waveform.ndim == 2 and waveform.shape[0] > waveform.shape[1]:
        waveform = waveform.T

    source_channels = int(waveform.shape[0])
    if source_channels <= 0:
        raise ValueError(f"Audio file has no channels: {audio_path}")

    if source_channels == 2:
        return audio_file

    if source_channels == 1:
        waveform = np.repeat(waveform, 2, axis=0)
        channel_mode = "pseudo-stereo"
    else:
        waveform = waveform[:2]
        channel_mode = "first-two-channels"

    temp_dir = Path(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    prepared_path = temp_dir / f"{audio_file.stem}.wav"
    sf.write(str(prepared_path), waveform.T, samplerate=int(sample_rate))
    print(f"Prepared {channel_mode} input for stem separation")

    return prepared_path


def get_stem_pipeline_models(checkpoint_path=None, device=None, model_type="default"):
    """加载 AMT 和 stem 分离模型"""
    device = device or torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # 加载 AMT 模型
    checkpoint = infer._ensure_checkpoint(
        None if checkpoint_path in (None, "", "DEFAULT") else Path(checkpoint_path),
        model_type=model_type
    )
    amt_cache_key = ("amt", str(checkpoint.resolve()), device.type, model_type)

    if amt_cache_key not in STEM_PIPELINE_CACHE:
        print(f"Loading AMT model ({model_type}) on {device}...")
        amt_model, amt_config, amt_settings = infer._load_model_and_settings(
            checkpoint,
            device=device,
            window_ms_override=None,
            stride_ms_override=None,
            track_batch_size_override=None,
        )
        STEM_PIPELINE_CACHE[amt_cache_key] = (amt_model, amt_config, amt_settings)
    else:
        print(f"Reusing cached AMT model ({model_type})")
        amt_model, amt_config, amt_settings = STEM_PIPELINE_CACHE[amt_cache_key]

    # 加载 stem 分离模型
    sep_cache_key = ("sep", device.type)
    if sep_cache_key not in STEM_PIPELINE_CACHE:
        print(f"Loading stem separation model on {device}...")
        sep_config = SeparationConfig(skip_existing=False)
        sep_model = load_mss_model(sep_config, device=device)
        sep_dtype = torch.float16 if sep_config.use_half_precision and device.type == "cuda" else torch.float32
        STEM_PIPELINE_CACHE[sep_cache_key] = (sep_config, sep_model, sep_dtype)
    else:
        print(f"Reusing cached stem separation model")
        sep_config, sep_model, sep_dtype = STEM_PIPELINE_CACHE[sep_cache_key]

    return {
        "device": device,
        "checkpoint": checkpoint,
        "amt_model": amt_model,
        "amt_config": amt_config,
        "amt_settings": amt_settings,
        "sep_config": sep_config,
        "sep_model": sep_model,
        "sep_dtype": sep_dtype,
    }


def run_stem_separated_transcription(
    audio_path,
    checkpoint_path=None,
    output_root="stem_outputs",
    window_batch_size=4,
    max_midi_melodic_instruments=15,
    skip_drum_stems=False,
    cleanup_separated_stems=False,
    merge_onset_ms=20.0,
):
    """执行分轨转录流程"""
    audio_file = Path(audio_path)
    if not audio_file.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    print(f"Processing: {audio_file.name}")

    # 加载所有需要的模型
    default_bundle = get_stem_pipeline_models(checkpoint_path=checkpoint_path, model_type="default")
    bass_bundle = get_stem_pipeline_models(checkpoint_path=checkpoint_path, model_type="bass")
    vocal_bundle = get_stem_pipeline_models(checkpoint_path=checkpoint_path, model_type="vocal_harmony")
    guitar_bundle = get_stem_pipeline_models(checkpoint_path=checkpoint_path, model_type="guitar")
    other_bundle = get_stem_pipeline_models(checkpoint_path=checkpoint_path, model_type="other")

    device = default_bundle["device"]
    sep_config = default_bundle["sep_config"]
    sep_model = default_bundle["sep_model"]
    sep_dtype = default_bundle["sep_dtype"]

    # 临时目录放在 D 盘，避免 C 盘空间不足
    # 用 hash 生成短目录名，避免长文件名导致 Windows 路径超限
    import hashlib
    short_name = hashlib.md5(audio_file.stem.encode()).hexdigest()[:12]
    run_root = Path("D:/stem_amt_temp") / short_name
    stem_dir = run_root / "stems"
    stem_midi_dir = run_root / "stem_midis"
    merged_dir = run_root / "merged"
    for directory in (stem_dir, stem_midi_dir, merged_dir):
        directory.mkdir(parents=True, exist_ok=True)

    # Stem 分离
    separation_input = prepare_audio_for_stem_separation(
        audio_file, temp_dir=run_root / "prepared_inputs"
    )
    # 确保传给 stem_splitter 的文件名足够短，避免 Windows 路径超限
    # _separate_one_file 会用 input.stem 构建 output_path，嵌套后路径可能超 260 字符
    max_stem_len = 30
    if len(separation_input.stem) > max_stem_len:
        import shutil as _shutil
        short_input = run_root / f"input{separation_input.suffix}"
        _shutil.copy2(str(separation_input), str(short_input))
        separation_input = short_input

    print(f"Separating stems for: {audio_file.name}")
    stems = _separate_one_file(
        separation_input,
        stem_dir,
        sep_config,
        sep_model,
        device,
        sep_dtype,
    )

    # 处理已存在的 stems
    if not stems:
        stems = resolve_stem_paths(
            song_path=audio_file,
            stem_dir=stem_dir,
            stem_names=sep_config.stem_names,
        )
        if stems:
            print(f"Reusing existing stems: {sorted(stems)}")
        else:
            raise RuntimeError(f"No stems found for {audio_file.stem}")

    # 转录每个 stem
    song_midi_paths = []
    for stem_name, stem_path in sorted(stems.items()):
        if skip_drum_stems and "drum" in stem_name.lower():
            print(f"Skipping drum stem: {stem_name}")
            continue

        # 截断长文件名避免 Windows 260 字符路径限制
        safe_stem = audio_file.stem[:80]
        output_midi = stem_midi_dir / f"{safe_stem}_{stem_name}.mid"
        print(f"Transcribing stem: {stem_name}")

        # 根据 stem 类型选择专用模型
        stem_lower = stem_name.lower()

        # 鼓声 stem 用 onset detection（1511 hits），不走 AMT（AMT 只能检测到 ~94 个高频 hit）
        is_drum_stem = "drum" in stem_lower
        if is_drum_stem:
            midi = transcribe_drum_stem(stem_path, output_midi)
            if midi is not None:
                song_midi_paths.append(output_midi)
            else:
                print(f"Drum stem produced no notes, skipping")
            continue

        if "bass" in stem_lower:
            bundle = bass_bundle
        elif "vocal" in stem_lower:
            bundle = vocal_bundle
        elif "guitar" in stem_lower:
            bundle = guitar_bundle
        elif "other" in stem_lower:
            bundle = other_bundle
        else:
            bundle = default_bundle

        try:
            waveform, _, _ = infer._load_audio(
                Path(stem_path),
                target_sample_rate=bundle["amt_config"].sample_rate,
            )
            # 跳过空 stem（waveform 为空或接近零）
            if waveform.numel() == 0 or waveform.abs().max() < 1e-6:
                print(f"Skipping empty stem: {stem_name}")
                continue
        except (ValueError, RuntimeError) as e:
            print(f"Skipping bad stem: {stem_name} ({e})")
            continue

        notes, _, _ = infer.run_inference(
            model=bundle["amt_model"],
            waveform=waveform.to(device),
            model_config=bundle["amt_config"],
            settings=bundle["amt_settings"],
            device=device,
            amp_enabled=False,
            amp_dtype=torch.float16 if device.type == "cuda" else torch.float32,
            velocity=100,
            merge_gap_ms=None,
            merge_onset_ms=merge_onset_ms,
            max_note_seconds=15.0,
            silence_gate_rms_dbfs=-72,
            window_batch_size=window_batch_size,
            max_midi_melodic_instruments=max_midi_melodic_instruments,
            disable_tqdm=False,
        )

        midi = infer._build_midi(
            notes,
            sample_rate=bundle["amt_config"].sample_rate,
            instrument_volumes=dict(infer.DEFAULT_INSTRUMENT_VOLUMES)
        )
        midi.write(_safe_path(output_midi))
        song_midi_paths.append(output_midi)

    if not song_midi_paths:
        raise RuntimeError("No stem MIDI files were generated")

    # 合并 MIDI，直接输出到 output_root（保持目录结构）
    output_root_path = Path(output_root)
    output_root_path.mkdir(parents=True, exist_ok=True)
    final_midi_path = output_root_path / f"{audio_file.stem}.mid"
    merge_midis(song_midi_paths, final_midi_path, max_melodic=max_midi_melodic_instruments)

    # 清理临时文件
    if cleanup_separated_stems:
        import gc, time
        gc.collect()
        time.sleep(0.5)
        for attempt in range(10):
            try:
                shutil.rmtree(run_root, ignore_errors=False)
                print(f"Temp cleaned: {run_root}")
                break
            except PermissionError:
                gc.collect()
                time.sleep(2)
            except Exception:
                time.sleep(1)
        else:
            shutil.rmtree(run_root, ignore_errors=True)
            print(f"Temp force-cleaned: {run_root}")

    result = {
        "audio_path": str(audio_file),
        "output_root": str(output_root_path),
        "final_midi_path": str(final_midi_path),
        "stem_count": len(stems),
        "transcribed_stem_count": len(song_midi_paths),
    }
    print("\n=== Result ===")
    print(f"Merged MIDI: {final_midi_path}")
    print(f"Stems processed: {len(song_midi_paths)}")
    return result


def parse_args():
    parser = argparse.ArgumentParser(
        description="Stem-separated transcription with specialized AMT models"
    )
    parser.add_argument("--audio", type=Path, required=True, help="Input audio file")
    parser.add_argument(
        "--output-root",
        type=Path,
        default="stem_outputs",
        help="Output directory for results",
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=None,
        help="Path to checkpoint (auto-downloads if not specified)",
    )
    parser.add_argument(
        "--window-batch-size",
        type=int,
        default=4,
        help="Number of windows to process at once (default: 4)",
    )
    parser.add_argument(
        "--max-midi-melodic-instruments",
        type=int,
        default=15,
        help="Maximum melodic instruments in output MIDI (default: 15)",
    )
    parser.add_argument(
        "--no-skip-drum",
        action="store_true",
        help="Do not skip drum stems during transcription",
    )
    parser.add_argument(
        "--cleanup-stems",
        action="store_true",
        help="Delete temporary files after transcription",
    )
    parser.add_argument(
        "--merge-onset-ms",
        type=float,
        default=20.0,
        help="Merge threshold for near-simultaneous onsets in ms (default: 20.0)",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    result = run_stem_separated_transcription(
        audio_path=args.audio,
        checkpoint_path=args.checkpoint,
        output_root=args.output_root,
        window_batch_size=args.window_batch_size,
        max_midi_melodic_instruments=args.max_midi_melodic_instruments,
        skip_drum_stems=False,
        cleanup_separated_stems=args.cleanup_stems,
        merge_onset_ms=args.merge_onset_ms,
    )

    print("\nDone!")
    return result


if __name__ == "__main__":
    main()
