"""릴스 소리 받아쓰기 (그래픽카드 large-v3). voice-lab 의 sv 가상환경에서 viral_analyze.py 가 부른다.

    python viral_asr.py 음성1.wav 음성2.wav ...   # 각 음성 옆에 같은 이름의 .txt 를 쓴다
"""
import os
import pathlib
import subprocess
import sys

import numpy as np
from faster_whisper import WhisperModel

model = WhisperModel("large-v3", device="cuda", compute_type="int8_float16")
for name in sys.argv[1:]:
    p = pathlib.Path(name)
    try:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-ac", "1", "-ar", "16000", "-f", "f32le", "-"], capture_output=True, check=True).stdout
        segments, _ = model.transcribe(np.frombuffer(raw, dtype=np.float32), condition_on_previous_text=False, vad_filter=True)
        lines = [f"[{s.start:.1f}초] {s.text.strip()}" for s in segments]
        p.with_suffix(".txt").write_text(chr(10).join(lines), encoding="utf-8")
    except Exception as e:
        print("실패", p.name, e, file=sys.stderr)

sys.stdout.flush()
os._exit(0)   # 그래픽카드 정리 중에 멈추는 일이 있어 바로 끝낸다
