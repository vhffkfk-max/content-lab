"""무료 X 크롤러 — threads_watch.py 가 5분마다 같이 부른다 (따로 켤 것 없음). 크롤링 전용 X 계정 로그인이 있을 때만.

    python x_watch.py            # 한 번만
    python crawl_login.py --x    # X 전용 계정 로그인 (처음 한 번)

크롤링 전용 계정으로 로그인한 크롬(logged_browser)으로 계정 화면·검색 화면을 열어, 화면이 불러온 글(조회수·좋아요·답글·
리포스트·인용·북마크)을 읽는다. 유료 수집(Apify, x_collect.py)을 대신함.
  - 핵심 인물(x_accounts.csv — 트럼프·백악관·재무장관·연준·머스크·속보 계정): 5분마다 VIP_PER_TICK곳씩 → 약 40분에 한 바퀴.
    새 글이 보이면 바로 텔레그램 알림 (트럼프 트루스소셜은 자동 읽기를 막아 둬서, 몇 분 안에 'TRUMP:'로 옮기는 속보 계정으로 봄)
  - 그 밖(검색에서 자주 걸린 계정·벤치마킹): 5분마다 OTHER_PER_TICK곳 → 최근 글 20여 개
  - 검색: 30분에 한 번 경제 키워드 하나('인기' 탭) → 한국어·영어 번갈아, 새 계정 찾기(x_found)
  - 같은 글을 다시 보면 숫자만 새로 고침 (중복 없음)
  → data/free_crawl.json 의 "x" 로 깃허브에 → free_import.py 가 insta.db 의 x_posts 에 넣음 → 분야별 계정 순위
기록: data/threads_watch.db 의 x_* 표 (PC에만)
"""
import csv
import logging
import os
import time
from datetime import datetime, timezone
from urllib.parse import quote

import requests

import account_rank
import logged_browser as lb
from common import ROOT

ACCOUNTS = ROOT / "x_accounts.csv"
VIP_PER_TICK = 2       # 핵심 인물 계정 (x_accounts.csv) — 한 바퀴에 2곳
OTHER_PER_TICK = 1     # 그 밖 계정
VIP_ALERT_H = 3        # 올린 지 이 시간 안의 새 글만 알림 (처음 볼 때 옛 글이 쏟아지지 않게)
SEARCH_EVERY_S = 1800
FOUND_MAX = 60
KEEP_DAYS = 7          # 이만큼 지난 글은 기록에서 지움
EN_WORDS = ["stock market", "nasdaq", "S&P 500", "fed rate", "bitcoin", "inflation", "tariffs", "treasury yields", "earnings"]

log = logging.getLogger("threads_watch")


def init(c):
    c.executescript("""CREATE TABLE IF NOT EXISTS x_live (id TEXT PRIMARY KEY, username TEXT, name TEXT, followers INTEGER, text TEXT,
                         created_at INTEGER, views INTEGER, likes INTEGER, reposts INTEGER, replies INTEGER, quotes INTEGER,
                         bookmarks INTEGER, lang TEXT, is_repost INTEGER, source TEXT, at INTEGER);
                       CREATE TABLE IF NOT EXISTS x_accounts (username TEXT PRIMARY KEY, last_scan INTEGER, followers INTEGER);
                       CREATE TABLE IF NOT EXISTS x_found (username TEXT PRIMARY KEY, hits INTEGER, best_likes INTEGER,
                         keywords TEXT, first_seen INTEGER);""")


def kv(c, k, v=None):
    if v is None:
        r = c.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return r[0] if r else 0
    c.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (k, v))


def vips():
    """핵심 인물 {아이디: (묶음, 메모)} — x_accounts.csv."""
    if not ACCOUNTS.exists():
        return {}
    with open(ACCOUNTS, encoding="utf-8-sig") as f:
        return {r["username"].strip().lstrip("@"): (r.get("group") or "", r.get("memo") or "")
                for r in csv.DictReader(f) if (r.get("username") or "").strip()}


