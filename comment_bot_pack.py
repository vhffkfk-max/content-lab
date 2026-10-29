"""댓글 기회 봇을 USB로 옮길 폴더로 묶는다 (기본: 바탕화면\\댓글봇_USB).

    python comment_bot_pack.py            # 바탕화면에 만들기
    python comment_bot_pack.py --to E:\\   # USB에 바로 만들기

.env 는 봇에 필요한 키만 골라 담는다 (인스타·캔바·Apify 키는 빼서 USB를 잃어버려도 덜 위험하게).
값은 화면에 찍지 않는다.
"""
import argparse
import shutil
import sys
from pathlib import Path

from common import ENV_PATH, ROOT

FILES = ["comment_bot.py", "post_reader.py", "common.py", "get_token.py", "publish/__init__.py",
         "publish/render.py", "config/comment_accounts.json", "comment_bot_install.ps1", "COMMENT_BOT.md"]
KEYS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "ANTHROPIC_API_KEY")
NAME = "댓글봇_USB"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", default=str(Path.home() / "Desktop"))
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    out = Path(a.to) / NAME
    out.mkdir(parents=True, exist_ok=True)
    for f in FILES:
        (out / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / f, out / f)
    # 배치 파일은 CRLF 여야 cmd 가 줄을 제대로 읽는다
    bat = (ROOT / "comment_bot_setup.bat").read_text(encoding="utf-8").replace("\r\n", "\n").replace("\n", "\r\n")
    (out / "댓글봇 설치.bat").write_bytes(bat.encode("utf-8"))
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    keep = [l for l in lines if l.split("=", 1)[0].strip() in KEYS]
    (out / ".env").write_text("\n".join(keep) + "\n", encoding="utf-8")
    found = sorted({l.split("=", 1)[0].strip() for l in keep})
    print(f"만들었어요: {out}")
    print("담은 키:", ", ".join(found) or "없음")
    if "ANTHROPIC_API_KEY" not in found:
        print("Anthropic 키는 없어요 → 여분 PC에서 설치할 때 한 번 물어봐요.")


if __name__ == "__main__":
    main()
