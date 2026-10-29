"""무료 쓰레드 크롤러 — 내 PC(나중엔 여분 PC)에서 3시간마다 돌며 경제 글의 **조회수가 크는 속도**를 잰다.

    python threads_watch.py             # 한 번 돌기 (계정 훑기 → 글 조회수 재기 → 사이트 파일 → 깃허브)
    python threads_watch.py --no-push   # 깃허브에 안 올리고 파일만
    python threads_watch.py --export    # 크롤링 없이 사이트 파일만 다시

로그인하지 않은 크롬(post_reader._dom)으로 공개 페이지만 읽는다. 쿠키·계정 저장 안 함. Apify 비용 없음.
  1) config/threads_watch.txt 계정 프로필 → 최근 48시간 글(답글 제외)과 좋아요·답글
  2) 매일 Apify 로 모은 최근 48시간 경제 글도 함께 지켜봄
  3) 글 페이지를 열어 조회수를 찍는다 (2.5시간에 한 번, 좋아요 속도 빠른 글부터 최대 MAX_OPEN개)
  4) 조회수 기록이 두 번 이상이면 '지난번 뒤로 시간당 몇 회' = 지금 크는 속도
  → output/site/thx_live.json(+_meta) / 빨리 크는 글은 텔레그램 알림(하루 글당 한 번)
기록: data/threads_watch.db (PC에만, 저장소에 안 올림)
"""
import argparse
import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests

from common import DEFAULT_DB, OUTPUT_DIR, ROOT, load_env
from post_reader import _dom, _threads, _walk
from topics import topics_of

KST = timezone(timedelta(hours=9))
WATCH = ROOT / "config" / "threads_watch.txt"
DB = ROOT / "data" / "threads_watch.db"
LOG = ROOT / "data" / "threads_watch.log"
SITE = OUTPUT_DIR / "site"
WINDOW_H = 48          # 이 시간 안에 올라온 글만 지켜봄
REOPEN_H = 2.5         # 같은 글 조회수는 이 간격 이상일 때만 다시 잼
MAX_OPEN = 250         # 한 번에 여는 글 페이지 수 (4개씩 동시에 열어 250장 약 4분)
WORKERS = 4
ALERT_VPH = 3000       # 올린 지 24시간 안에 시간당 조회 이만큼이면 알림
ALERT_MAX = 3          # 한 번에 보내는 알림 수

log = logging.getLogger("threads_watch")


def db():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB)
    c.executescript("""CREATE TABLE IF NOT EXISTS posts (code TEXT PRIMARY KEY, url TEXT, username TEXT, followers INTEGER,
                         text TEXT, taken_at INTEGER, topics TEXT, source TEXT, first_seen INTEGER, alerted INTEGER DEFAULT 0);
                       CREATE TABLE IF NOT EXISTS snaps (code TEXT, at INTEGER, views INTEGER, likes INTEGER, replies INTEGER, reposts INTEGER);
                       CREATE INDEX IF NOT EXISTS snaps_code ON snaps(code, at);""")
    return c


def korean(text):
    return len(re.findall(r"[가-힣]", text or "")) >= 10


def accounts():
    if not WATCH.exists():
        return []
    return [l.strip().lstrip("@") for l in WATCH.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]


# ── 1) 계정 프로필 훑기 ──
def profile(user):
    try:
        dom = _dom(f"https://www.threads.com/@{user}")
    except subprocess.TimeoutExpired:
        return user, None, []
    posts = []
    for s in re.findall(r'<script type="application/json"[^>]*>(.*?)</script>', dom, re.S):
        if '"like_count"' in s:
            try:
                _walk(json.loads(s), posts)
            except json.JSONDecodeError:
                pass
    f = re.search(r'"follower_count":(\d+)', dom)
    return user, int(f.group(1)) if f else None, posts


def scan_accounts(c, now):
    users = accounts()
    found = 0
    with ThreadPoolExecutor(WORKERS) as ex:
        for user, followers, posts in ex.map(profile, users):
            for p in {p["code"]: p for p in posts}.values():
                info = p.get("text_post_app_info") or {}
                if info.get("is_reply") or p["user"]["username"] != user or not p.get("taken_at"):
                    continue
                if now - p["taken_at"] > WINDOW_H * 3600:
                    continue
                text = (p.get("caption") or {}).get("text") or ""
                add_post(c, p["code"], f"https://www.threads.com/@{user}/post/{p['code']}", user, followers, text,
                         p["taken_at"], "계정", now)
                c.execute("INSERT INTO snaps VALUES (?,?,?,?,?,?)", (p["code"], now, None, p.get("like_count"),
                                                                    info.get("direct_reply_count"), info.get("repost_count")))
                found += 1
    c.commit()
    log.info("계정 %d곳에서 최근 글 %d개", len(users), found)


