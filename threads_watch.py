"""무료 쓰레드 크롤러 — 내 PC(나중엔 여분 PC)에서 **5분마다 조금씩** 돌며 경제 글의 조회수가 크는 속도를 잰다.

    python threads_watch.py --loop      # 계속 켜 두기 (threads_watch_install.ps1 이 로그인 때 자동 실행)
    python threads_watch.py             # 한 번만 (5분치 한 바퀴)
    python threads_watch.py --no-push   # 깃허브에 안 올리고
    python threads_watch.py --export    # 크롤링 없이 사이트 파일만 다시

계정 화면·검색은 크롤링 전용 계정으로 로그인한 크롬(logged_browser, crawl_login.py)으로 → 계정당 글 40여 개 + 키워드 검색으로 새 계정 찾기.
로그인이 없거나 풀리면 예전처럼 로그인 없는 크롬(post_reader._dom)으로 공개 페이지만. 글 조회수는 늘 로그인 없이 잼(계정 아끼려고).
같은 걸 반복해서 긁지 않도록 '다음 확인 시각'을 따로 적어 두고 차례가 된 것만 연다.
  - 계정: 5분마다 마지막으로 본 지 가장 오래된 계정 ACCT_PER_TICK곳 → 76곳이면 약 1시간에 한 바퀴
  - 새 글: 계정에서 처음 보이면 바로 다음 차례에 조회수를 잰다
  - 글 다시 재기: 어릴수록 자주 (3시간 안 20분 / 12시간 안 45분 / 24시간 안 1.5시간 / 48시간 안 3시간),
    반응이 거의 없는 글은 6시간, 48시간이 지나면 그만
  - 매일 Apify 로 모은 경제 글은 1시간에 한 번 목록만 가져옴
  - 인스타도 같은 바퀴에서 조금씩 (insta_watch.py)
  → output/site/thx_live.json(+_meta)·igx_live.json(+_meta), 30분마다 깃허브 / 빨리 크는 글은 텔레그램 알림(글당 한 번)
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

import account_rank
import insta_watch
import logged_browser as lb
from common import DEFAULT_DB, OUTPUT_DIR, ROOT, load_env
from post_reader import _dom, _threads, _walk
from topics import topics_of

KST = timezone(timedelta(hours=9))
WATCH = ROOT / "config" / "threads_watch.txt"
DB = ROOT / "data" / "threads_watch.db"
LOG = ROOT / "data" / "threads_watch.log"
SITE = OUTPUT_DIR / "site"
TICK_S = 300           # 5분마다 한 바퀴
ACCT_PER_TICK = 6      # 한 바퀴에 훑는 계정 수
POSTS_PER_TICK = 20    # 한 바퀴에 조회수 재는 글 수
WORKERS = 2            # 동시에 여는 페이지 (천천히)
WINDOW_H = 48          # 이 시간 안에 올라온 글만 지켜봄
SEARCH_EVERY_S = 1800  # 키워드 검색으로 새 계정 찾기 간격 (로그인 때만)
FOUND_MAX = 80         # 검색으로 찾아 지켜보는 계정 최대 수
IMPORT_EVERY_S = 3600  # 매일 수집 글 목록 가져오기 간격
PUSH_EVERY_S = 1800    # 깃허브 올리는 간격
ALERT_VPH = 3000       # 올린 지 24시간 안에 시간당 조회 이만큼이면 알림
ALERT_MAX = 3          # 한 바퀴에 보내는 알림 수

log = logging.getLogger("threads_watch")


def db():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB)
    c.executescript("""CREATE TABLE IF NOT EXISTS posts (code TEXT PRIMARY KEY, url TEXT, username TEXT, followers INTEGER,
                         text TEXT, taken_at INTEGER, topics TEXT, source TEXT, first_seen INTEGER, alerted INTEGER DEFAULT 0);
                       CREATE TABLE IF NOT EXISTS snaps (code TEXT, at INTEGER, views INTEGER, likes INTEGER, replies INTEGER, reposts INTEGER);
                       CREATE INDEX IF NOT EXISTS snaps_code ON snaps(code, at);
                       CREATE TABLE IF NOT EXISTS accounts (username TEXT PRIMARY KEY, last_scan INTEGER, followers INTEGER);
                       CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v INTEGER);
                       CREATE TABLE IF NOT EXISTS th_found (username TEXT PRIMARY KEY, hits INTEGER, best_likes INTEGER,
                         keywords TEXT, first_seen INTEGER, last_seen INTEGER);""")
    cols = {r[1] for r in c.execute("PRAGMA table_info(posts)")}
    if "next_check" not in cols:   # 예전(3시간 일괄) 기록 → 차례표 붙이기
        c.execute("ALTER TABLE posts ADD COLUMN next_check INTEGER")
        c.execute("ALTER TABLE posts ADD COLUMN fails INTEGER DEFAULT 0")
        c.execute("ALTER TABLE posts ADD COLUMN likes_hint INTEGER")
        c.execute("UPDATE posts SET next_check=? WHERE taken_at >= ?", (int(time.time()), int(time.time()) - WINDOW_H * 3600))
    insta_watch.init(c)
    c.execute("DELETE FROM snaps WHERE views IS NULL")   # 프로필에서 찍던 좋아요 기록은 likes_hint 로 대신
    c.commit()
    return c


def kv(c, k, v=None):
    if v is None:
        r = c.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return r[0] if r else 0
    c.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (k, v))


def korean(text):
    return len(re.findall(r"[가-힣]", text or "")) >= 10


def accounts(c=None):
    """지켜볼 계정 = config/threads_watch.txt + 점수 높은 벤치마킹 계정(account_rank.py) + 검색에서 두 번 넘게 걸린 경제 계정."""
    mine = [l.strip().lstrip("@") for l in WATCH.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")] if WATCH.exists() else []
    found = [r[0] for r in c.execute("SELECT username FROM th_found WHERE hits >= 2 OR best_likes >= 300 "
                                     "ORDER BY best_likes DESC LIMIT ?", (FOUND_MAX,))] if c else []
    return list(dict.fromkeys(mine + account_rank.bench_accounts("threads") + found))


def add_post(c, code, url, user, followers, text, taken_at, source, now, likes=None):
    """처음 보는 글이면 바로 다음 차례에 재도록 넣는다. 이미 있으면 좋아요·팔로워만 갱신(중복 없음)."""
    c.execute("INSERT OR IGNORE INTO posts (code, url, username, followers, text, taken_at, topics, source, first_seen, next_check, fails) "
              "VALUES (?,?,?,?,?,?,?,?,?,?,0)", (code, url, user, followers, text, taken_at, ", ".join(topics_of(text)), source, now, now))
    if followers:
        c.execute("UPDATE posts SET followers=? WHERE code=?", (followers, code))
    if likes is not None:
        c.execute("UPDATE posts SET likes_hint=? WHERE code=?", (likes, code))


# ── 계정 프로필 ──
def profile(user):
    if lb.ready("threads"):
        html, bodies = lb.visit(f"https://www.threads.com/@{user}", scrolls=2)
        if html:
            f = re.search(r'"follower_count":(\d+)', html)
            return user, int(f.group(1)) if f else None, lb.threads_posts(html, bodies)
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


def scan_accounts(c, now, n):
    users = accounts(c)
    for u in users:
        c.execute("INSERT OR IGNORE INTO accounts (username, last_scan) VALUES (?, 0)", (u,))
    # 벤치마킹 계정은 30분 먼저 차례가 와서 더 자주 봄
    bench = set(account_rank.bench_accounts("threads"))
    last = dict(c.execute("SELECT username, last_scan FROM accounts WHERE username IN (%s)" % ",".join("?" * len(users)), users)) if users else {}
    pick = sorted(users, key=lambda u: (last.get(u) or 0) - (1800 if u in bench else 0))[:n]
    new = 0
    # 로그인 크롬은 한 곳에서 차례로만 쓸 수 있어서 그땐 동시에 열지 않음
    with ThreadPoolExecutor(WORKERS) as ex:
        for user, followers, posts in (map if lb.ready("threads") else ex.map)(profile, pick):
            c.execute("UPDATE accounts SET last_scan=?, followers=COALESCE(?, followers) WHERE username=?", (now, followers, user))
            for p in {p["code"]: p for p in posts}.values():
                info = p.get("text_post_app_info") or {}
                if info.get("is_reply") or p["user"]["username"] != user or not p.get("taken_at"):
                    continue
                if now - p["taken_at"] > WINDOW_H * 3600:
                    continue
                new += c.execute("SELECT 1 FROM posts WHERE code=?", (p["code"],)).fetchone() is None
                add_post(c, p["code"], f"https://www.threads.com/@{user}/post/{p['code']}", user, followers,
                         (p.get("caption") or {}).get("text") or "", p["taken_at"], "계정", now, p.get("like_count"))
    c.commit()
    return len(pick), new


# ── 키워드 검색으로 새 경제 계정 찾기 (로그인 때만, 30분에 한 번 키워드 하나) ──
def search_words():
    return [w for ws in account_rank.CATS.values() for w in ws if re.search(r"[가-힣]", w) and len(w) >= 2]


def discover(c, now):
    if not lb.ready("threads") or now - kv(c, "last_search") < SEARCH_EVERY_S:
        return None, 0
    words = search_words()
    i = kv(c, "search_i") % len(words)
    kv(c, "search_i", i + 1)
    kv(c, "last_search", now)
    word = words[i]
    html, bodies = lb.visit(f"https://www.threads.com/search?q={requests.utils.quote(word)}&serp_type=default", scrolls=3)
    users, new = set(), 0
    for p in lb.threads_posts(html, bodies):
        text = (p.get("caption") or {}).get("text") or ""
        user = (p.get("user") or {}).get("username")
        tp = topics_of(text)
        if not user or not korean(text) or not tp or tp == ["기타"] or (p.get("text_post_app_info") or {}).get("is_reply"):
            continue
        likes = p.get("like_count") or 0
        if user not in users:   # 한 검색에서 같은 계정은 한 번만 셈
            users.add(user)
            c.execute("INSERT INTO th_found VALUES (?,1,?,?,?,?) ON CONFLICT(username) DO UPDATE SET hits=hits+1, "
                      "best_likes=MAX(best_likes, excluded.best_likes), last_seen=excluded.last_seen, "
                      "keywords=CASE WHEN instr(keywords, excluded.keywords) > 0 THEN keywords ELSE keywords || ', ' || excluded.keywords END",
                      (user, likes, word, now, now))
        if p.get("taken_at") and now - p["taken_at"] <= WINDOW_H * 3600:
            new += c.execute("SELECT 1 FROM posts WHERE code=?", (p["code"],)).fetchone() is None
            add_post(c, p["code"], f"https://www.threads.com/@{user}/post/{p['code']}", user, None, text, p["taken_at"], "검색", now, likes)
    c.commit()
    return word, len(users)


# ── 매일 Apify 로 모은 최근 글 (1시간에 한 번 목록만) ──
def from_apify(c, now):
    if not DEFAULT_DB.exists() or now - kv(c, "last_import") < IMPORT_EVERY_S:
        return 0
    src = sqlite3.connect(DEFAULT_DB)
    since = datetime.fromtimestamp(now - WINDOW_H * 3600, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    n = 0
    for code, url, user, text, posted, followers, likes in src.execute(
            "SELECT code, url, username, text, posted_at, followers, likes FROM threads_apify "
            "WHERE posted_at >= ? AND (is_reply IS NULL OR is_reply = 0) AND code IS NOT NULL", (since,)):
        tp = topics_of(text or "")
        if not korean(text) or not tp or tp == ["기타"]:
            continue
        if c.execute("SELECT 1 FROM posts WHERE code=?", (code,)).fetchone():
            continue
        taken = int(datetime.fromisoformat(posted.replace("Z", "+00:00")).timestamp())
        add_post(c, code, (url or "").replace("threads.net", "threads.com"), user, followers, text, taken, "키워드", now, likes)
        n += 1
    kv(c, "last_import", now)
    c.commit()
    return n


# ── 글 조회수 재기 (차례 된 글만) ──
def next_gap(age_h, vph):
    if age_h >= WINDOW_H:
        return None                      # 48시간 지나면 그만
    if age_h >= 6 and vph < 50:
        return 6 * 3600                  # 반응이 거의 없는 글은 가끔만
    return (20 * 60 if age_h < 3 else 45 * 60 if age_h < 12 else 90 * 60 if age_h < 24 else 3 * 3600)


def views_of(url):
    try:
        return _threads(url, _dom(url))
    except (subprocess.TimeoutExpired, StopIteration, KeyError, TypeError):
        return None


def measure(c, now, n):
    due = c.execute("SELECT code, url, taken_at FROM posts WHERE next_check IS NOT NULL AND next_check <= ? "
                    "ORDER BY next_check, COALESCE(likes_hint, 0) DESC LIMIT ?", (now, n)).fetchall()
    ok = 0
    with ThreadPoolExecutor(WORKERS) as ex:
        for (code, url, taken), post in zip(due, ex.map(views_of, [d[1] for d in due])):
            at = int(time.time())
            if not post or post.get("views") is None:
                fails = c.execute("UPDATE posts SET fails=fails+1 WHERE code=? RETURNING fails", (code,)).fetchone()[0]
                c.execute("UPDATE posts SET next_check=? WHERE code=?", (None if fails >= 3 else at + 1800, code))
                continue
            c.execute("INSERT INTO snaps VALUES (?,?,?,?,?,?)",
                      (code, at, post["views"], post.get("likes"), post.get("replies"), post.get("reposts")))
            age_h = max(0.25, (at - taken) / 3600)
            gap = next_gap(age_h, post["views"] / age_h)
            c.execute("UPDATE posts SET next_check=?, fails=0, likes_hint=? WHERE code=?",
                      (at + gap if gap else None, post.get("likes"), code))
            if post.get("text"):
                c.execute("UPDATE posts SET text=?, topics=? WHERE code=? AND (text IS NULL OR text='')",
                          (post["text"], ", ".join(topics_of(post["text"])), code))
            ok += 1
    c.commit()
    return len(due), ok


# ── 크는 속도 계산 → 사이트 파일 ──
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
        prev = next((s for s in reversed(vs[:-1]) if at - s[0] >= 900), None)   # 15분 이상 떨어진 지난 기록과 비교
        if prev:
            growth = round((views - prev[1]) / ((at - prev[0]) / 3600))
        out.append({"code": code, "url": url, "username": user, "followers": followers, "text": (text or "")[:300],
                    "topics": topics or "", "source": source, "time": fmt_t(taken), "age_h": round(age_h, 1),
                    "views": views, "likes": likes, "replies": replies, "reposts": reposts,
                    "vph": round(views / age_h), "growth": growth, "checks": len(vs), "checked": fmt_t(at),
                    "spread": round(views / followers, 1) if followers else None,
                    "trend": [v for _, v, *_ in vs][-8:], "alerted": alerted})
    out.sort(key=lambda r: -(r["growth"] if r["growth"] is not None else r["vph"]))
    return out


def export(c, now):
    rows = metrics(c, now)
    SITE.mkdir(parents=True, exist_ok=True)
    keep = [{k: v for k, v in r.items() if k != "alerted"} for r in rows[:60]]
    (SITE / "thx_live.json").write_text(json.dumps(keep, ensure_ascii=False, indent=1), encoding="utf-8")
    tracked = c.execute("SELECT COUNT(*) FROM posts WHERE next_check IS NOT NULL").fetchone()[0]
    meta = [{"updated": fmt_t(now), "accounts": len(accounts()), "tracked": tracked, "measured": len(rows),
             "growing": sum(1 for r in rows if (r["growth"] or 0) >= 1000)}]
    (SITE / "thx_live_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return rows


# ── 알림 ──
def short_n(v):
    return f"{v / 10000:.1f}만".replace(".0만", "만") if v >= 10000 else f"{v:,}"


def alert(c, rows):
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return 0
    hot = [r for r in rows if not r["alerted"] and r["age_h"] <= 24 and max(r["vph"], r["growth"] or 0) >= ALERT_VPH][:ALERT_MAX]
    for r in hot:
        speed = max(r["vph"], r["growth"] or 0)
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
    return len(hot)


def git(*args):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="ignore",
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.returncode, (r.stdout + r.stderr).strip()


FREE = ROOT / "data" / "free_crawl.json"
FREE_DAYS = 7          # 매일 분석(free_import.py)에 넘기는 기간


def free_export(c, now):
    """유료 수집(Apify) 대신 — 최근 7일 글의 마지막 숫자를 data/free_crawl.json 으로 (깃허브가 아침에 insta.db 에 넣음)."""
    since = now - FREE_DAYS * 86400
    last = lambda t, cols, code: c.execute(f"SELECT {cols} FROM {t} WHERE code=? ORDER BY at DESC LIMIT 1", (code,)).fetchone()
    th = []
    for code, url, user, followers, text, taken in c.execute(
            "SELECT code, url, username, followers, text, taken_at FROM posts WHERE taken_at >= ?", (since,)).fetchall():
        s = last("snaps", "at, views, likes, replies, reposts", code)
        if s:
            th.append({"code": code, "url": url, "username": user, "followers": followers, "text": text or "", "taken_at": taken,
                       "at": s[0], "views": s[1], "likes": s[2], "replies": s[3], "reposts": s[4]})
    ig = []
    for code, url, acc, author, kind, slides, text, taken in c.execute(
            "SELECT code, url, account, author, kind, slides, text, taken_at FROM ig_posts WHERE taken_at >= ?", (since,)).fetchall():
        s = last("ig_snaps", "at, likes, comments, views", code)
        if s:
            ig.append({"code": code, "url": url, "username": author or acc, "kind": kind, "slides": slides, "text": text or "",
                       "taken_at": taken, "at": s[0], "likes": s[1], "comments": s[2], "views": s[3]})
    accs = [{"username": u, "followers": f} for u, f in c.execute("SELECT username, followers FROM ig_accounts WHERE followers IS NOT NULL")]
    FREE.write_text(json.dumps({"updated": now, "threads": th, "instagram": ig, "ig_accounts": accs}, ensure_ascii=False),
                    encoding="utf-8")


def push(c, now, force=False):
    if not force and now - kv(c, "last_push") < PUSH_EVERY_S:
        return
    kv(c, "last_push", now)
    c.commit()
    free_export(c, now)
    git("pull", "--rebase", "--autostash")
    git("add", "output/site/thx_live.json", "output/site/thx_live_meta.json", "output/site/igx_live.json", "output/site/igx_live_meta.json",
        "data/free_crawl.json")
    if git("commit", "-m", f"data: 쓰레드·인스타 실시간 추적 {datetime.now(KST).strftime('%m/%d %H:%M')}")[0] != 0:
        return
    code, out = git("push")
    log.info("깃허브 올리기 %s", "완료" if code == 0 else f"실패: {out[-200:]}")


def tick(c, no_push=False):
    now = int(time.time())
    start = time.time()
    na, new = scan_accounts(c, now, ACCT_PER_TICK)
    word, found = discover(c, now)
    imp = from_apify(c, now)
    nd, ok = measure(c, now, POSTS_PER_TICK)
    rows = export(c, now)
    sent = alert(c, rows)
    log.info("계정 %d곳(새 글 %d)%s%s · 매일수집 %d · 조회수 %d/%d · 알림 %d · %d초", na, new,
             " · 로그인" if lb.ready("threads") else "", f" · 검색 '{word}' 계정 {found}곳" if word else "",
             imp, ok, nd, sent, time.time() - start)
    try:
        insta_watch.tick(c)
    except Exception as e:   # 인스타가 실패해도 쓰레드는 계속
        log.info("인스타 바퀴 실패: %r", e)
    finally:
        lb.close()   # 한 바퀴 끝나면 로그인 크롬 닫기
    if not no_push:
        push(c, now)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--export", action="store_true")
    a = ap.parse_args()
    if sys.stdout:
        sys.stdout.reconfigure(encoding="utf-8")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    handlers = [logging.FileHandler(LOG, encoding="utf-8")] + ([logging.StreamHandler(sys.stdout)] if sys.stdout else [])
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%m/%d %H:%M", handlers=handlers)
    load_env()
    c = db()
    if a.export:
        export(c, int(time.time()))
        return
    if not a.loop:
        tick(c, a.no_push)
        return
    log.info("쓰레드·인스타 크롤러 켜짐 (5분마다)")
    while True:
        t0 = time.time()
        try:
            tick(c, a.no_push)
        except Exception as e:   # 한 바퀴가 실패해도 계속
            log.info("이번 바퀴 실패: %r", e)
        time.sleep(max(30, TICK_S - (time.time() - t0)))


if __name__ == "__main__":
    main()
