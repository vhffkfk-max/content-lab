"""텔레그램 방 실시간 수집 + 반응 큰 글 알림 (내 PC에서 계속 켜 두는 프로그램).

    python tg_live.py --login     # 처음 한 번: 이 프로그램 전용 로그인 (코드 입력)
    python tg_live.py             # 계속 실행 (작업 스케줄러가 PC 로그온 때 자동 시작)
    python tg_live.py --once --no-push --session telegram --dry-alert   # 시험: 한 바퀴만, 올리기·알림 보내기 없이

하는 일:
  - telegram_chats.csv 에 표시한 방의 새 글을 올라오는 즉시 저장 (data/telegram_history.db 에 계속 쌓음, 저장소에 안 올라감)
  - 구독자 수를 매일 기록 (내 채널은 10분마다, 다른 채널은 1시간마다 최신값)
  - 10분마다 최근 글의 조회수·반응을 새로 읽고, 평소의 3배 이상 반응이 나온 24시간 안 글을 내 텔레그램 '저장된 메시지'로 알림
  - 30분마다 사이트용 통계·키우기 지표(output/site/tg_*.json, tg_metrics.py)를 만들어 저장소에 올림 → 서버가 사이트 다시 배포
Claude 를 부르지 않아 토큰 비용이 없다 (오늘의 문구는 서버가 하루 한 번만 씀).
"""
import argparse
import asyncio
import csv
import logging
import os
import re
import sqlite3
import statistics
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from common import DATA_DIR, OUTPUT_DIR, ROOT, load_env
from tg_collect import MIN_GROUP_CHARS, link_of, media_of
from tg_login import CHATS
import tg_analyze
import tg_metrics
from tg_history import SCHEMA as HISTORY_SCHEMA

DB = DATA_DIR / "telegram_history.db"   # tg_history.py 와 같은 곳에 쌓음 (1년 치 + 실시간)
LOG = DATA_DIR / "tg_live.log"
SITE = OUTPUT_DIR / "site"
KEEP_DAYS = 7
REFRESH_MIN, PUSH_MIN = 10, 30
ALERT_X, ALERT_HOURS, ALERT_MAX = 3.0, 24, 10
# 시황 원문으로 쓰는 채널: 아침('10월 26일 시황.')·마감('마감 시황.') 긴 글을 바로 올려 서버가 말희아빠 시황으로 변환 (tg_rewrite.py)
SOURCE_USERS = {"shmstory"}
MORNING_RE = re.compile(r"^\s*\d{1,2}월\s*\d{1,2}일\s*시황")
CLOSE_RE = re.compile(r"^\s*마감\s*시황")
SITE_FILES = ["tg_source", "tg_meta", "tg_chats", "tg_hot", "tg_mine", "tg_hours", "tg_lengths", "tg_media",
              "tg_growth", "tg_streak", "tg_slots", "tg_shared", "tg_rank"]

