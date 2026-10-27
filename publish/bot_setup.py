"""텔레그램 알림 봇 연결 (한 번만). 토큰 값은 화면에 출력하지 않는다.

1) 텔레그램에서 @BotFather → /newbot → 이름·아이디 정하기 → 받은 토큰을 .env 에 TELEGRAM_BOT_TOKEN=... 로 저장
2) 방금 만든 봇과 대화방을 열고 아무 말이나 한 번 보내기 (예: 안녕)
3) python -m publish.bot_setup
   → 대화방 번호(chat id)를 찾아 .env 에 저장하고, 시험 알림을 보내고, 깃허브 Secrets 에 둘 다 등록
"""
import json
import os
import subprocess
import sys
import urllib.request

from common import ROOT, load_env
from get_token import set_env


def main():
    load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        sys.exit("❌ .env 에 TELEGRAM_BOT_TOKEN 을 먼저 넣어 주세요 (@BotFather 에서 받은 값).")
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20) as r:
        updates = json.load(r).get("result", [])
    chats = [u["message"]["chat"] for u in updates if u.get("message")]
    if not chats:
        sys.exit("❌ 봇에게 온 메시지가 없어요. 텔레그램에서 봇 대화방을 열고 아무 말이나 보낸 뒤 다시 실행해 주세요.")
    chat = chats[-1]
    set_env({"TELEGRAM_CHAT_ID": str(chat["id"])})
    os.environ["TELEGRAM_CHAT_ID"] = str(chat["id"])
    from publish.notify import send
    if not send("✅ 컨텐츠 연구소 알림 봇이 연결됐어요. 발행 완료·보류·오류를 여기로 알려드릴게요."):
        sys.exit("❌ 시험 알림을 보내지 못했어요.")
    print(f"✅ 대화방 연결: {chat.get('first_name') or chat.get('title') or ''} — 시험 알림을 보냈어요")
    for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        subprocess.run(["gh", "secret", "set", name, "--repo", "vhffkfk-max/content-lab"], input=os.environ[name], text=True,
                       check=True, cwd=ROOT, stdout=subprocess.DEVNULL)
        print(f"✅ 깃허브 Secrets 에 {name} 등록")


if __name__ == "__main__":
    main()
