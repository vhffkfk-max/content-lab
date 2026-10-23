"""텔레그램 로그인 + 내가 들어가 있는 채널·그룹 목록을 telegram_chats.csv 로 만든다 (내 PC에서 한 번).

    python tg_login.py
처음 실행하면 전화번호(+8210…) → 텔레그램 앱으로 온 코드 → (설정했다면) 2단계 비밀번호를 물어본다.
로그인 정보는 data/telegram.session 에만 저장되고 저장소에 올라가지 않는다.
.env 에 TG_API_ID, TG_API_HASH 필요 (https://my.telegram.org → API development tools).

telegram_chats.csv 의 '분석' 칸에 o(다른 업체 방) 또는 내방(내 채널)을 적으면 그 방만 수집한다.
다시 실행해도 이미 적어 둔 표시는 유지된다.
"""
import csv
import os
import sys

from common import DATA_DIR, ROOT, load_env

CHATS = ROOT / "telegram_chats.csv"
FIELDS = ["분석", "id", "이름", "아이디", "종류", "인원"]


def client():
    from telethon.sync import TelegramClient
    load_env()
    api_id, api_hash = os.environ.get("TG_API_ID"), os.environ.get("TG_API_HASH")
    if not api_id or not api_hash:
        sys.exit(".env 에 TG_API_ID, TG_API_HASH 를 먼저 넣어 주세요 (TELEGRAM_SETUP.md 참고).")
    DATA_DIR.mkdir(exist_ok=True)
    return TelegramClient(str(DATA_DIR / "telegram"), int(api_id), api_hash)


def main():
    marks = {}
    if CHATS.exists():
        with open(CHATS, encoding="utf-8-sig", newline="") as f:
            marks = {r["id"]: r["분석"] for r in csv.DictReader(f)}
    rows = []
    with client() as c:
        me = c.get_me()
        print(f"✅ 로그인: {me.first_name or ''} (@{me.username or '-'})")
        for d in c.iter_dialogs():
            if not (d.is_channel or d.is_group):
                continue
            e = d.entity
            kind = "채널" if getattr(e, "broadcast", False) else "그룹"
            rows.append({"분석": marks.get(str(d.id), ""), "id": d.id, "이름": d.name, "아이디": getattr(e, "username", "") or "",
                         "종류": kind, "인원": getattr(e, "participants_count", "") or ""})
    with open(CHATS, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    picked = sum(1 for r in rows if r["분석"])
    print(f"✅ 채널·그룹 {len(rows)}개 → {CHATS.name} (분석 표시 {picked}개)")
    print("   분석할 방의 '분석' 칸에 o, 내 채널은 내방 이라고 적어 주세요.")


if __name__ == "__main__":
    main()
