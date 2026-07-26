#!/usr/bin/env python3
"""对比两种鼓声检测方式 - 完整分轨流程:

方法1: 强制 _use_interval_instrument_head=True (模拟 Colab)
  - 所有 stem (包括 drums) 都走 AMT 模型
  - default/bass/vocal_harmony/guitar/other 各模型强制开启 interval head

方法2: onset detection v2 (当前本地方式)
  - drums stem 用 onset detection
  - 其他 stem 走 AMT (正常 fallback)

输出两个 MIDI 文件到同一目录供对比。
"""

import io
import sys
import torch
from pathlib import Path

if getattr(sys.stdout, 'encoding', '') != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

import numpy as np
import pretty_midi
import soundfile as sf
import infer
from stem_infer import (
    transcribe_drum_stem, merge_midis, _safe_path,
    resolve_stem_paths, prepare_audio_for_stem_separation,
    get_stem_pipeline_models,
)
from stem_splitter.inference import SeparationConfig, _separate_one_file, load_mss_model

AUDIO = Path(r"d:\working\vscode-projects\instrument-agnostic-amt-main\Coup De Coeur.mp3")
OUTPUT_DIR = Path(r"d:\working\vscode-projects\instrument-agnostic-amt-main\compare_drum_output")

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def transcribe_stem_with_amt(bundle, stem_path, output_midi, force_interval_head=False):
    """用 AMT 模型转录单个 stem"""
    if force_interval_head:
        bundle["amt_model"]._use_interval_instrument_head = True

    try:
        waveform, _, _ = infer._load_audio(
            Path(stem_path),
            target_sample_rate=bundle["amt_config"].sample_rate,
        )
        if waveform.numel() == 0 or waveform.abs().max() < 1e-6:
            print(f"  Skipping empty stem")
            return None
    except (ValueError, RuntimeError) as e:
        print(f"  Skipping bad stem: {e}")
        return None

    device = bundle["device"]
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
        merge_onset_ms=20.0,
        max_note_seconds=15.0,
        silence_gate_rms_dbfs=-72,
        window_batch_size=4,
        max_midi_melodic_instruments=15,
        disable_tqdm=False,
    )

    midi = infer._build_midi(
        notes,
        sample_rate=bundle["amt_config"].sample_rate,
        instrument_volumes=dict(infer.DEFAULT_INSTRUMENT_VOLUMES),
    )
    midi.write(_safe_path(output_midi))
    return output_midi