SCHEMA = HISTORY_SCHEMA + """
CREATE TABLE IF NOT EXISTS alerted (chat_id TEXT, id INTEGER, PRIMARY KEY (chat_id, id));
CREATE TABLE IF NOT EXISTS members (date TEXT, chat_id TEXT, count INTEGER, PRIMARY KEY (date, chat_id));
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
        "INSERT INTO msgs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(chat_id, id) DO UPDATE SET text=excluded.text, "
        "views=excluded.views, forwards=excluded.forwards, replies=excluded.replies, reactions=excluded.reactions",
        (ch["id"], m.id, m.date.isoformat(), text[:2000], m.views, m.forwards, m.replies.replies if m.replies else 0,
         reactions, media_of(m), int("http" in text), int(m.fwd_from is not None), str(m.grouped_id or ""),
         str(m.sender_id or "")))


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
    conn.commit()


async def record_members(client, conn, chats):
    """구독자 수를 오늘 날짜로 기록 (하루 중 마지막 값이 남음)."""
    from telethon.tl.functions.channels import GetFullChannelRequest
    today = datetime.now(tg_analyze.KST).date().isoformat()
    for ch in chats:
        try:
            full = await client(GetFullChannelRequest(int(ch["id"])))
            conn.execute("INSERT OR REPLACE INTO members VALUES (?, ?, ?)", (today, ch["id"], full.full_chat.participants_count))
        except Exception as e:
            log.warning("구독자 수 %s: %s", ch["이름"], e)
    conn.commit()


def snapshot(conn, chats):
    """tg_collect 와 같은 모양의 데이터 → tg_analyze.build 로 사이트 통계."""
    cols = ["chat_id", "id", "date", "text", "views", "forwards", "replies", "reactions", "media"]
    since = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).isoformat()
    by_id = {c["id"]: c for c in chats}
    msgs = [dict(zip(cols, r)) for r in conn.execute(f"SELECT {', '.join(cols)} FROM msgs WHERE date >= ?", (since,))
            if r[0] in by_id]
    for m in msgs:
        m["link"] = link_of(by_id[m["chat_id"]], m["id"])
    return {"collected": datetime.now(timezone.utc).isoformat(timespec="seconds"), "days": KEEP_DAYS,
            "chats": [{"id": c["id"], "title": c["이름"], "username": c["아이디"], "kind": c["종류"], "members": c["인원"],
                       "role": "mine" if "내" in c["분석"] else "other"} for c in chats],
            "messages": msgs}


def source_posts(conn, chats):
    """시황 원문 채널의 최근 3일 긴 글 (아침·마감 시황 표시)."""
    since = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    out = []
    for c in chats:
        if (c["아이디"] or "").lower() not in SOURCE_USERS:
            continue
        for mid, date, text in conn.execute("SELECT id, date, text FROM msgs WHERE chat_id=? AND date >= ? AND length(text) >= 400 "
                                            "ORDER BY date", (c["id"], since)):
            kind = "아침" if MORNING_RE.match(text) else "마감" if CLOSE_RE.match(text) else "기타"
            out.append({"id": f"{c['id']}_{mid}", "chat": c["이름"], "date": date, "kind": kind, "text": text,
                        "time": datetime.fromisoformat(date).astimezone(tg_analyze.KST).strftime("%m/%d %H:%M"),
                        "link": link_of(c, mid)})
    return out


def write_site(conn, chats):
    import json
    out = tg_analyze.build(snapshot(conn, chats), datetime.now(timezone.utc))
    out.update(tg_metrics.compute(conn, chats))
    out["tg_source"] = source_posts(conn, chats)
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
        since = (now - timedelta(days=KEEP_DAYS)).isoformat()
        rows = [(r[0], r[1], r[2], r[3], r[4], r[5], link_of(ch, r[0])) for r in conn.execute(
            "SELECT id, date, text, views, reactions, replies FROM msgs WHERE chat_id=? AND date >= ?", (ch["id"], since))]
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


async def deliver_rewrites(client, conn, dry):
    """서버가 변환한 말희아빠 시황(output/site/tg_rewrites.json)을 내 텔레그램 '저장된 메시지'로 한 번씩 보낸다."""
    import json
    git("pull", "--rebase", "--autostash")
    path = OUTPUT_DIR / "site" / "tg_rewrites.json"
    if not path.exists():
        return
    for r in json.loads(path.read_text(encoding="utf-8") or "[]"):
        key = int(str(r["source_id"]).rsplit("_", 1)[-1])
        if conn.execute("SELECT 1 FROM alerted WHERE chat_id='rewrite' AND id=?", (key,)).fetchone():
            continue
        head = f"🥛 {r['kind']}시황 변환 완료 (원문 {r['source_time']})"
        checks = "\n".join(f"· {c}" for c in r.get("check") or [])
        if dry:
            log.info("시황 변환(시험) %s", head)
        else:
            await client.send_message("me", f"{head}\n올리기 전 확인:\n{checks}" if checks else head, link_preview=False)
            await client.send_message("me", r["text"], link_preview=False)   # 이 메시지를 그대로 전달·복사해서 올리면 됨
        conn.execute("INSERT OR IGNORE INTO alerted VALUES ('rewrite', ?)", (key,))
        conn.commit()
        log.info("시황 변환본 보냄: %s", head)


async def ig_alert(client, conn, dry):
    """서버가 남긴 인스타 수집 상태(output/site/ig_health.json)가 '막힘'이면 내 텔레그램으로 한 번 알림."""
    import json
    path = OUTPUT_DIR / "site" / "ig_health.json"
    if not path.exists():
        return
    h = json.loads(path.read_text(encoding="utf-8"))[0]
    if h.get("status") != "blocked":
        return
    key = int(datetime.fromisoformat(h["checked"]).timestamp())
    if conn.execute("SELECT 1 FROM alerted WHERE chat_id='ig_health' AND id=?", (key,)).fetchone():
        return
    text = ("⛔ 인스타그램 수집이 멈췄어요 (연구소 사이트)\n\n"
            f"{h.get('message', '')[:200]}\n\n"
            "developers.facebook.com 에 들어가 '계정 확인'이나 앱 경고를 처리한 뒤 Claude에게 '인스타 다시 연결해줘'라고 말해 주세요.")
    if dry:
        log.info("인스타 알림(시험) %s", text.replace("\n", " / "))
    else:
        await client.send_message("me", text, link_preview=False)
    conn.execute("INSERT OR IGNORE INTO alerted VALUES ('ig_health', ?)", (key,))
    conn.commit()


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
    for c in chats:
        conn.execute("INSERT OR REPLACE INTO chats VALUES (?,?,?,?,?,?)", (c["id"], c["이름"], c["아이디"], c["종류"],
                     int(c["인원"] or 0), "mine" if "내" in c["분석"] else "other"))
    first = conn.execute("SELECT COUNT(*) FROM alerted").fetchone()[0] == 0   # 처음 켜는 것
    await refresh(client, conn, chats, 300 if first else 80)
    await record_members(client, conn, chats)
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
        last_push = last_members = datetime.now(timezone.utc)
        mine = [c for c in chats if "내" in c["분석"]]
        last_source = max((s["id"] for s in source_posts(conn, chats) if s["kind"] != "기타"), default=None)
        while True:
            await asyncio.sleep(REFRESH_MIN * 60)
            try:
                await refresh(client, conn, chats, 80)
                await send_alerts(client, conn, chats, args.dry_alert)
                hourly = datetime.now(timezone.utc) - last_members >= timedelta(minutes=59)
                await record_members(client, conn, chats if hourly else mine)
                if hourly:
                    last_members = datetime.now(timezone.utc)
                newest = max((s["id"] for s in source_posts(conn, chats) if s["kind"] != "기타"), default=None)
                new_source = newest is not None and newest != last_source
                if new_source:
                    log.info("새 시황 원문 감지 → 바로 올림 (서버가 말희아빠 시황으로 변환)")
                    last_source = newest
                if new_source or datetime.now(timezone.utc) - last_push >= timedelta(minutes=PUSH_MIN - 1):
                    write_site(conn, chats)
                    if not args.no_push:
                        push()
                    await ig_alert(client, conn, args.dry_alert)
                    last_push = datetime.now(timezone.utc)
                if not args.no_push:
                    await deliver_rewrites(client, conn, args.dry_alert)
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
