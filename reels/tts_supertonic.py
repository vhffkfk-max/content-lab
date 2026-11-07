"""Supertonic 음성 묶음 생성. voice-lab 의 st 가상환경에서 engine.py 가 부른다 (모델을 한 번만 띄운다).

    python tts_supertonic.py 일감.json M3     # [{"text": ..., "speed": 1.15, "out": "x.wav"}, ...]
"""
import json
import sys

from supertonic import TTS

voice = sys.argv[2]
tts = TTS(auto_download=True)
style = tts.get_voice_style(voice)
for job in json.load(open(sys.argv[1], encoding="utf-8")):
    wav, _ = tts.synthesize(job["text"], voice_style=style, lang="ko", speed=job["speed"])
    tts.save_audio(wav, job["out"])
