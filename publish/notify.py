"""텔레그램 봇으로 대표에게 알림 (깃허브 실행에서도 동작 — PC 로그인 필요 없음).

    from publish.notify import send
    send("발행 완료: https://instagram.com/p/...")
환경변수(Secrets): TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID  — 설정은 python -m publish.bot_setup
"""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

SENT = Path.home() / ".content-lab-ai" / "tg_sent.json"   # 보낸 파일 장부 (publish.tg_watch 가 같은 것을 두 번 안 보내게)


def key(path):
    """파일 내용 지문: 크기 + 앞뒤 1MB. 이름이 달라도 같은 영상이면 같다."""
    import hashlib
    p = Path(path)
    size = p.stat().st_size
    h = hashlib.sha1()
    with open(p, "rb") as f:
        h.update(f.read(1 << 20))
        if size > 2 << 20:
            f.seek(-(1 << 20), 2)
            h.update(f.read())
    return f"{size}:{h.hexdigest()[:16]}"


def load_sent():
    try:
        return set(json.loads(SENT.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def mark(paths):
    """보낸 파일을 장부에 적는다 (실패해도 전송은 그대로)."""
    try:
        sent = load_sent() | {key(p) for p in paths}
        SENT.parent.mkdir(parents=True, exist_ok=True)
        SENT.write_text(json.dumps(sorted(sent)[-5000:]), encoding="utf-8")
    except OSError as e:
        print("⚠️ 보낸 장부 기록 실패:", e)


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


def send_video(path, caption=""):
    """영상 파일 보내기 (봇 한도 50MB). 영상은 공개 저장소에 올리지 않고 이 길로 보낸다."""
    import requests
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("[알림 미설정] 영상:", caption)
        return False
    try:
        with open(path, "rb") as f:
            r = requests.post(f"https://api.telegram.org/bot{token}/sendVideo", data={"chat_id": chat, "caption": caption[:1000], "supports_streaming": "true"},
                              files={"video": f}, timeout=180)
        ok = r.json().get("ok", False)
        ok and mark([path])
        return ok
    except requests.RequestException as e:
        print("⚠️ 텔레그램 영상 전송 실패:", e)
        return False


def send_photos(paths, caption=""):
    """이미지 앨범(최대 10장) 보내기 — 카드뉴스 초안 확인용. 첫 장에 설명이 붙는다."""
    import requests
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("[알림 미설정] 이미지", len(paths), "장:", caption)
        return False
    paths = list(paths)[:10]
    media = [{"type": "photo", "media": f"attach://p{i}", **({"caption": caption[:1000]} if i == 0 else {})} for i in range(len(paths))]
    files = {f"p{i}": open(p, "rb") for i, p in enumerate(paths)}
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMediaGroup",
                          data={"chat_id": chat, "media": json.dumps(media)}, files=files, timeout=60)
        ok = r.json().get("ok", False)
        ok and mark(paths)
        return ok
    except requests.RequestException as e:
        print("⚠️ 텔레그램 이미지 보내기 실패:", e)
        return False
    finally:
        for f in files.values():
            f.close()
