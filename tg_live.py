"""텔레그램 방 실시간 수집 + 반응 큰 글 알림 (내 PC에서 계속 켜 두는 프로그램).

    python tg_live.py --login     # 처음 한 번: 이 프로그램 전용 로그인 (코드 입력)
    python tg_live.py             # 계속 실행 (작업 스케줄러가 PC 로그온 때 자동 시작)
    python tg_live.py --once --no-push --session telegram --dry-alert   # 시험: 한 바퀴만, 올리기·알림 보내기 없이

하는 일:
  - telegram_chats.csv 에 표시한 방의 새 글을 올라오는 즉시 저장 (data/telegram_live.db, 저장소에 안 올라감)
  - 10분마다 최근 글의 조회수·반응을 새로 읽고, 평소의 3배 이상 반응이 나온 24시간 안 글을 내 텔레그램 '저장된 메시지'로 알림
  - 30분마다 사이트용 통계(output/site/tg_*.json)를 만들어 저장소에 올림 → 서버가 사이트 다시 배포
Claude 를 부르지 않아 토큰 비용이 없다 (오늘의 문구는 서버가 하루 한 번만 씀).
"""
import argparse
import asyncio
import csv
import logging
import os
import sqlite3
import statistics
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from common import DATA_DIR, OUTPUT_DIR, ROOT, load_env
from tg_collect import MIN_GROUP_CHARS, link_of, media_of
from tg_login import CHATS
import tg_analyze

