"""받아쓰기 검사 (그래픽카드, large-v3). voice-lab 의 sv 가상환경에서 make_reel.py 가 부른다.

    python rt_gpu.py 음성파일      # 마지막 줄에 받아쓴 글을 찍는다
"""
import subprocess
import sys

import numpy as np
from faster_whisper import WhisperModel

raw = subprocess.run(["ffmpeg", "-v", "error", "-i", sys.argv[1], "-ac", "1", "-ar", "16000", "-f", "f32le", "-"], capture_output=True, check=True).stdout
model = WhisperModel("large-v3", device="cuda", compute_type="int8_float16")
segments, _ = model.transcribe(np.frombuffer(raw, dtype=np.float32), language="ko", condition_on_previous_text=False)
print(" ".join(s.text.strip() for s in segments))
