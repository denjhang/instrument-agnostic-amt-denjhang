import soundfile as sf
from pathlib import Path
S = Path(r"F:\存储器备份\备份索尼录音笔 2021.4.12\x88 放大300")
files = sorted(S.glob("*.mp3"))
print("count", len(files))
for f in files[:10]:
    info = sf.info(str(f))
    print(f.name, info.samplerate, "ch", info.channels, round(info.duration, 1), "s")
