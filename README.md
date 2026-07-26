# Instrument-Agnostic AMT 个人工作库

基于 [anime-song/instrument-agnostic-amt](https://github.com/anime-song/instrument-agnostic-amt) 的个人工作库，主要用于批量音乐 MIDI 转录。

> 本仓库区别于 amt 官方库，只保留**自己实际使用的版本、批量脚本和工作记录**。模型权重、Python 环境、示例音频等大文件不入库（见 `.gitignore`）。

---

## 目录结构

```
instrument-agnostic-amt-main/
├── oldversion-20260603/        # 旧版代码（6/3 基线 + 6/7 自己改的批量脚本）
├── newversion-20260726/        # 新版官方代码（含鼓声模型 + 力度预测）
├── checkpoints/                # [本地] 所有 .pth 模型权重（共享）
├── .venv/                      # [本地] Python 环境（共享）
├── Coup De Coeur.mp3           # [本地] 示例曲目
└── README.md                   # 本文件
```

两个版本**完全独立、互不污染**，共享根目录的 `checkpoints/` 和 `.venv/`。运行时工作目录设在根目录，两版都能从 `./checkpoints` 找到模型。

---

## 两个版本对比

| | 旧版 `oldversion-20260603` | 新版 `newversion-20260726` |
|---|---|---|
| 代码日期 | 2026-06-03（核心）/ 06-07（infer/stem_infer 改动） | 2026-07-26（官方最新） |
| 架构 | 散落 `.py` 文件 | 打包为 `instrument_agnostic_amt/` 包 |
| 鼓声 | onset detection hack（频段滤波，底鼓军鼓易混） | ✅ 专用 `drums` 模型（6/24 上传） |
| 力度 | 固定 100（1 档） | ✅ 力度预测模型（7/24，103 档 24-126） |
| 分轨模型 | bass/vocal_harmony/guitar/other（4 个） | bass_v2/vocal_harmony/guitar_v1_5/other/drums（6 个） |
| 入口 | `infer.py` / `stem_infer.py` | `infer.py` / `infer_velocity.py` |

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

### 新版 — 官方分轨流程（stem 分离 + 专用模型 + 力度预测）
```bash
# 单文件（复刻 Colab 单元[10]的 run_stem_separated_transcription）
PYTHONPATH=newversion-20260726 \
  .venv/Scripts/python.exe newversion-20260726/run_compare_new.py
```

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
