# Instrument-Agnostic AMT 个人工作库

基于 [anime-song/instrument-agnostic-amt](https://github.com/anime-song/instrument-agnostic-amt) 的个人工作库，主要用于批量音乐 MIDI 转录。

> 本仓库区别于 amt 官方库，只保留**自己实际使用的版本、批量脚本和工作记录**。模型权重、Python 环境、示例音频等大文件不入库（见 `.gitignore`）。

---

## 目录结构

```
instrument-agnostic-amt-main/
├── oldversion-20260603/        # 旧版代码（6/3 基线 + 6/7 自己改的批量脚本）
├── newversion-20260726/        # 新版官方代码（含鼓声模型 + 力度预测）— 20260824 前的产线
├── newversion-20260823/        # 最新官方代码（main b7beee9）— 现役产线
├── expression-20260823/        # CC11 表情分支 fork — 已试过弃用
├── checkpoints/                # [本地] 所有 .pth 模型权重（共享，13 个）
├── .venv/                      # [本地] Python 环境（共享）
├── Coup De Coeur.mp3           # [本地] 示例曲目
└── README.md                   # 本文件
```

各版本**完全独立、互不污染**，共享根目录的 `checkpoints/` 和 `.venv/`。运行时工作目录设在根目录，各版都能从 `./checkpoints` 找到模型。

---

## 版本演进

| | 旧版 `oldversion-20260603` | `newversion-20260726` | `newversion-20260823`（现役） |
|---|---|---|---|
| 代码日期 | 2026-06-03/07 | 2026-07-26 | 2026-08-23（main b7beee9） |
| 架构 | 散落 `.py` 文件 | `instrument_agnostic_amt/` 包 | 同左 + Triton/Semi-CRF 提速、AMP |
| 鼓声 | onset hack | ✅ drums 专用模型 | ✅ 同左 |
| 力度 | 固定 100 | ✅ 103 档（7/24 模型） | ✅ 同左（权重未变） |
| 乐器修正 | ✗ | ✗ | ✅ Instrument Refinement（8/8 模型） |
| 节拍/和弦/调性 | ✗ | ✗ | ✅ best_beat_chord_key.pth（7/30） |
| other stem 模型 | other | other | other_v1_5（8/19） |

**2026-08-24 起所有新任务用 `newversion-20260823`**（`from infer_stem import run_stem_separated_transcription`，加 `refine_instruments=True, predict_beat_chord=True`，产物 `<曲名>_beat_chord.mid`）。旧任务产物不回溯。

**CC11 表情分支**（`expression-20260823/`，fork of main）：纯 DSP 响度包络写 CC11，无专门训练，不区分乐器包络特性。小提琴实测忽大忽小、力度跳变过大，**彻底弃用**（2026-08-25 定论）。

**0824 版 vs 7 月版实听结论**：0824 对**小提琴、多乐器协奏曲（竖笛+Harpsichord 等）、管风琴识别率大幅提升**——属针对性提升而非全面；但不清晰音频（直播、嘈杂源）的**音符召回不如 7 月版**，以丢音符换精确度。**7 月版依旧有实用性，不淘汰**，两版并存：清晰源用 0824，不清晰源可加转 7 月版对比。

---

## 官方模型更新时间线（hf-mirror.com 实测）

| 日期 | 内容 |
|------|------|
| 2026-05-03 | 初始上传 `best_model.pth` |
| 2026-05-16~20 | bass / vocal / guitar 模型 |
| 2026-05-31 | vocal_harmony 模型 |
| 2026-06-05 | other 模型 |
| **2026-06-24** | 🥁 `best_model_drums.pth` 鼓声专用模型 |
| 2026-07-15~16 | `best_model_bass_v2.pth` |
| 2026-07-22 | `best_model_guitar_v1_5.pth` |
| **2026-07-23~24** | 🎚️ `best_velocity_model.pth` 力度预测模型 |
| **2026-07-30** | 🎼 `best_beat_chord_key.pth` 节拍/和弦/调性模型 |
| **2026-08-08** | 🎻 `best_instrument_refinement.pth` 乐器修正模型 |
| **2026-08-19** | `best_model_other_v1_5.pth` other stem 升级 |

（8/21~23 另有大量纯性能优化提交：Semi-CRF Viterbi 提速、Triton 后端、AMP 默认开、stem-splitter 0.0.7、uv+PyTorch 2.13 迁移；原有 10 个权重 md5 未变。）

---

## 关键认知（避坑）

### 1. 快速模式天然无鼓声（非 bug）
- `default` 模型（`best_model.pth`）缺 `interval_instrument_predictor` 权重 → 识别不出鼓
- `drums` 模型直接跑整曲只输出零星几个音符（设计使然，它只处理纯鼓声 stem）
- **鼓声只在分轨模式下有**（先分离 drums.wav，再用 drums 模型转录）

### 2. 力度只在分轨模式下有
力度模型是**二段式后处理**：先 AMT 出音符 → 力度模型用 stem 音频预测每个音符的 velocity（1-127）。快速模式用不了。

### 3. 力度模型完全开源
新版 `instrument_agnostic_amt/velocity/` 包含完整代码（modeling/cli/training/synthesis），入口 `infer_velocity.py`，核心函数 `predict_velocity_for_stem_midis()`。

---

## 使用方式

### 运行环境
工作目录统一设在**项目根目录**，让两版都能找到 `./checkpoints`。

### 旧版 — 快速模式批量转换（已完成多个批次）
```bash
# 单专辑分轨
.venv/Scripts/python.exe oldversion-20260603/stem_infer.py \
  --audio "音频.mp3" --output-root "输出目录" --cleanup-stems

# 批量快速模式（如酷我下载）
.venv/Scripts/python.exe oldversion-20260603/run_kuwo_fast.py
```

### 最新版（现役）— 官方分轨流程 + 乐器修正 + 节拍/和弦
```bash
PYTHONPATH=newversion-20260823/instrument-agnostic-amt-main \
  .venv/Scripts/python.exe newversion-20260823/instrument-agnostic-amt-main/infer_stem.py \
  --audio "音频.mp3" --output-root "输出目录" --refine-instruments --predict-beat-chord --cleanup-stems
```

### 旧版 — 20260726 官方分轨流程（历史任务用）

新版快速模式：
```bash
PYTHONPATH=newversion-20260726 \
  .venv/Scripts/python.exe newversion-20260726/infer.py --audio "音频.mp3"
```

---

## 依赖（不在本仓库，需本地准备）

| 资源 | 位置 | 说明 |
|------|------|------|
| `.venv/` | 项目根目录 | Python 环境，两版共享 |
| `checkpoints/*.pth` | 项目根目录 | 所有 AMT + 力度模型权重 |
| `stem_splitter.pt` | `~/.cache/stem_splitter/weights/` | stem 分离权重（350MB），由 `stem-splitter` 包自动下载 |
| HF 镜像 | `HF_ENDPOINT=https://hf-mirror.com` | 中国大陆下载模型必须用镜像 |

`stem-splitter` 是独立 PyPI 包：`pip install stem-splitter`

---

## 工作记录

详见 [`oldversion-20260603/分轨模式转换进度.md`](oldversion-20260603/分轨模式转换进度.md)，包含：
- 已完成的批量转换批次（音乐卡 1132 个、酷我 924 个等）
- 已修复的 11 个 Bug（路径长度、编码、并发竞争等）
- 鼓声检测的 v1/v2 调参记录
- 模型输出能力清单（支持/不支持）

---

## 致谢

- 官方仓库：[anime-song/instrument-agnostic-amt](https://github.com/anime-song/instrument-agnostic-amt)
- 模型权重：[anime-song/instrument_agnostic_amt](https://huggingface.co/anime-song/instrument_agnostic_amt)（HuggingFace）
- 架构基础：[Transkun](https://github.com/Yujia-Yan/Transkun)（Neural Semi-CRF）
