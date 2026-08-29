# AMT 转换任务总览

> 本文档记录所有批量转换任务，便于持续扩充时查阅。每次新增任务追加到「任务清单」。

---

## 目录约定（规则统一）

| 项目 | 规则 |
|------|------|
| 输出根目录 | `D:\开源合集\开源 2022.9.14\芯片音乐\自制芯片音乐\MIDI识别合集\MIDI识别 2026\` |
| 按日期分目录 | `<日期>/`（如 `20260726/`、`20260727/`）。**新版(20260823)任务统一进 `20260824/`，禁止再新开日期文件夹**（除非用户明确要求） |
| 按来源分目录 | `<日期>/<来源名>/`（如 `20260726/理查德克莱德曼/`） |
| 保留源结构 | 完整保留源文件夹的所有子目录层级，**绝不混杂** |
| 转换流程 | **20260824 起用最新版官方分轨**（stem分离 → 各stem专用模型 → 乐器修正 → 合并 → 力度 → 节拍/和弦） |
| 力度 | 103 档（24-126），带鼓声 |

### 版本切换记录

- **2026-08-24 起产线切换为 `newversion-20260823`**（官方 main b7beee9）。新增能力：Instrument Refinement 乐器修正（refine_instruments）、beat/chord/key 推断（predict_beat_chord）、other_v1_5 模型、Semi-CRF 提速/AMP。此前任务（截至 20260729 目录全部）均为 `newversion-20260726` 产出，不回溯重转。
- **实听结论（2026-08-25，用户评测）**：0824 版对**小提琴、多乐器协奏曲（如竖笛+Harpsichord）、管风琴的识别率有大幅提升**——说明官方是针对某些情况（特定乐器/编制）做的提升，并非全面提升。但**不清晰音频的音符数量不如 7 月版**——以丢失部分音符换取精确度，整体"部分精确、部分丢失"。**7 月版（20260726）依旧有实用性**，不淘汰；对不清晰/嘈杂源（直播、老录音）可考虑用 7 月版补转对比。
- **AI音乐双版本结论（2026-08-28，用户评测）**：AI 生成音乐**优先用 0824 版**；7 月版只适合**单乐器 + 音质模糊**的源（如 x88 内录）。7 月版定位收窄为特定场景工具。
- **CC11 表情分支（haveyouwantto/expression）彻底弃用（2026-08-25 定论）**：纯 DSP 响度包络写 CC11，无专门训练，小提琴实测忽大忽小、力度变化范围过大，"勉强实现的功能"。对比文件在 `20260824/版本对比-雨后轻风有香/` 和 `20260824/音乐卡/网络收集/youtube one/Sonatas & Partitas CC11/`（未跑完即停）。
- 新批量脚本模板改动：worker 里 `sys.path` 指向 `newversion-20260823/instrument-agnostic-amt-main`，`from infer_stem import run_stem_separated_transcription`，调用参数加 `refine_instruments=True, predict_beat_chord=True`，最终产物为 `<曲名>_beat_chord.mid`。

### 来源 → 输出归档规则

- **酷我下载** (`F:\KwDownload\song`) → `20260726/<专辑名>/`（按 7/26 21:00 后筛选）
- **音乐档案** (`F:\存储器备份\2023.1.17 音乐档案\MP3格式`) → 看内容：
  - 游戏音乐 → `20260727/<游戏名>/`
  - 古典/纯音乐（如喜马拉雅-巴赫）→ **和酷我放一起** → `20260726/<目录名>/`

---

## 通用脚本

所有任务基于同一套模板（复制改路径即可）：

| 脚本 | 用途 | 关键配置 |
|------|------|---------|
| `run_kuwo_stem.py` | 酷我下载（按时间筛选） | SOURCE/TARGET/CUTOFF |
| `run_games_stem.py` | 指定多个游戏目录 | SOURCE/TARGET/GAME_DIRS |
| `run_summon_stem.py` | 召唤之夜 5/6 代 | SERIES_SRC/SUBDIRS/TARGET |
| `run_bach_stem.py` | 喜马拉雅-巴赫（古典纯音乐） | SOURCE/TARGET |
| `run_singles_stem.py` | 酷我根目录散落单曲 | SOURCE/TARGET |
| `run_bilibili_stem.py` | 哔哩哔哩视频（mp4，ffmpeg 提音频） | SOURCE/TARGET/CUTOFF |
| `run_cdrip_stem.py` | CD翻录（AMT 重转替代 pianotrans） | SOURCE/TARGET |

### 视频处理（哔哩哔哩专用）

`run_bilibili_stem.py` 针对视频文件（mp4/mkv 等）的特殊处理：
- AMT 不能直接读视频容器（soundfile 不支持），**worker 先用 ffmpeg 提取音频为 wav**，再喂给 AMT
- ffmpeg 来自 `imageio_ffmpeg.get_ffmpeg_exe()`
- 提取的临时 wav 放在 `work_root/_audio_input.wav`，转换完随 work_root 一起清理
- 其余流程（stem 分离、专用模型、力度）和音频任务完全一样

### 共用机制（已踩坑修复）

1. **路径超长防护**：worker 把音频 + out_root 都改成 MD5 短名喂给 stem 分离器（`need_short: song_stem>30 或 est>240`）
2. **磁盘防爆**：每首转完立即删自己的 `_work/<曲名>/`（stem wav 占大头）
3. **断点续跑**：`final.exists() and size>100` 才算完成，中断后重跑自动跳过
4. **双 GPU 并行**：multiprocessing 2 worker，`GPUS=[0,1]`，worker_proc 必须在模块顶层（Windows spawn）

### 手动查进度

```bash
# 各任务 log（实时）
tail -5 D:\working\vscode-projects\instrument-agnostic-amt-main\run_<任务名>.log
# GPU 状态
nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader
# D 盘剩余
.venv\Scripts\python.exe -c "import shutil; print(shutil.disk_usage('D:').free//1024**3,'GB')"
```

### 续转/补转命令

下载完新内容后，重跑对应脚本即可（自动只转缺失的）：
```bash
.venv\Scripts\python.exe run_kuwo_stem.py        # 酷我
.venv\Scripts\python.exe run_games_stem.py       # 游戏
.venv\Scripts\python.exe run_<新任务>.py          # 新任务
```

---

## 任务清单

### ✅ 已完成

| 日期 | 任务 | 数量 | 输出 | 脚本 |
|------|------|------|------|------|
| 2026-07-26 | 理查德克莱德曼（单文件测试） | 16 | `20260726/理查德克莱德曼/` | run_richard.py |
| 2026-07-27 | 游戏音乐（PopKart/QQ堂/QQ幻想/赛尔号/梦幻西游） | 456 | `20260727/<游戏名>/` | run_games_stem.py |
| 2026-07-27 | 召唤之夜 5/6 代 | 62 | `20260727/召唤之夜系列/` | run_summon_stem.py |
| 2026-07-28 | 喜马拉雅-巴赫（古典） | 1084 | `20260726/喜马拉雅-巴赫/` | run_bach_stem.py |
| 2026-07-28 | 酷我+酷狗根目录单曲 | 21 | `20260726/_root_singles/` | run_singles_stem.py |
| 2026-07-27~29 | 哔哩哔哩视频（mp4） | ~2066+ | `20260727/哔哩哔哩视频/<UP主>/` | run_bilibili_stem.py |
| 2026-07-28 | CD翻录（AMT 重转） | 221 | `20260728/CD翻录/` | run_cdrip_stem.py |
| 2026-07-29 | 管风琴（音乐卡） | 59 | `20260729/管风琴/` | run_organ_stem.py |
| 2026-07-29 | 古典多目录（赋格的艺术/网络收集等5目录） | 978/992 | `20260729/<目录名>/` | run_classical_stem.py |
| 2026-07-29~30 | DNF视频/冒险岛/彩虹岛/新游戏/愤怒小鸟 | ~876 | `20260727/<游戏名>/` | 各专用脚本 |
| 2026-08-23~24 | 酷我补转（含全部理查德专辑、Best 100、French Suites 等） | 1005/1007 | `20260726/<专辑>/` | run_kuwo_stem.py |
| 2026-08-24 | 三版本对比实验（雨后轻风有香） | 3 | `20260824/版本对比-雨后轻风有香/` | compare3_*.py |

### 🔄 进行中

（无——20260824 版全部任务已于 2026-08-28 收官，共产出 **8759 首 MIDI**）

| 20260824 版任务 | 成果 |
|------|------|
| 哔哩哔哩视频（含周杰伦两合集/红警3两套OST/怒之铁拳4/AI续写系列） | 2951 |
| 音乐卡 16G 全量（排除 vgm/midi音乐/备份） | 1102 |
| 音乐档案游戏音乐（赛尔号/PopKart/QQ系/梦4/铸剑物語）+ 召唤之夜 | 661 |
| 喜马拉雅（未分类） | 850+ |
| qq音乐+网易云音乐（巴赫名家+游戏作曲家） | 2164/2165 |
| AI音乐合集 0824版 / 0726版（双版本对照） | 260 / 146 |
| x88 放大300 双版本对照 | 262 |
| 版本对比实验 | 3 |

### 2026-08-29 官方更新

- **官方库改名 tsumugi**（原 instrument-agnostic-amt，代码同一项目），最新代码在 `newversion-tsumugi-20260829/tsumugi/`
- **新模型 Vocal Harmony v1.5**（2026-08-25, `best_model_vocal_harmony_v1_5.pth`，已入共享 checkpoints/）：人声 stem COnP 0.6052→0.6814，新代码中已设为 vocals 默认。注意：v1_5 单 Pitch Slot，**不预测声部内同时发声的音符**（合唱和声会少轨）
- 其余模型文件未变（md5 同 8/23）
- **切换时机**：等当前在跑任务（酷我等）结束后，新版批量脚本 sys.path 改指 tsumugi 目录再启用；对合唱/和声内容多的源，v1.5 与旧 vocal_harmony 可对比选用

### 经验教训（20260824 工程期间）

1. **特殊编码 mp3**（qq音乐下载的 mqms 系）：表头可读但解码中途崩，soundfile/audioread 全挂。解法：ffmpeg 预转标准 wav 再进管线（run_qq_seq_retry.py）
2. **audioread 无后端**：系统 PATH 无 ffmpeg，需在 worker 里把 audioread.ffdec.COMMANDS 指向 imageio_ffmpeg 绝对路径
3. **8 worker 并行内存挤爆**：CUDA bad allocation + numpy OOM 连环失败，4-6 worker 为安全上限；失败补跑用断点续跑自愈
4. **多任务断点续跑+失败清理+即清机制**经受住多次盘满/进程被杀考验

### ⏳ 待启动

（暂无）

---

## 注意事项

1. **用户持续下载**：酷我下载是滚动进行的，每次重跑 `run_kuwo_stem.py` 会把新下载的补上
2. **路径超长**：古典音乐文件名常含全角符号（`：` `？`）+ 长英文标题，必须用短名机制
3. **磁盘监控**：D 盘曾因 stem wav 堆积爆满（126GB），现已修复（每首即清），但仍需留意
4. **GPU 共享**：可与其他任务（如 LMStudio）共存，显存够即可
