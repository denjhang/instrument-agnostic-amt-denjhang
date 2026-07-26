"""新版官方分轨流程对比脚本

完全复刻 Colab_Inference.ipynb 单元[10]的 run_stem_separated_transcription()。
关键: 工作目录设为项目根目录（那里有 checkpoints/），同时把新版目录加入 sys.path。
"""

import os
import sys
from pathlib import Path

NEW_DIR = Path(r"D:\working\vscode-projects\instrument-agnostic-amt-main\newversion-20260726")
ROOT = NEW_DIR.parent

# 1. 把新版目录加入 sys.path，让 `import infer` / `import instrument_agnostic_amt` 生效
sys.path.insert(0, str(NEW_DIR))
# 2. 工作目录设为根目录，让新版找到 ./checkpoints
os.chdir(ROOT)

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
# 用 hf-mirror 镜像，万一需要下载也不至于连不上
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

import importlib.util
spec = importlib.util.spec_from_file_location("nb_helpers", str(NEW_DIR / "_nb_helpers.py"))
nb_helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nb_helpers)

AUDIO = ROOT / "Coup De Coeur.mp3"
OUTPUT_ROOT = ROOT / "compare_new_stem"

if __name__ == "__main__":
    print("=" * 60)
    print("新版官方分轨流程（stem分离 + 专用模型 + 力度预测）")
    print(f"工作目录: {os.getcwd()}")
    print(f"音频: {AUDIO}")
    print(f"输出: {OUTPUT_ROOT}")
    print("=" * 60)
    result = nb_helpers.run_stem_separated_transcription(
        AUDIO,
        checkpoint_path=None,
        output_root=str(OUTPUT_ROOT),
        window_batch_size=4,
        max_midi_melodic_instruments=15,
        transcribe_drum_stems=True,
        predict_velocity=True,
        cleanup_separated_stems=False,
        merge_onset_ms=50.0,
    )
    print("=" * 60)
    print("完成:")
    for k, v in result.items():
        print(f"  {k}: {v}")