DB = DATA_DIR / "telegram_live.db"
LOG = DATA_DIR / "tg_live.log"
SITE = OUTPUT_DIR / "site"
KEEP_DAYS = 7
REFRESH_MIN, PUSH_MIN = 10, 30
ALERT_X, ALERT_HOURS, ALERT_MAX = 3.0, 24, 10
SITE_FILES = ["tg_meta", "tg_chats", "tg_hot", "tg_mine", "tg_hours", "tg_lengths", "tg_media"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS msgs (
    chat_id TEXT, id INTEGER, date TEXT, text TEXT, views INTEGER, forwards INTEGER, replies INTEGER,
    reactions INTEGER, media TEXT, link TEXT, PRIMARY KEY (chat_id, id)
);
CREATE TABLE IF NOT EXISTS alerted (chat_id TEXT, id INTEGER, PRIMARY KEY (chat_id, id));
"""
log = logging.getLogger("tg_live")


def load_chats():
    with open(CHATS, encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f) if (r["분석"] or "").strip()]


def save(conn, ch, m):
    text = m.message or ""
    if ch["종류"] == "그룹" and len(text) < MIN_GROUP_CHARS:
        return
    if not text and not m.media:
        return
    reactions = sum(r.count for r in m.reactions.results) if m.reactions else 0
    conn.execute(
        "INSERT INTO msgs VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(chat_id, id) DO UPDATE SET text=excluded.text, "
        "views=excluded.views, forwards=excluded.forwards, replies=excluded.replies, reactions=excluded.reactions",
        (ch["id"], m.id, m.date.isoformat(), text[:1000], m.views, m.forwards, m.replies.replies if m.replies else 0,
         reactions, media_of(m), link_of(ch, m.id)))


async def refresh(client, conn, chats, limit):
    since = datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)
    for ch in chats:
        try:
            async for m in client.iter_messages(int(ch["id"]), limit=limit):
                if m.date < since:
                    break
                save(conn, ch, m)
        except Exception as e:  # 나간 방·권한 없는 방은 건너뛴다
            log.warning("%s: %s", ch["이름"], e)
    conn.execute("DELETE FROM msgs WHERE date < ?", (since.isoformat(),))
    conn.commit()


def snapshot(conn, chats):
    """tg_collect 와 같은 모양의 데이터 → tg_analyze.build 로 사이트 통계."""
    cols = ["chat_id", "id", "date", "text", "views", "forwards", "replies", "reactions", "media", "link"]
    msgs = [dict(zip(cols, r)) for r in conn.execute(f"SELECT {', '.join(cols)} FROM msgs")]
    return {"collected": datetime.now(timezone.utc).isoformat(timespec="seconds"), "days": KEEP_DAYS,
            "chats": [{"id": c["id"], "title": c["이름"], "username": c["아이디"], "kind": c["종류"], "members": c["인원"],
                       "role": "mine" if "내" in c["분석"] else "other"} for c in chats],
            "messages": msgs}


def write_site(conn, chats):
    import json
    out = tg_analyze.build(snapshot(conn, chats), datetime.now(timezone.utc))
    SITE.mkdir(parents=True, exist_ok=True)
    for name in SITE_FILES:
        (SITE / f"{name}.json").write_text(json.dumps(out[name], ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def alert_candidates(conn, chats, since_min=None):
    """다른 방 글 중 24시간 안에 올라와 그 방 평소(중앙값)의 3배 이상 반응인 글."""
    now = datetime.now(timezone.utc)
    found = []
    for ch in chats:
        if "내" in ch["분석"]:
            continue
        rows = conn.execute("SELECT id, date, text, views, reactions, replies, link FROM msgs WHERE chat_id=?", (ch["id"],)).fetchall()
        scores = [tg_analyze.score({"views": r[3], "reactions": r[4], "replies": r[5]}, ch["종류"]) for r in rows]
        if len(scores) < 5:
            continue
        base = max(statistics.median(scores), 5)
        for r, s in zip(rows, scores):
            dt = datetime.fromisoformat(r[1])
            if now - dt > timedelta(hours=ALERT_HOURS) or (since_min and dt < since_min):
                continue
            x = s / base
            if x >= ALERT_X and not conn.execute("SELECT 1 FROM alerted WHERE chat_id=? AND id=?", (ch["id"], r[0])).fetchone():
                found.append({"chat": ch, "id": r[0], "x": x, "text": r[2] or "", "views": r[3], "reactions": r[4],
                              "replies": r[5], "link": r[6]})
    return sorted(found, key=lambda a: -a["x"])


def alert_text(a):
    ch = a["chat"]
    nums = (f"조회 {a['views'] or 0:,} · 반응 {a['reactions']:,}" if ch["종류"] == "채널"
            else f"반응 {a['reactions']:,} · 답글 {a['replies']:,}")
    body = a["text"].strip()
    body = body[:300] + ("…" if len(body) > 300 else "")
    return f"🔥 [{ch['이름']}] 평소의 {a['x']:.1f}배\n{nums}\n\n{body}\n\n{a['link']}"


async def send_alerts(client, conn, chats, dry, since_min=None):
    sent = 0
    for a in alert_candidates(conn, chats, since_min)[:ALERT_MAX]:
        if dry:
            log.info("알림(시험) %s", alert_text(a).replace("\n", " / ")[:200])
        else:
            try:
                await client.send_message("me", alert_text(a), link_preview=False)
            except Exception as e:
                log.warning("알림 실패: %s", e)
                continue
        conn.execute("INSERT OR IGNORE INTO alerted VALUES (?, ?)", (a["chat"]["id"], a["id"]))
        sent += 1
    conn.commit()
    if sent:
        log.info("알림 %d개", sent)


def git(*args):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    return r.returncode, (r.stdout + r.stderr).strip()


def push():
    git("pull", "--rebase", "--autostash")
    git("add", *[f"output/site/{n}.json" for n in SITE_FILES])
    code, _ = git("commit", "-m", f"data: 텔레그램 {datetime.now(tg_analyze.KST).strftime('%m/%d %H:%M')}")
    if code != 0:
        return  # 바뀐 게 없음
    code, out = git("push")
    log.info("사이트 올리기 %s", "완료" if code == 0 else f"실패: {out[-200:]}")


async def run(args):
    from telethon import TelegramClient, events
    load_env()
    api_id, api_hash = os.environ.get("TG_API_ID"), os.environ.get("TG_API_HASH")
    if not api_id or not api_hash:
        sys.exit(".env 에 TG_API_ID, TG_API_HASH 가 없어요.")
    client = TelegramClient(str(DATA_DIR / args.session), int(api_id), api_hash)
    if args.login:
        await client.start()
        me = await client.get_me()
        print(f"✅ 실시간 수집용 로그인 완료: {me.first_name or ''}")
        await client.disconnect()
        return
    await client.connect()
    if not await client.is_user_authorized():
        log.error("로그인이 안 되어 있어요. python tg_live.py --login 을 먼저 실행해 주세요.")
        return
    chats = load_chats()
    by_id = {int(c["id"]): c for c in chats}
    await client.get_dialogs()  # 방 정보 캐시 (이벤트에서 방을 알아보려면 필요)
    conn = sqlite3.connect(DB)
    conn.executescript(SCHEMA)
    first = conn.execute("SELECT COUNT(*) FROM msgs").fetchone()[0] == 0
    await refresh(client, conn, chats, 300 if first else 80)
    started = datetime.now(timezone.utc)
    if first:  # 처음 켤 때는 지난 글로 알림이 쏟아지지 않게, 최근 1시간 글만 알리고 나머지는 알린 것으로 표시
        await send_alerts(client, conn, chats, args.dry_alert, since_min=started - timedelta(hours=1))
        for a in alert_candidates(conn, chats):
            conn.execute("INSERT OR IGNORE INTO alerted VALUES (?, ?)", (a["chat"]["id"], a["id"]))
        conn.commit()
    else:
        await send_alerts(client, conn, chats, args.dry_alert)
    write_site(conn, chats)
    if not args.no_push:
        push()
    log.info("시작: 방 %d개, 글 %d개", len(chats), conn.execute("SELECT COUNT(*) FROM msgs").fetchone()[0])
    if args.once:
        await client.disconnect()
        return

    @client.on(events.NewMessage(chats=list(by_id)))
    async def on_new(event):
        ch = by_id.get(event.chat_id)
        if ch:
            save(conn, ch, event.message)
            conn.commit()

    async def loop():
        last_push = datetime.now(timezone.utc)
        while True:
            await asyncio.sleep(REFRESH_MIN * 60)
            try:
                await refresh(client, conn, chats, 80)
                await send_alerts(client, conn, chats, args.dry_alert)
                if datetime.now(timezone.utc) - last_push >= timedelta(minutes=PUSH_MIN - 1):
                    write_site(conn, chats)
                    if not args.no_push:
                        push()
                    last_push = datetime.now(timezone.utc)
            except Exception:
                log.exception("갱신 중 오류 (다음 차례에 다시)")

    task = asyncio.create_task(loop())
    await client.run_until_disconnected()
    task.cancel()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--login", action="store_true", help="이 프로그램 전용 로그인만 하고 끝")
    ap.add_argument("--once", action="store_true", help="한 바퀴만 돌고 끝 (시험용)")
    ap.add_argument("--no-push", action="store_true", help="저장소에 올리지 않음 (시험용)")
    ap.add_argument("--dry-alert", action="store_true", help="알림을 보내지 않고 기록만 (시험용)")
    ap.add_argument("--session", default="telegram_live", help="로그인 파일 이름 (data/<이름>.session)")
    args = ap.parse_args()
    handlers = [logging.FileHandler(LOG, encoding="utf-8")]
    if sys.stdout and sys.stdout.isatty() or args.once or args.login:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%m/%d %H:%M", handlers=handlers)
    logging.getLogger("telethon").setLevel(logging.WARNING)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
