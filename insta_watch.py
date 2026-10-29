"""무료 인스타 크롤러 — threads_watch.py 가 5분마다 같이 부른다 (따로 켤 것 없음).

    python insta_watch.py            # 한 번만 (계정 몇 곳 + 차례 된 글)
    python insta_watch.py --export   # 크롤링 없이 사이트 파일만 다시

로그인하지 않은 크롬(post_reader._dom)으로 공개 페이지만 읽는다. 쿠키·계정 저장 안 함. Apify 비용 없음.
  - 계정(accounts.csv): 5분마다 가장 오래전에 본 곳 IG_ACCT곳 → 최근 글 12개 주소만 얻음 (48곳이면 약 1시간 20분에 한 바퀴)
  - 글: 차례 된 것만 열어 좋아요·댓글·올린 시각을 잼. 어릴수록 자주 (3시간 안 30분 / 12시간 안 1시간 /
    24시간 안 2시간 / 72시간 안 6시간), 반응이 거의 없으면 12시간, 72시간 지나면 그만
  - 릴스 조회수는 로그인 없이는 안 보여서, 매일 수집(data/insta.db)에 있으면 그 값을 붙임
  - 인스타가 빈 화면을 3번 연속 주면 1시간 쉼 (막히지 않게)
  → output/site/igx_live.json(+_meta) / 평소보다 훨씬 빨리 크는 글은 텔레그램 알림(글당 한 번)
기록: data/threads_watch.db 의 ig_* 표 (PC에만)
"""
import argparse
import csv
import json
import logging
import os
import re
import sqlite3
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests

from common import DEFAULT_DB, OUTPUT_DIR, ROOT, load_env
from post_reader import _dom
from topics import topics_of

KST = timezone(timedelta(hours=9))
ACCOUNTS = ROOT / "accounts.csv"
SITE = OUTPUT_DIR / "site"
IG_ACCT = 3            # 한 바퀴에 훑는 계정 수
IG_POSTS = 8           # 한 바퀴에 여는 글 수
WORKERS = 2
WINDOW_H = 72          # 인스타는 오래 크니까 3일
PAUSE_S = 3600         # 막힌 것 같으면 쉬는 시간
ALERT_X = 3            # 평소 좋아요의 이만큼 배면 알림
ALERT_MIN_LIKES = 300
ALERT_MAX = 2
KIND = {"clips": "릴스", "carousel_container": "카드뉴스", "feed": "사진"}

log = logging.getLogger("threads_watch")


def init(c):
    c.executescript("""CREATE TABLE IF NOT EXISTS ig_posts (code TEXT PRIMARY KEY, url TEXT, account TEXT, author TEXT, kind TEXT,
                         slides INTEGER, text TEXT, taken_at INTEGER, topics TEXT, first_seen INTEGER, next_check INTEGER,
                         fails INTEGER DEFAULT 0, alerted INTEGER DEFAULT 0);
                       CREATE TABLE IF NOT EXISTS ig_snaps (code TEXT, at INTEGER, likes INTEGER, comments INTEGER);
                       CREATE INDEX IF NOT EXISTS ig_snaps_code ON ig_snaps(code, at);
                       CREATE TABLE IF NOT EXISTS ig_accounts (username TEXT PRIMARY KEY, last_scan INTEGER);""")
    c.commit()


def kv(c, k, v=None):
    if v is None:
        r = c.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return r[0] if r else 0
    c.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (k, v))


def accounts():
    if not ACCOUNTS.exists():
        return []
    with open(ACCOUNTS, encoding="utf-8") as f:
        return [r["username"].strip().lstrip("@") for r in csv.DictReader(f) if r.get("username")]


def blocked(c, now, empty):
    """빈 화면이 3번 연속이면 1시간 쉰다. 쉬는 중이면 True."""
    if now < kv(c, "ig_pause_until"):
        return True
    streak = kv(c, "ig_empty") + 1 if empty else 0
    kv(c, "ig_empty", streak)
    if streak >= 3:
        kv(c, "ig_pause_until", now + PAUSE_S)
        kv(c, "ig_empty", 0)
        log.info("인스타가 빈 화면을 계속 줘서 1시간 쉬어요")
    return False


# ── 계정 프로필: 최근 글 주소만 ──
def profile(user):
    try:
        dom = _dom(f"https://www.instagram.com/{user}/", wait_ms=10000, timeout=40)
    except subprocess.TimeoutExpired:
        return user, []
    return user, sorted(set(re.findall(r'/(p|reel)/([\w-]{8,})/', dom)))


