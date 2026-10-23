"""telegram_chats.csv 에 표시한 방의 최근 글을 모아 data/telegram.json 으로 저장한다 (내 PC에서 매일).

    python tg_collect.py            # 최근 14일, 방마다 최대 400개
    python tg_collect.py --days 30
채널은 조회수·전달 수·반응 수, 그룹은 반응·답글 수를 함께 모은다.
data/telegram.json 은 저장소에 올라가서 서버(telegram.yml)가 Claude 분석 후 사이트에 싣는다.
"""
import argparse
import csv
import json
from datetime import datetime, timedelta, timezone

from common import DATA_DIR
from tg_login import CHATS, client

OUT = DATA_DIR / "telegram.json"
MIN_GROUP_CHARS = 30   # 그룹은 잡담이 많아서 짧은 말은 뺀다


def media_of(m):
    if m.photo:
        return "사진"
    if m.video or m.gif:
        return "영상"
    if m.document:
        return "파일"
    if m.web_preview:
        return "링크"
    return "글"


def link_of(chat, mid):
    if chat["아이디"]:
        return f"https://t.me/{chat['아이디']}/{mid}"
    cid = str(chat["id"]).removeprefix("-100")
    return f"https://t.me/c/{cid}/{mid}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--limit", type=int, default=400)
    args = ap.parse_args()
    if not CHATS.exists():
        raise SystemExit("telegram_chats.csv 가 없어요. python tg_login.py 를 먼저 실행해 주세요.")
    with open(CHATS, encoding="utf-8-sig", newline="") as f:
        chats = [r for r in csv.DictReader(f) if (r["분석"] or "").strip()]
    if not chats:
        raise SystemExit("telegram_chats.csv 의 '분석' 칸에 o 또는 내방 을 적은 방이 없어요.")
    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    out_chats, msgs = [], []
    with client() as c:
        for ch in chats:
            role = "mine" if "내" in ch["분석"] else "other"
            n = 0
            try:
                for m in c.iter_messages(int(ch["id"]), limit=args.limit):
                    if m.date < since:
                        break
                    text = m.message or ""
                    if ch["종류"] == "그룹" and len(text) < MIN_GROUP_CHARS:
                        continue
                    if not text and not m.media:
                        continue
                    reactions = sum(r.count for r in m.reactions.results) if m.reactions else 0
                    msgs.append({"chat_id": ch["id"], "id": m.id, "date": m.date.isoformat(), "text": text[:2000],
                                 "views": m.views, "forwards": m.forwards, "replies": m.replies.replies if m.replies else 0,
                                 "reactions": reactions, "media": media_of(m), "link": link_of(ch, m.id)})
                    n += 1
            except Exception as e:  # 나간 방·권한 없는 방은 건너뛴다
                print(f"⚠️ {ch['이름']}: {e}")
                continue
            out_chats.append({"id": ch["id"], "title": ch["이름"], "username": ch["아이디"], "kind": ch["종류"],
                              "members": ch["인원"], "role": role})
            print(f"✅ {ch['이름']}: {n}개")
    OUT.write_text(json.dumps({"collected": datetime.now(timezone.utc).isoformat(timespec="seconds"), "days": args.days,
                               "chats": out_chats, "messages": msgs}, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"완료: 방 {len(out_chats)}개, 글 {len(msgs)}개 → {OUT}")


if __name__ == "__main__":
    main()
