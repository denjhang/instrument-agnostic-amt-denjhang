#!/usr/bin/env python3
"""Batch convert audio files to MIDI using AMT models

Maintains directory structure from source to destination.
Supports both fast (direct) and stem-separated transcription modes.
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading


# 支持的音频格式
SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".flac", ".ogg", ".opus", ".m4a", ".aac", ".wma", ".aiff", ".aif"}

# 全局锁用于输出同步
output_lock = threading.Lock()
progress_counter = {"total": 0, "processed": 0, "failed": 0, "skipped": 0}


def find_audio_files(source_dir: Path, exclude_dirs: list[str] = None) -> list[Path]:
    """递归查找所有音频文件，排除指定目录"""
    exclude_dirs = exclude_dirs or []
    audio_files = []
    for path in source_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            # 检查是否在排除目录中
            try:
                rel_path = path.relative_to(source_dir)
                if any(part.lower() in exclude_dirs for part in rel_path.parts):
                    continue
            except ValueError:
                pass
            audio_files.append(path)
    return sorted(audio_files)


def get_relative_path(source_file: Path, source_root: Path) -> Path:
    """获取相对路径"""
    try:
        return source_file.relative_to(source_root)
    except ValueError:
        return source_file.name


def convert_fast_mode(audio_file: Path, output_dir: Path, venv_path: Path, script_dir: Path) -> dict:
    """快速模式转换"""
    with output_lock:
        progress_counter["total"] += 1

    try:
        midi_output = output_dir / audio_file.with_suffix(".mid").name

        # 检查是否已存在
        if midi_output.exists():
            with output_lock:
                progress_counter["skipped"] += 1
                print(f"[SKIP] {audio_file.name} (already exists)")
            return {"status": "skipped", "input": str(audio_file), "output": str(midi_output)}

        # 调用 infer.py
        result = subprocess.run(
            [
                str(venv_path / "Scripts" / "python.exe"),
                str(script_dir / "infer.py"),
                "--audio", str(audio_file),
                "--output-midi", str(midi_output),
            ],
            capture_output=True,
            text=True,
            timeout=1800,  # 30分钟超时
        )

        if result.returncode == 0 and midi_output.exists():
            with output_lock:
                progress_counter["processed"] += 1
                print(f"[OK] Fast: {audio_file.name}")
            return {"status": "success", "input": str(audio_file), "output": str(midi_output)}
        else:
            with output_lock:
                progress_counter["failed"] += 1
                print(f"[FAIL] Fast: {audio_file.name}")
            return {"status": "failed", "input": str(audio_file), "error": result.stderr[-500:]}

    except subprocess.TimeoutExpired:
        with output_lock:
            progress_counter["failed"] += 1
            print(f"[TIMEOUT] Fast: {audio_file.name}")
        return {"status": "timeout", "input": str(audio_file)}
    except Exception as e:
        with output_lock:
            progress_counter["failed"] += 1
            print(f"[ERROR] Fast: {audio_file.name} - {e}")
        return {"status": "error", "input": str(audio_file), "error": str(e)}


def convert_stem_mode(audio_file: Path, output_dir: Path, venv_path: Path, script_dir: Path) -> dict:
    """分轨模式转换"""
    with output_lock:
        progress_counter["total"] += 1

    try:
        # 分轨模式：MIDI 直接输出到目标目录
        expected_midi = output_dir / f"{audio_file.stem}.mid"
        if expected_midi.exists():
            with output_lock:
                progress_counter["skipped"] += 1
                print(f"[SKIP] {audio_file.name} (already exists)")
            return {"status": "skipped", "input": str(audio_file), "output": str(expected_midi)}

        # 调用 stem_infer.py
        result = subprocess.run(
            [
                str(venv_path / "Scripts" / "python.exe"),
                str(script_dir / "stem_infer.py"),
                "--audio", str(audio_file),
                "--output-root", str(output_dir),
                "--cleanup-stems",
            ],
            capture_output=True,
            text=True,
            timeout=3600,  # 60分钟超时（分轨更慢）
        )

        if result.returncode == 0 and expected_midi.exists():
            with output_lock:
                progress_counter["processed"] += 1
                print(f"[OK] Stem: {audio_file.name}")
            return {"status": "success", "input": str(audio_file), "output": str(expected_midi)}
        else:
            with output_lock:
                progress_counter["failed"] += 1
                print(f"[FAIL] Stem: {audio_file.name}")
            return {"status": "failed", "input": str(audio_file), "error": result.stderr[-500:]}

    except subprocess.TimeoutExpired:
        with output_lock:
            progress_counter["failed"] += 1
            print(f"[TIMEOUT] Stem: {audio_file.name}")
        return {"status": "timeout", "input": str(audio_file)}
    except Exception as e:
        with output_lock:
            progress_counter["failed"] += 1
            print(f"[ERROR] Stem: {audio_file.name} - {e}")
        return {"status": "error", "input": str(audio_file), "error": str(e)}


def batch_convert(
    source_dir: Path,
    target_root: Path,
    mode: str,
    venv_path: Path,
    script_dir: Path,
    max_workers: int = 1,
    exclude_dirs: list[str] = None,
):
    """批量转换音频文件"""

    # 查找所有音频文件
    exclude_dirs = exclude_dirs or []
    print(f"Scanning audio files in {source_dir}...")
    if exclude_dirs:
        print(f"Excluding directories: {exclude_dirs}")
    audio_files = find_audio_files(source_dir, exclude_dirs)
    total_count = len(audio_files)

    if total_count == 0:
        print("No audio files found!")
        return

    print(f"Found {total_count} audio files")
    print(f"Mode: {mode.upper()}")
    print(f"Output: {target_root}")
    print(f"Max workers: {max_workers}")
    print("-" * 50)

    # 创建任务列表
    tasks = []
    for audio_file in audio_files:
        rel_path = get_relative_path(audio_file, source_dir)
        output_dir = target_root / rel_path.parent
        output_dir.mkdir(parents=True, exist_ok=True)

        if mode == "fast":
            tasks.append((audio_file, output_dir, convert_fast_mode))
        else:  # stem
            tasks.append((audio_file, output_dir, convert_stem_mode))

    # 执行转换
    convert_func = (lambda f, d, fn: fn(f, d, venv_path, script_dir))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(convert_func, audio_file, output_dir, convert_fn): audio_file
            for audio_file, output_dir, convert_fn in tasks
        }

        for future in as_completed(futures):
            audio_file = futures[future]
            try:
                result = future.result()
                # 结果已经在 convert 函数中处理
            except Exception as e:
                with output_lock:
                    progress_counter["failed"] += 1
                    print(f"[ERROR] {audio_file.name}: {e}")

    # 打印总结
    print("\n" + "=" * 50)
    print("BATCH CONVERSION SUMMARY")
    print("=" * 50)
    print(f"Total files:      {progress_counter['total']}")
    print(f"Processed:        {progress_counter['processed']}")
    print(f"Skipped:          {progress_counter['skipped']}")
    print(f"Failed:           {progress_counter['failed']}")
    print(f"Success rate:     {progress_counter['processed'] / progress_counter['total'] * 100:.1f}%")
    print(f"Output directory: {target_root}")
    print("=" * 50)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Batch convert audio to MIDI with AMT models",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Fast mode, single thread
  python batch_convert.py fast --source "E:/music" --target "D:/midi/fast"

  # Stem mode, multi-thread (careful with GPU memory!)
  python batch_convert.py stem --source "E:/music" --target "D:/midi/stem" --workers 1
        """
    )
    parser.add_argument(
        "mode",
        choices=["fast", "stem"],
        help="Conversion mode: fast (direct) or stem (separated transcription)"
    )
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="Source directory containing audio files"
    )
    parser.add_argument(
        "--target",
        type=Path,
        required=True,
        help="Target directory for MIDI output (maintains source structure)"
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=None,
        help="AMT project directory (default: same as this script)"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of parallel workers (default: 1, increase if you have multiple GPUs)"
    )
    parser.add_argument(
        "--exclude",
        type=str,
        nargs="*",
        default=["vgm"],
        help="Directory names to exclude (default: vgm)"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # 确定项目目录
    if args.project_dir:
        script_dir = args.project_dir
    else:
        script_dir = Path(__file__).parent.absolute()

    venv_path = script_dir / ".venv"

    # 验证环境
    if not venv_path.exists():
        print(f"ERROR: Virtual environment not found at {venv_path}")
        print("Please run deployment setup first.")
        sys.exit(1)

    infer_script = script_dir / "infer.py"
    stem_script = script_dir / "stem_infer.py"

    if args.mode == "fast" and not infer_script.exists():
        print(f"ERROR: infer.py not found at {infer_script}")
        sys.exit(1)

    if args.mode == "stem" and not stem_script.exists():
        print(f"ERROR: stem_infer.py not found at {stem_script}")
        sys.exit(1)

    # 验证源目录
    if not args.source.exists():
        print(f"ERROR: Source directory not found: {args.source}")
        sys.exit(1)

    # 执行批量转换
    batch_convert(
        source_dir=args.source,
        target_root=args.target,
        mode=args.mode,
        venv_path=venv_path,
        script_dir=script_dir,
        max_workers=args.workers,
        exclude_dirs=args.exclude,
    )


if __name__ == "__main__":
    main()
