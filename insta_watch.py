"""무료 인스타 크롤러 — threads_watch.py 가 5분마다 같이 부른다 (따로 켤 것 없음).

    python insta_watch.py            # 한 번만 (계정 몇 곳 + 차례 된 글)
    python insta_watch.py --export   # 크롤링 없이 사이트 파일만 다시

크롤링 전용 계정으로 로그인한 크롬(logged_browser)이 있으면 계정 화면 + 릴스 탭을 열어 최근 글 12개의 좋아요·댓글·릴스 재생수를
한 번에 읽고(글을 따로 안 열어도 됨), 인스타가 보여 주는 '비슷한 계정'으로 새 계정도 찾는다.
로그인이 없거나 풀리면 예전처럼 로그인 없는 크롬(post_reader._dom)으로 공개 페이지만.
  - 계정(accounts.csv): 5분마다 가장 오래전에 본 곳 IG_ACCT곳 → 최근 글 12개 주소만 얻음 (48곳이면 약 1시간 20분에 한 바퀴)
  - 글: 차례 된 것만 열어 좋아요·댓글·올린 시각을 잼. 어릴수록 자주 (3시간 안 30분 / 12시간 안 1시간 /
    24시간 안 2시간 / 72시간 안 6시간), 반응이 거의 없으면 12시간, 72시간 지나면 그만
  - 릴스 조회수: 글 화면엔 없어서, 인스타가 다른 사이트용으로 공개한 '퍼가기(임베드)' 화면(/embed/captioned/)에서 읽음
    (앱에 보이는 재생수와는 셈법이 달라 숫자가 다를 수 있음 → 크는 속도 비교용). 못 읽으면 매일 수집 값
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
import logged_browser as lb
from post_reader import _dom
from topics import topics_of

KST = timezone(timedelta(hours=9))
ACCOUNTS = ROOT / "accounts.csv"
SITE = OUTPUT_DIR / "site"
IG_ACCT = 3            # 한 바퀴에 훑는 계정 수
IG_POSTS = 8           # 한 바퀴에 여는 글 수
WORKERS = 2
WINDOW_H = 72          # 인스타는 오래 크니까 3일
FOUND_MAX = 40        # '비슷한 계정'으로 찾아 지켜보는 계정 최대 수
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
                       CREATE TABLE IF NOT EXISTS ig_accounts (username TEXT PRIMARY KEY, last_scan INTEGER);
                       CREATE TABLE IF NOT EXISTS ig_found (username TEXT PRIMARY KEY, hits INTEGER, via TEXT, first_seen INTEGER);""")
    if "followers" not in {r[1] for r in c.execute("PRAGMA table_info(ig_accounts)")}:
        c.execute("ALTER TABLE ig_accounts ADD COLUMN followers INTEGER")
    if "views" not in {r[1] for r in c.execute("PRAGMA table_info(ig_snaps)")}:
        c.execute("ALTER TABLE ig_snaps ADD COLUMN views INTEGER")
    c.commit()


def kv(c, k, v=None):
    if v is None:
        r = c.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return r[0] if r else 0
    c.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (k, v))


def accounts(c=None):
    """accounts.csv + 등록 계정 두 곳 넘게에서 '비슷한 계정'으로 뜬 계정."""
    mine = []
    if ACCOUNTS.exists():
        with open(ACCOUNTS, encoding="utf-8") as f:
            mine = [r["username"].strip().lstrip("@") for r in csv.DictReader(f) if r.get("username")]
    found = [r[0] for r in c.execute("SELECT username FROM ig_found WHERE hits >= 2 ORDER BY hits DESC, first_seen LIMIT ?",
                                     (FOUND_MAX,))] if c else []
    return list(dict.fromkeys(mine + found))


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


def _with(o, key, out):
    """JSON 안에서 code 와 key 가 같이 있는 덩어리."""
    if isinstance(o, dict):
        if o.get("code") and key in o:
            out.append(o)
        o = list(o.values())
    if isinstance(o, list):
        for v in o:
            _with(v, key, out)
    return out