def others(c):
    found = [r[0] for r in c.execute("SELECT username FROM x_found WHERE hits >= 2 OR best_likes >= 1000 "
                                     "ORDER BY best_likes DESC LIMIT ?", (FOUND_MAX,))]
    v = vips()
    return [u for u in dict.fromkeys(found + account_rank.bench_accounts("x")) if u not in v]


def _tweets(o, out):
    """화면이 불러온 JSON 안의 글 덩어리 (rest_id + legacy.full_text)."""
    if isinstance(o, dict):
        if "rest_id" in o and isinstance(o.get("legacy"), dict) and "full_text" in o["legacy"]:
            out.append(o)
        for v in o.values():
            _tweets(v, out)
    elif isinstance(o, list):
        for v in o:
            _tweets(v, out)
    return out


def parse(t):
    L = t["legacy"]
    u = ((t.get("core") or {}).get("user_results") or {}).get("result") or {}
    user = (u.get("core") or {}).get("screen_name") or (u.get("legacy") or {}).get("screen_name")
    if not user:
        return None
    note = (((t.get("note_tweet") or {}).get("note_tweet_results") or {}).get("result") or {}).get("text")   # 긴 글은 여기 전문
    fol = (u.get("legacy") or {}).get("followers_count")
    if fol is None:
        fol = next(iter(lb.find_key(u, "followers", [])), None)
    try:
        created = int(datetime.strptime(L["created_at"], "%a %b %d %H:%M:%S %z %Y").timestamp())
    except (KeyError, ValueError):
        return None
    views = (t.get("views") or {}).get("count")
    return {"id": "x:" + t["rest_id"], "username": user, "name": (u.get("core") or {}).get("name"),
            "followers": fol if isinstance(fol, int) else None, "text": note or L.get("full_text") or "", "created_at": created,
            "views": int(views) if views else None, "likes": L.get("favorite_count"), "reposts": L.get("retweet_count"),
            "replies": L.get("reply_count"), "quotes": L.get("quote_count"), "bookmarks": L.get("bookmark_count"),
            "lang": L.get("lang"), "is_repost": int("retweeted_status_result" in L)}


def save(c, posts, source, now):
    new = 0
    for p in posts:
        new += c.execute("SELECT 1 FROM x_live WHERE id=?", (p["id"],)).fetchone() is None
        c.execute("INSERT INTO x_live VALUES (:id,:username,:name,:followers,:text,:created_at,:views,:likes,:reposts,:replies,"
                  ":quotes,:bookmarks,:lang,:is_repost,:source,:at) ON CONFLICT(id) DO UPDATE SET views=COALESCE(excluded.views, views), "
                  "likes=excluded.likes, reposts=excluded.reposts, replies=excluded.replies, quotes=excluded.quotes, "
                  "bookmarks=excluded.bookmarks, followers=COALESCE(excluded.followers, followers), at=excluded.at",
                  {**p, "source": source, "at": now})
    return new


def visit(url, scrolls=2):
    html, bodies = lb.visit(url, scrolls=scrolls, wait_ms=6000)
    if html is None:
        return None
    posts = [p for p in (parse(t) for t in _tweets(bodies, [])) if p]
    return list({p["id"]: p for p in posts}.values())


def oldest(c, users, n):
    for u in users:
        c.execute("INSERT OR IGNORE INTO x_accounts (username, last_scan) VALUES (?, 0)", (u,))
    return [r[0] for r in c.execute("SELECT username FROM x_accounts WHERE username IN (%s) ORDER BY last_scan LIMIT ?"
                                    % ",".join("?" * len(users)), (*users, n))] if users else []


def scan_accounts(c, now):
    v = vips()
    pick = oldest(c, list(v), VIP_PER_TICK) + oldest(c, others(c), OTHER_PER_TICK)
    new, fresh = 0, []
    for user in pick:
        posts = visit(f"https://x.com/{user}")
        if posts is None:
            break
        mine = [p for p in posts if p["username"].lower() == user.lower()]   # 리포스트 원글 주인 글은 빼고
        fol = next((p["followers"] for p in mine if p["followers"]), None)
        first = c.execute("SELECT last_scan FROM x_accounts WHERE username=?", (user,)).fetchone()[0] == 0
        c.execute("UPDATE x_accounts SET last_scan=?, followers=COALESCE(?, followers) WHERE username=?", (now, fol, user))
        known = {r[0] for r in c.execute("SELECT id FROM x_live WHERE username=?", (user,))}
        if user in v and not first:
            fresh += [p for p in mine if p["id"] not in known and not p["is_repost"] and now - p["created_at"] <= VIP_ALERT_H * 3600]
        new += save(c, mine, "핵심 인물" if user in v else "계정", now)
    c.commit()
    alert(fresh, v)
    return len(pick), new