def scan_accounts(c, now):
    users = accounts()
    for u in users:
        c.execute("INSERT OR IGNORE INTO ig_accounts VALUES (?, 0)", (u,))
    pick = [r[0] for r in c.execute("SELECT username FROM ig_accounts WHERE username IN (%s) ORDER BY last_scan LIMIT ?"
                                    % ",".join("?" * len(users)), (*users, IG_ACCT))] if users else []
    new = 0
    with ThreadPoolExecutor(WORKERS) as ex:
        for user, links in ex.map(profile, pick):
            if blocked(c, now, not links):
                break
            c.execute("UPDATE ig_accounts SET last_scan=? WHERE username=?", (now, user))
            for kind, code in links:
                # 처음 보는 글만 넣는다 (올린 시각은 글을 열어야 알 수 있어서 바로 다음 차례에 한 번 연다)
                new += c.execute("INSERT OR IGNORE INTO ig_posts (code, url, account, first_seen, next_check) VALUES (?,?,?,?,?)",
                                 (code, f"https://www.instagram.com/{kind}/{code}/", user, now, now)).rowcount
    c.commit()
    return len(pick), new


# ── 글 하나 열기 ──
def _find(o, code):
    if isinstance(o, dict):
        if o.get("code") == code and "taken_at" in o:
            return o
        o = list(o.values())
    if isinstance(o, list):
        for v in o:
            r = _find(v, code)
            if r:
                return r
    return None


def read_post(url):
    code = url.rstrip("/").rsplit("/", 1)[-1]
    try:
        dom = _dom(url)
    except subprocess.TimeoutExpired:
        return None
    for s in re.findall(r'<script type="application/json"[^>]*>(.*?)</script>', dom, re.S):
        if code in s and '"taken_at"' in s:
            try:
                m = _find(json.loads(s), code)
            except json.JSONDecodeError:
                continue
            if m:
                return {"taken_at": m["taken_at"], "likes": m.get("like_count"), "comments": m.get("comment_count"),
                        "author": (m.get("user") or {}).get("username"), "kind": KIND.get(m.get("product_type"), m.get("product_type")),
                        "slides": m.get("carousel_media_count"), "text": (m.get("caption") or {}).get("text") or "",
                        "hidden": m.get("like_and_view_counts_disabled")}
    return None


def next_gap(age_h, lph):
    if age_h >= WINDOW_H:
        return None
    if age_h >= 6 and lph < 5:
        return 12 * 3600
    return (30 * 60 if age_h < 3 else 3600 if age_h < 12 else 2 * 3600 if age_h < 24 else 6 * 3600)


def measure(c, now):
    if now < kv(c, "ig_pause_until"):
        return 0, 0
    due = c.execute("SELECT code, url FROM ig_posts WHERE next_check IS NOT NULL AND next_check <= ? ORDER BY next_check LIMIT ?",
                    (now, IG_POSTS)).fetchall()
    ok = 0
    with ThreadPoolExecutor(WORKERS) as ex:
        for (code, url), p in zip(due, ex.map(read_post, [d[1] for d in due])):
            at = int(time.time())
            if blocked(c, at, not p):
                break
            if not p:
                fails = c.execute("UPDATE ig_posts SET fails=fails+1 WHERE code=? RETURNING fails", (code,)).fetchone()[0]
                c.execute("UPDATE ig_posts SET next_check=? WHERE code=?", (None if fails >= 3 else at + 1800, code))
                continue
            c.execute("UPDATE ig_posts SET author=?, kind=?, slides=?, taken_at=?, fails=0 WHERE code=?",
                      (p["author"], p["kind"], p["slides"], p["taken_at"], code))
            if p["text"]:
                c.execute("UPDATE ig_posts SET text=?, topics=? WHERE code=? AND (text IS NULL OR text='')",
                          (p["text"], ", ".join(topics_of(p["text"])), code))
            age_h = max(0.25, (at - p["taken_at"]) / 3600)
            if age_h >= WINDOW_H:               # 고정해 둔 옛 글 등 → 기록 없이 그만
                c.execute("UPDATE ig_posts SET next_check=NULL WHERE code=?", (code,))
                continue
            c.execute("INSERT INTO ig_snaps VALUES (?,?,?,?)", (code, at, p["likes"], p["comments"]))
            gap = next_gap(age_h, (p["likes"] or 0) / age_h)
            c.execute("UPDATE ig_posts SET next_check=? WHERE code=?", (at + gap if gap else None, code))
            ok += 1
    c.commit()
    return len(due), ok


# ── 평소 반응·릴스 조회수 (매일 수집 기록에서) ──
def daily_info():
    usual, views, followers = {}, {}, {}
    if not DEFAULT_DB.exists():
        return usual, views, followers
    src = sqlite3.connect(DEFAULT_DB)
    since = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%S")
    by = {}
    for user, link, likes, v in src.execute("SELECT username, permalink, likes, views FROM posts WHERE timestamp >= ?", (since,)):
        if likes:
            by.setdefault(user, []).append(likes)
        if v and link:
            views[link.rstrip("/").rsplit("/", 1)[-1]] = v
    usual = {u: statistics.median(ls) for u, ls in by.items() if len(ls) >= 5}
    followers = {u: f for u, f in src.execute("SELECT username, followers FROM accounts") if f}
    return usual, views, followers