def add_post(c, code, url, user, followers, text, taken_at, source, now):
    c.execute("INSERT OR IGNORE INTO posts (code, url, username, followers, text, taken_at, topics, source, first_seen) "
              "VALUES (?,?,?,?,?,?,?,?,?)", (code, url, user, followers, text, taken_at, ", ".join(topics_of(text)), source, now))
    if followers:
        c.execute("UPDATE posts SET followers=? WHERE code=?", (followers, code))


# ── 2) 매일 Apify 로 모은 최근 글 ──
def from_apify(c, now):
    if not DEFAULT_DB.exists():
        return
    src = sqlite3.connect(DEFAULT_DB)
    since = datetime.fromtimestamp(now - WINDOW_H * 3600, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    n = 0
    for code, url, user, text, posted, followers in src.execute(
            "SELECT code, url, username, text, posted_at, followers FROM threads_apify "
            "WHERE posted_at >= ? AND (is_reply IS NULL OR is_reply = 0) AND code IS NOT NULL", (since,)):
        tp = topics_of(text or "")
        if not korean(text) or not tp or tp == ["기타"]:
            continue
        taken = int(datetime.fromisoformat(posted.replace("Z", "+00:00")).timestamp())
        add_post(c, code, (url or "").replace("threads.net", "threads.com"), user, followers, text, taken, "키워드", now)
        n += 1
    c.commit()
    log.info("매일 수집에서 최근 경제 글 %d개", n)


# ── 3) 글 페이지 열어 조회수 재기 ──
def due_posts(c, now):
    rows = c.execute("""SELECT p.code, p.url, p.taken_at,
                          (SELECT likes FROM snaps s WHERE s.code=p.code AND likes IS NOT NULL ORDER BY at DESC LIMIT 1),
                          (SELECT MAX(at) FROM snaps s WHERE s.code=p.code AND views IS NOT NULL)
                        FROM posts p WHERE p.taken_at >= ?""", (now - WINDOW_H * 3600,)).fetchall()
    due = [r for r in rows if not r[4] or now - r[4] >= REOPEN_H * 3600]
    due.sort(key=lambda r: -((r[3] or 0) / max(1, (now - r[2]) / 3600)))   # 좋아요 속도 빠른 글부터
    return due[:MAX_OPEN]


def views_of(url):
    try:
        return url, _threads(url, _dom(url))
    except (subprocess.TimeoutExpired, StopIteration, KeyError, TypeError):
        return url, None


def measure(c, now):
    due = due_posts(c, now)
    ok = 0
    with ThreadPoolExecutor(WORKERS) as ex:
        for (code, url, *_), (_, post) in zip(due, ex.map(views_of, [d[1] for d in due])):
            if not post or post.get("views") is None:
                continue
            c.execute("INSERT INTO snaps VALUES (?,?,?,?,?,?)",
                      (code, int(time.time()), post["views"], post.get("likes"), post.get("replies"), post.get("reposts")))
            if post.get("text"):
                c.execute("UPDATE posts SET text=?, topics=? WHERE code=? AND (text IS NULL OR text='')",
                          (post["text"], ", ".join(topics_of(post["text"])), code))
            ok += 1
    c.commit()
    log.info("글 %d개 열어 조회수 %d개 기록", len(due), ok)


# ── 4) 크는 속도 계산 → 사이트 파일 ──
def fmt_t(ts):
    return datetime.fromtimestamp(ts, KST).strftime("%m/%d %H:%M")


def metrics(c, now):
    out = []
    for code, url, user, followers, text, taken, topics, source, alerted in c.execute(
            "SELECT code, url, username, followers, text, taken_at, topics, source, alerted FROM posts WHERE taken_at >= ?",
            (now - WINDOW_H * 3600,)):
        vs = c.execute("SELECT at, views, likes, replies, reposts FROM snaps WHERE code=? AND views IS NOT NULL ORDER BY at",
                       (code,)).fetchall()
        if not vs:
            continue
        at, views, likes, replies, reposts = vs[-1]
        age_h = max(0.25, (at - taken) / 3600)
        growth = None
        if len(vs) >= 2 and at - vs[-2][0] >= 1800:
            growth = round((views - vs[-2][1]) / ((at - vs[-2][0]) / 3600))
        out.append({"code": code, "url": url, "username": user, "followers": followers, "text": (text or "")[:300],
                    "topics": topics or "", "source": source, "time": fmt_t(taken), "age_h": round(age_h, 1),
                    "views": views, "likes": likes, "replies": replies, "reposts": reposts,
                    "vph": round(views / age_h), "growth": growth, "checks": len(vs),
                    "spread": round(views / followers, 1) if followers else None,
                    "trend": [v for _, v, *_ in vs][-6:], "alerted": alerted})
    # 지금 크는 속도(없으면 평균 속도) 순
    out.sort(key=lambda r: -(r["growth"] if r["growth"] is not None else r["vph"]))
    return out


def export(c, now):
    rows = metrics(c, now)
    SITE.mkdir(parents=True, exist_ok=True)
    keep = [{k: v for k, v in r.items() if k != "alerted"} for r in rows[:60]]
    (SITE / "thx_live.json").write_text(json.dumps(keep, ensure_ascii=False, indent=1), encoding="utf-8")
    tracked = c.execute("SELECT COUNT(*) FROM posts WHERE taken_at >= ?", (now - WINDOW_H * 3600,)).fetchone()[0]
    meta = [{"updated": fmt_t(now), "accounts": len(accounts()), "tracked": tracked, "measured": len(rows),
             "growing": sum(1 for r in rows if (r["growth"] or 0) >= 1000)}]
    (SITE / "thx_live_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("사이트 파일: 조회수 잰 글 %d개 (지켜보는 글 %d개)", len(rows), tracked)
    return rows


# ── 알림 ──
def short_n(v):
    return f"{v / 10000:.1f}만".replace(".0만", "만") if v >= 10000 else f"{v:,}"


def alert(c, rows):
    load_env()
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return
    hot = [r for r in rows if not r["alerted"] and r["age_h"] <= 24 and max(r["vph"], r["growth"] or 0) >= ALERT_VPH][:ALERT_MAX]
    for r in hot:
        speed = r["growth"] if r["growth"] is not None else r["vph"]
        lines = [f"🔥 지금 크는 쓰레드 글 · 시간당 조회 {short_n(speed)}",
                 f"@{r['username']}" + (f" (팔로워 {short_n(r['followers'])})" if r["followers"] else "") +
                 f" · 올린 지 {r['age_h']}시간 · 조회 {short_n(r['views'])}" + (f" · 주제 {r['topics']}" if r["topics"] else ""),
                 "", r["text"][:200], "", r["url"]]
        try:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=20,
                          json={"chat_id": chat, "text": "\n".join(lines), "disable_web_page_preview": True})
            c.execute("UPDATE posts SET alerted=1 WHERE code=?", (r["code"],))
        except requests.RequestException as e:
            log.info("알림 실패: %s", e)
    c.commit()
    if hot:
        log.info("텔레그램 알림 %d개", len(hot))


def git(*args):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    return r.returncode, (r.stdout + r.stderr).strip()


def push():
    git("pull", "--rebase", "--autostash")
    git("add", "output/site/thx_live.json", "output/site/thx_live_meta.json")
    if git("commit", "-m", f"data: 쓰레드 조회수 추적 {datetime.now(KST).strftime('%m/%d %H:%M')}")[0] != 0:
        return
    code, out = git("push")
    log.info("깃허브 올리기 %s", "완료" if code == 0 else f"실패: {out[-200:]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--export", action="store_true")
    a = ap.parse_args()
    if sys.stdout:
        sys.stdout.reconfigure(encoding="utf-8")
    handlers = [logging.FileHandler(LOG, encoding="utf-8")] + ([logging.StreamHandler(sys.stdout)] if sys.stdout else [])
    LOG.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%m/%d %H:%M", handlers=handlers)
    c, now = db(), int(time.time())
    if not a.export:
        start = time.time()
        scan_accounts(c, now)
        from_apify(c, now)
        measure(c, now)
        log.info("크롤링 %d초", time.time() - start)
    rows = export(c, now)
    if not a.export:
        alert(c, rows)
    if not (a.no_push or a.export):
        push()


if __name__ == "__main__":
    main()