def alert(posts, v):
    """핵심 인물 새 글 → 텔레그램 (글마다 한 번 — 처음 본 글만 들어옴)."""
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return
    for p in sorted(posts, key=lambda p: p["created_at"])[:5]:
        grp, memo = v.get(p["username"], ("", ""))
        ago = max(1, round((time.time() - p["created_at"]) / 60))
        text = "\n".join([f"🇺🇸 핵심 인물 새 글 · @{p['username']}" + (f" ({memo})" if memo else "") + f" · {ago}분 전",
                          f"조회 {p['views'] or '-'} · 좋아요 {p['likes'] or 0}", "", p["text"][:700], "",
                          f"https://x.com/{p['username']}/status/{p['id'].split(':', 1)[1]}"])
        try:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=20,
                          json={"chat_id": chat, "text": text, "disable_web_page_preview": True})
        except requests.RequestException as e:
            log.info("X 알림 실패: %s", e)


def search_words():
    ko = [w for ws in account_rank.CATS.values() for w in ws if any("가" <= ch <= "힣" for ch in w) and len(w) >= 2]
    return [w for pair in zip(ko, EN_WORDS * (len(ko) // len(EN_WORDS) + 1)) for w in pair]   # 한국어·영어 번갈아


def discover(c, now):
    if now - kv(c, "x_last_search") < SEARCH_EVERY_S:
        return None, 0
    words = search_words()
    i = kv(c, "x_search_i") % len(words)
    kv(c, "x_search_i", i + 1)
    kv(c, "x_last_search", now)
    word = words[i]
    posts = visit(f"https://x.com/search?q={quote(word + ' -filter:replies')}&src=typed_query&f=top")
    if posts is None:
        return word, 0
    users = {}
    for p in posts:
        if not p["is_repost"]:
            users[p["username"]] = max(users.get(p["username"], 0), p["likes"] or 0)
    for u, likes in users.items():
        c.execute("INSERT INTO x_found VALUES (?,1,?,?,?) ON CONFLICT(username) DO UPDATE SET hits=hits+1, "
                  "best_likes=MAX(best_likes, excluded.best_likes), "
                  "keywords=CASE WHEN instr(keywords, excluded.keywords) > 0 THEN keywords ELSE keywords || ', ' || excluded.keywords END",
                  (u, likes, word, now))
    save(c, [p for p in posts if not p["is_repost"]], "검색", now)
    c.commit()
    return word, len(users)


def export(c, now):
    """free_crawl.json 의 "x" (최근 7일)."""
    c.execute("DELETE FROM x_live WHERE created_at < ?", (now - KEEP_DAYS * 86400,))
    cols = ["id", "username", "name", "followers", "text", "created_at", "views", "likes", "reposts", "replies", "quotes",
            "bookmarks", "lang", "is_repost", "source", "at"]
    return [dict(zip(cols, r)) for r in c.execute(f"SELECT {', '.join(cols)} FROM x_live")]


def tick(c):
    """threads_watch 한 바퀴 안에서 부른다. X 로그인이 없으면 아무것도 안 함."""
    if not lb.ready("x"):
        return
    now = int(time.time())
    start = time.time()
    init(c)
    na, new = scan_accounts(c, now)
    word, found = discover(c, now)
    log.info("X 계정 %d곳(새 글 %d)%s · %d초", na, new, f" · 검색 '{word}' 계정 {found}곳" if word else "", time.time() - start)


def main():
    import sys
    from threads_watch import db
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%m/%d %H:%M")
    c = db()
    try:
        tick(c)
    finally:
        lb.close()


if __name__ == "__main__":
    main()
