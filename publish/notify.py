"""텔레그램 봇으로 대표에게 알림 (깃허브 실행에서도 동작 — PC 로그인 필요 없음).

    from publish.notify import send
    send("발행 완료: https://instagram.com/p/...")
환경변수(Secrets): TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID  — 설정은 python -m publish.bot_setup
"""
import json
import os
import urllib.error
import urllib.request


def send(text, silent=False):
    """알림 보내기. 봇 설정이 없으면 화면에만 찍고 넘어간다 (발행 자체는 막지 않음)."""
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("[알림 미설정]", text)
        return False
    body = json.dumps({"chat_id": chat, "text": text[:4000], "disable_web_page_preview": True,
                       "disable_notification": silent}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r).get("ok", False)
    except (urllib.error.URLError, TimeoutError) as e:
        print("⚠️ 텔레그램 알림 실패:", e)
        return False