def _with_user(o, user, out):
    if isinstance(o, dict):
        if o.get("username") == user:
            out.append(o)
        o = list(o.values())
    if isinstance(o, list):
        for v in o:
            _with_user(v, user, out)
    return out


def logged_profile(user):
    """로그인 크롬: 계정 화면(최근 글) + 릴스 탭(재생수) → (팔로워, {code: 글 정보}, 비슷한 계정들)."""
    html, bodies = lb.visit(f"https://www.instagram.com/{user}/", scrolls=0)
    if html is None:
        return None
    me = [d for d in _with_user(bodies, user, []) if d.get("follower_count") is not None]
    posts = {}
    for conn in lb.find_key(bodies, "xdt_api__v1__feed__user_timeline_graphql_connection", []):
        for e in conn.get("edges") or []:
            m = e.get("node") or {}
            if not m.get("code") or not m.get("taken_at"):
                continue
            posts[m["code"]] = {"taken_at": m["taken_at"], "likes": m.get("like_count"), "comments": m.get("comment_count"),
                                "author": (m.get("user") or {}).get("username") or user,
                                "kind": KIND.get(m.get("product_type"), m.get("product_type")),
                                "slides": m.get("carousel_media_count"), "text": (m.get("caption") or {}).get("text") or "",
                                "views": m.get("play_count") or m.get("ig_play_count") or m.get("view_count"),
                                "path": "reel" if m.get("product_type") == "clips" else "p"}
    similar = []
    for ch in lb.find_key(bodies, "xdt_api__v1__discover__chaining", []):
        for group in lb.find_key(ch, "users", []):
            similar += [u.get("username") for u in group if isinstance(u, dict)] if isinstance(group, list) else []
    if any(p["kind"] == "릴스" for p in posts.values()):
        _, rb = lb.visit(f"https://www.instagram.com/{user}/reels/", scrolls=0)
        for m in _with(rb, "play_count", []):
            if m["code"] in posts and m.get("play_count"):
                posts[m["code"]]["views"] = m["play_count"]
    return (me[0]["follower_count"] if me else None), posts, [u for u in similar if u and u != user]


# ── 계정 프로필: 최근 글 주소만 ──
def profile(user):
    if lb.ready("instagram"):
        got = logged_profile(user)
        if got:
            return user, got[0], got
    try:
        dom = _dom(f"https://www.instagram.com/{user}/", wait_ms=10000, timeout=40)
    except subprocess.TimeoutExpired:
        return user, None, []
    f = re.search(r'"follower_count":(\d+)', dom)
    return user, int(f.group(1)) if f else None, sorted(set(re.findall(r'/(p|reel)/([\w-]{8,})/', dom)))


def save_logged(c, user, now, posts, similar):
    """로그인 화면에서 읽은 글은 바로 숫자까지 기록 (계정을 다시 볼 때마다 새로 잼 → 글을 따로 안 엶)."""
    new = 0
    for code, p in posts.items():
        url = f"https://www.instagram.com/{p['path']}/{code}/"
        new += c.execute("INSERT OR IGNORE INTO ig_posts (code, url, account, first_seen) VALUES (?,?,?,?)", (code, url, user, now)).rowcount
        c.execute("UPDATE ig_posts SET author=?, kind=?, slides=?, taken_at=?, next_check=NULL, fails=0 WHERE code=?",
                  (p["author"], p["kind"], p["slides"], p["taken_at"], code))
        if p["text"]:
            c.execute("UPDATE ig_posts SET text=?, topics=? WHERE code=? AND (text IS NULL OR text='')",
                      (p["text"], ", ".join(topics_of(p["text"])), code))
        if now - p["taken_at"] <= WINDOW_H * 3600:
            c.execute("INSERT INTO ig_snaps (code, at, likes, comments, views) VALUES (?,?,?,?,?)",
                      (code, now, p["likes"], p["comments"], p["views"]))
    for u in similar:
        c.execute("INSERT INTO ig_found VALUES (?,1,?,?) ON CONFLICT(username) DO UPDATE SET hits=hits+1, "
                  "via=CASE WHEN instr(via, excluded.via) > 0 THEN via ELSE via || ', ' || excluded.via END", (u, user, now))
    return new