def run_full_pipeline(force_interval_head=False, label=""):
    """走完整分轨流程，返回合并后的 MIDI"""
    import hashlib
    import shutil

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # 加载模型
    print(f"\n{'='*60}")
    print(f"加载模型 ({label})")
    print(f"{'='*60}")

    default_bundle = get_stem_pipeline_models(model_type="default")
    bass_bundle = get_stem_pipeline_models(model_type="bass")
    vocal_bundle = get_stem_pipeline_models(model_type="vocal_harmony")
    guitar_bundle = get_stem_pipeline_models(model_type="guitar")
    other_bundle = get_stem_pipeline_models(model_type="other")

    if force_interval_head:
        for name, bundle in [("default", default_bundle), ("bass", bass_bundle),
                             ("vocal_harmony", vocal_bundle), ("guitar", guitar_bundle),
                             ("other", other_bundle)]:
            bundle["amt_model"]._use_interval_instrument_head = True
            print(f"  {name}: forced _use_interval_instrument_head = True")

    sep_config = default_bundle["sep_config"]
    sep_model = default_bundle["sep_model"]
    sep_dtype = default_bundle["sep_dtype"]

    # Stem 分离
    short_name = hashlib.md5(AUDIO.stem.encode()).hexdigest()[:12]
    run_root = Path("D:/stem_amt_temp") / short_name
    stem_dir = run_root / "stems"
    stem_midi_dir = run_root / "stem_midis"
    for directory in (stem_dir, stem_midi_dir):
        directory.mkdir(parents=True, exist_ok=True)

    separation_input = prepare_audio_for_stem_separation(AUDIO, temp_dir=run_root / "prepared_inputs")
    max_stem_len = 30
    if len(separation_input.stem) > max_stem_len:
        short_input = run_root / f"input{separation_input.suffix}"
        shutil.copy2(str(separation_input), str(short_input))
        separation_input = short_input

    print(f"\nStem 分离: {AUDIO.name}")
    stems = _separate_one_file(separation_input, stem_dir, sep_config, sep_model, device, sep_dtype)
    if not stems:
        stems = resolve_stem_paths(AUDIO, stem_dir, sep_config.stem_names)

    print(f"分离出 {len(stems)} 个 stem: {sorted(stems.keys())}")

    # 转录每个 stem
    song_midi_paths = []
    for stem_name, stem_path in sorted(stems.items()):
        safe_stem = AUDIO.stem[:80]
        output_midi = stem_midi_dir / f"{safe_stem}_{stem_name}.mid"
        stem_lower = stem_name.lower()

        print(f"\n转录 stem: {stem_name}")

        if force_interval_head:
            # 方法1: 鼓声也走 AMT (强制 interval head)
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
            result = transcribe_stem_with_amt(bundle, stem_path, output_midi, force_interval_head=True)
        else:
            # 方法2: 鼓声用 onset, 其他走 AMT
            is_drum = "drum" in stem_lower
            if is_drum:
                midi = transcribe_drum_stem(stem_path, output_midi)
                if midi is not None:
                    song_midi_paths.append(output_midi)
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
            result = transcribe_stem_with_amt(bundle, stem_path, output_midi, force_interval_head=False)

        if result is not None:
            song_midi_paths.append(result)

    if not song_midi_paths:
        print("ERROR: 没有生成任何 MIDI")
        return None

    # 合并
    final_path = OUTPUT_DIR / f"{label}.mid"
    merge_midis(song_midi_paths, final_path, max_melodic=15)

    # 统计
    midi = pretty_midi.PrettyMIDI(str(final_path))
    drum_insts = [inst for inst in midi.instruments if inst.is_drum]
    non_drum_insts = [inst for inst in midi.instruments if not inst.is_drum]
    drum_notes = sum(len(inst.notes) for inst in drum_insts)
    total_notes = sum(len(inst.notes) for inst in midi.instruments)

    print(f"\n--- {label} 结果 ---")
    print(f"轨道: {len(midi.instruments)} (鼓: {len(drum_insts)}, 非鼓: {len(non_drum_insts)})")
    print(f"音符: {total_notes} (鼓: {drum_notes}, {drum_notes*100/max(total_notes,1):.1f}%)")
    for inst in drum_insts:
        print(f"  [鼓] {inst.name} (program={inst.program}): {len(inst.notes)} notes")
    for inst in non_drum_insts:
        print(f"  [非鼓] {inst.name} (program={inst.program}): {len(inst.notes)} notes")

    return midi


def main():
    print(f"音频: {AUDIO.name}")
    print(f"存在: {AUDIO.exists()}")
    print(f"输出目录: {OUTPUT_DIR}")

    if not AUDIO.exists():
        print(f"ERROR: 音频文件不存在: {AUDIO}")
        return

    midi1 = run_full_pipeline(force_interval_head=True, label="method1_colab_simulation")
    midi2 = run_full_pipeline(force_interval_head=False, label="method2_onset_v2")

    print("\n" + "=" * 60)
    print("对比总结")
    print("=" * 60)
    for label, midi in [("方法1 (Colab模拟)", midi1), ("方法2 (onset v2)", midi2)]:
        if midi is None:
            print(f"{label}: 无输出")
            continue
        drum = sum(len(inst.notes) for inst in midi.instruments if inst.is_drum)
        total = sum(len(inst.notes) for inst in midi.instruments)
        print(f"{label}: 总={total}, 鼓={drum} ({drum*100/max(total,1):.1f}%)")

    print(f"\n文件: {OUTPUT_DIR}")
    print("用 MIDI 编辑器打开两个 .mid 文件对比听效果")


if __name__ == "__main__":
    main()
