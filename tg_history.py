"""텔레그램 방의 과거 글(기본 1년)을 모아 data/telegram_history.db 에 쌓는다 (내 PC에서, 전략 분석용).

    python tg_history.py                 # telegram_chats.csv 에 표시한 방, 최근 365일
    python tg_history.py --days 365 --only 내방
이미 모은 글은 건너뛰고 이어서 모은다 (중간에 멈춰도 다시 실행하면 이어짐).
원문이 들어 있어서 저장소에 올리지 않는다.
"""
import argparse
import csv
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from common import DATA_DIR
from tg_collect import media_of
from tg_login import CHATS, client

DB = DATA_DIR / "telegram_history.db"
SCHEMA = """
CREATE TABLE IF NOT EXISTS msgs (
    chat_id TEXT, id INTEGER, date TEXT, text TEXT, views INTEGER, forwards INTEGER, replies INTEGER,
    reactions INTEGER, media TEXT, has_link INTEGER, is_forward INTEGER, grouped_id TEXT, sender_id TEXT,
    PRIMARY KEY (chat_id, id)
);
CREATE TABLE IF NOT EXISTS chats (id TEXT PRIMARY KEY, title TEXT, username TEXT, kind TEXT, members INTEGER, role TEXT);
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--only", help="'내방' 이면 내 채널만")
    ap.add_argument("--groups", action="store_true", help="그룹도 모음 (오래 걸림)")
    args = ap.parse_args()
    with open(CHATS, encoding="utf-8-sig", newline="") as f:
        chats = [r for r in csv.DictReader(f) if (r["분석"] or "").strip()]
    if args.only:
        chats = [c for c in chats if args.only in c["분석"]]
    if not args.groups:  # 그룹은 잡담이 많고 조회수가 없어 전략 분석에 안 씀 (1년이면 수십만 개)
        chats = [c for c in chats if c["종류"] == "채널"]
    # 내 채널 먼저
    chats.sort(key=lambda c: "내" not in c["분석"])
    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    conn = sqlite3.connect(DB)
    conn.executescript(SCHEMA)
    with client() as c:
        for ch in chats:
            role = "mine" if "내" in ch["분석"] else "other"
            conn.execute("INSERT OR REPLACE INTO chats VALUES (?,?,?,?,?,?)",
                         (ch["id"], ch["이름"], ch["아이디"], ch["종류"], int(ch["인원"] or 0), role))
            oldest = conn.execute("SELECT MIN(id), MIN(date) FROM msgs WHERE chat_id=?", (ch["id"],)).fetchone()
            done_back = oldest[1] and oldest[1] <= since.isoformat()
            newest = conn.execute("SELECT MAX(id) FROM msgs WHERE chat_id=?", (ch["id"],)).fetchone()[0] or 0
            t0, n = time.time(), 0
            try:
                # 1) 새 글(마지막으로 모은 뒤) 2) 아직 덜 모은 과거 글
                passes = [dict(min_id=newest)] if newest else []
                if not done_back:
                    passes.append(dict(offset_id=oldest[0] or 0))
                for kw in passes:
                    for m in c.iter_messages(int(ch["id"]), wait_time=1, **kw):
                        if m.date < since:
                            break
                        if m.action:
                            continue
                        reactions = sum(r.count for r in m.reactions.results) if m.reactions else 0
                        conn.execute("INSERT OR REPLACE INTO msgs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                     (ch["id"], m.id, m.date.isoformat(), (m.message or "")[:2000], m.views, m.forwards,
                                      m.replies.replies if m.replies else 0, reactions, media_of(m),
                                      int("http" in (m.message or "")), int(m.fwd_from is not None),
                                      str(m.grouped_id or ""), str(m.sender_id or "")))
                        n += 1
                        if n % 500 == 0:
                            conn.commit()
                            print(f"   … {ch['이름']}: {n}개 ({m.date.astimezone().strftime('%Y-%m-%d')}까지)", flush=True)
            except Exception as e:
                print(f"⚠️ {ch['이름']}: {e}", flush=True)
            conn.commit()
            total = conn.execute("SELECT COUNT(*) FROM msgs WHERE chat_id=?", (ch["id"],)).fetchone()[0]
            print(f"✅ {ch['이름']}: 이번에 {n}개, 모두 {total}개 ({time.time() - t0:.0f}초)", flush=True)
    print(f"완료 → {DB}")


if __name__ == "__main__":
    main()