def scan_accounts(c, now):
    users = accounts(c)
    for u in users:
        c.execute("INSERT OR IGNORE INTO ig_accounts (username, last_scan) VALUES (?, 0)", (u,))
    pick = [r[0] for r in c.execute("SELECT username FROM ig_accounts WHERE username IN (%s) ORDER BY last_scan LIMIT ?"
                                    % ",".join("?" * len(users)), (*users, IG_ACCT))] if users else []
    new = 0
    # 로그인 크롬은 한 곳에서 차례로만 쓸 수 있어서 그땐 동시에 열지 않음
    with ThreadPoolExecutor(WORKERS) as ex:
        for user, followers, links in (map if lb.ready("instagram") else ex.map)(profile, pick):
            if blocked(c, now, not links):
                break
            c.execute("UPDATE ig_accounts SET last_scan=?, followers=COALESCE(?, followers) WHERE username=?", (now, followers, user))
            if isinstance(links, tuple):   # 로그인 화면
                new += save_logged(c, user, now, links[1], links[2])
                continue
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


def embed_views(url):
    """공개 퍼가기 화면에서 영상 조회수만 읽는다."""
    try:
        m = re.search(r'video_view_count\\*":(\d+)', _dom(url + "embed/captioned/"))
    except subprocess.TimeoutExpired:
        return None
    return int(m.group(1)) if m else None


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
                        "hidden": m.get("like_and_view_counts_disabled"),
                        "views": embed_views(url) if m.get("media_type") == 2 else None}
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
    if lb.ready("instagram"):   # 로그인 땐 계정 화면을 다시 볼 때 숫자도 새로 잼 → 글을 따로 열지 않음 (로그인 없이 열면 빈 화면이 와서 쉬게 됨)
        c.execute("UPDATE ig_posts SET next_check=NULL WHERE next_check IS NOT NULL")
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
            c.execute("INSERT INTO ig_snaps (code, at, likes, comments, views) VALUES (?,?,?,?,?)",
                      (code, at, p["likes"], p["comments"], p["views"]))
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


def live_followers(c):
    return {u: f for u, f in c.execute("SELECT username, followers FROM ig_accounts WHERE followers IS NOT NULL")}


def fmt_t(ts):
    return datetime.fromtimestamp(ts, KST).strftime("%m/%d %H:%M")


def metrics(c, now):
    usual, views, followers = daily_info()
    followers.update(live_followers(c))
    out = []
    for code, url, acc, author, kind, slides, text, taken, topics, alerted in c.execute(
            "SELECT code, url, account, author, kind, slides, text, taken_at, topics, alerted FROM ig_posts WHERE taken_at >= ?",
            (now - WINDOW_H * 3600,)):
        ss = c.execute("SELECT at, likes, comments, views FROM ig_snaps WHERE code=? ORDER BY at", (code,)).fetchall()
        if not ss:
            continue
        at, likes, comments, v = ss[-1]
        vprev = next((s for s in reversed(ss[:-1]) if at - s[0] >= 900 and s[3] is not None), None)
        vgrowth = round((v - vprev[3]) / ((at - vprev[0]) / 3600)) if vprev and v is not None else None
        age_h = max(0.25, (at - taken) / 3600)
        prev = next((s for s in reversed(ss[:-1]) if at - s[0] >= 900 and s[1] is not None), None)
        growth = round((likes - prev[1]) / ((at - prev[0]) / 3600)) if prev and likes is not None else None
        base = usual.get(author) or usual.get(acc)
        out.append({"code": code, "url": url, "username": author or acc, "account": acc, "kind": kind or "", "slides": slides,
                    "followers": followers.get(author) or followers.get(acc), "text": (text or "")[:300], "topics": topics or "",
                    "time": fmt_t(taken), "age_h": round(age_h, 1), "likes": likes, "comments": comments,
                    "lph": round((likes or 0) / age_h), "growth": growth, "views": v if v is not None else views.get(code),
                    "vph": round(v / age_h) if v is not None else None, "vgrowth": vgrowth,
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