def fmt_t(ts):
    return datetime.fromtimestamp(ts, KST).strftime("%m/%d %H:%M")


def metrics(c, now):
    usual, views, followers = daily_info()
    out = []
    for code, url, acc, author, kind, slides, text, taken, topics, alerted in c.execute(
            "SELECT code, url, account, author, kind, slides, text, taken_at, topics, alerted FROM ig_posts WHERE taken_at >= ?",
            (now - WINDOW_H * 3600,)):
        ss = c.execute("SELECT at, likes, comments FROM ig_snaps WHERE code=? ORDER BY at", (code,)).fetchall()
        if not ss:
            continue
        at, likes, comments = ss[-1]
        age_h = max(0.25, (at - taken) / 3600)
        prev = next((s for s in reversed(ss[:-1]) if at - s[0] >= 900 and s[1] is not None), None)
        growth = round((likes - prev[1]) / ((at - prev[0]) / 3600)) if prev and likes is not None else None
        base = usual.get(author) or usual.get(acc)
        out.append({"code": code, "url": url, "username": author or acc, "account": acc, "kind": kind or "", "slides": slides,
                    "followers": followers.get(author) or followers.get(acc), "text": (text or "")[:300], "topics": topics or "",
                    "time": fmt_t(taken), "age_h": round(age_h, 1), "likes": likes, "comments": comments,
                    "lph": round((likes or 0) / age_h), "growth": growth, "views": views.get(code),
                    "x_usual": round(likes / base, 1) if base and likes is not None else None,
                    "checks": len(ss), "checked": fmt_t(at), "trend": [s[1] for s in ss if s[1] is not None][-8:], "alerted": alerted})
    out.sort(key=lambda r: -(r["growth"] if r["growth"] is not None else r["lph"]))
    return out


def export(c, now):
    rows = metrics(c, now)
    SITE.mkdir(parents=True, exist_ok=True)
    keep = [{k: v for k, v in r.items() if k != "alerted"} for r in rows[:60]]
    (SITE / "igx_live.json").write_text(json.dumps(keep, ensure_ascii=False, indent=1), encoding="utf-8")
    tracked = c.execute("SELECT COUNT(*) FROM ig_posts WHERE next_check IS NOT NULL").fetchone()[0]
    meta = [{"updated": fmt_t(now), "accounts": len(accounts()), "tracked": tracked, "measured": len(rows),
             "hot": sum(1 for r in rows if (r["x_usual"] or 0) >= 2),
             "paused": fmt_t(kv(c, "ig_pause_until")) if now < kv(c, "ig_pause_until") else ""}]
    (SITE / "igx_live_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return rows


def short_n(v):
    return f"{v / 10000:.1f}만".replace(".0만", "만") if v >= 10000 else f"{v:,}"


def alert(c, rows):
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return 0
    hot = [r for r in rows if not r["alerted"] and r["age_h"] <= 24 and (r["likes"] or 0) >= ALERT_MIN_LIKES
           and (r["x_usual"] or 0) >= ALERT_X][:ALERT_MAX]
    for r in hot:
        lines = [f"🔥 지금 크는 인스타 {r['kind'] or '글'} · 평소 좋아요의 {r['x_usual']}배",
                 f"@{r['username']} · 올린 지 {r['age_h']}시간 · 좋아요 {short_n(r['likes'])} · 댓글 {short_n(r['comments'] or 0)}"
                 + (f" · 조회 {short_n(r['views'])}" if r["views"] else "") + (f" · 주제 {r['topics']}" if r["topics"] else ""),
                 "", r["text"][:200], "", r["url"]]
        try:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=20,
                          json={"chat_id": chat, "text": "\n".join(lines), "disable_web_page_preview": True})
            c.execute("UPDATE ig_posts SET alerted=1 WHERE code=?", (r["code"],))
        except requests.RequestException as e:
            log.info("알림 실패: %s", e)
    c.commit()
    return len(hot)


def tick(c):
    """threads_watch 한 바퀴 안에서 부른다."""
    now = int(time.time())
    start = time.time()
    if now < kv(c, "ig_pause_until"):
        na = new = nd = ok = 0
    else:
        na, new = scan_accounts(c, now)
        nd, ok = measure(c, now)
    rows = export(c, now)
    sent = alert(c, rows)
    log.info("인스타 계정 %d곳(새 글 %d) · 글 %d/%d · 알림 %d · %d초", na, new, ok, nd, sent, time.time() - start)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", action="store_true")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%m/%d %H:%M")
    load_env()
    from threads_watch import db
    c = db()
    init(c)
    if a.export:
        export(c, int(time.time()))
    else:
        tick(c)


if __name__ == "__main__":
    main()
