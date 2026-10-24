"""Apify 쓰레드 수집기(futurizerush/meta-threads-scraper)로 쓰레드 공개 글을 **조회수·팔로워 수**와 함께 모은다.

    python apify_threads.py           # APIFY_TOKEN 필요 (GitHub 비밀값 / .env)
    python apify_threads.py --dry-run # 호출 없이 무엇을 수집할지만 출력

모으는 것 (월 약 22달러 안쪽, 1천 건당 2.5달러):
  - 경제 키워드 12개 × 최근 7일 인기 글 15개 (매일)
  - 참고 계정(threads_accounts.csv) 최근 글 5개씩 (이틀에 한 번)
  - 팀이 폼에 넣은 링크 → 본문·숫자·조회수를 자동으로 채움
메타 공식 API가 아니라 공개 페이지를 읽는 외부 서비스다. 로그인·계정 연결은 하지 않는다.
"""
import argparse
import csv
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from common import ROOT, connect, load_env
from topics import topics_of

ACTOR = "futurizerush~meta-threads-scraper"
API = f"https://api.apify.com/v2/acts/{ACTOR}/run-sync-get-dataset-items"
PRICE_PER_1K = 2.5
THREADS_KEYWORDS = ["미국주식", "국내주식", "코인", "비트코인", "금리", "환율", "부동산", "ETF", "엔비디아", "삼성전자", "재테크", "배당"]
PER_KEYWORD = 15
PER_ACCOUNT = 5
RECHECK_MAX = 0   # 링크 모드는 링크당 최소 10건(답글 포함) 과금이라 끔 — 인기 글은 다음 날 검색에 다시 걸리며 조회수가 갱신됨
DEFAULT_ACCOUNTS = ["bullstory1", "heoyoopapa", "snowball_economy", "hibi_heebee", "syukaworld", "weolbu_official",
                    "buiknam", "bstory_economy", "chart_ddorai", "ekke.now"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS threads_apify (
    post_id TEXT PRIMARY KEY, code TEXT, url TEXT, username TEXT, text TEXT, posted_at TEXT,
    likes INTEGER, replies INTEGER, reposts INTEGER, quotes INTEGER, media_type TEXT, is_reply INTEGER,
    source TEXT, topics TEXT, scraped_at TEXT
);
CREATE TABLE IF NOT EXISTS threads_cost (date TEXT PRIMARY KEY, results INTEGER);
"""
NEW_COLS = {"views": "INTEGER", "view_status": "TEXT", "shares": "INTEGER", "followers": "INTEGER", "display_name": "TEXT",
            "bio": "TEXT", "verified": "INTEGER", "has_media": "INTEGER", "is_quote": "INTEGER", "views_at": "TEXT"}


def migrate(conn):
    conn.executescript(SCHEMA)
    have = {r[1] for r in conn.execute("PRAGMA table_info(threads_apify)")}
    for col, typ in NEW_COLS.items():
        if col not in have:
            conn.execute(f"ALTER TABLE threads_apify ADD COLUMN {col} {typ}")


def run_actor(token, payload):
    req = urllib.request.Request(f"{API}?token={token}&timeout=280", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return [i for i in json.load(r) if i.get("post_code") or i.get("post_url")]
    except urllib.error.HTTPError as e:
        print(f"⚠️ Apify 오류({e.code}): {e.read()[:200].decode('utf-8', 'ignore')}")
    except Exception as e:  # 시간 초과 등은 그 묶음만 건너뛴다
        print(f"⚠️ Apify 호출 실패: {e}")
    return []


def accounts():
    path = ROOT / "threads_accounts.csv"
    if path.exists():
        with open(path, encoding="utf-8-sig", newline="") as f:
            names = [r["username"].strip().lstrip("@") for r in csv.DictReader(f) if (r.get("username") or "").strip()]
        if names:
            return names
    return DEFAULT_ACCOUNTS


def team_links(conn):
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "threads_saved" not in tables:
        return []
    # 숫자나 본문이 비어 있는 팀 링크만 채운다 (이미 채운 건 다시 사지 않음)
    return [r[0] for r in conn.execute("SELECT link FROM threads_saved WHERE likes IS NULL OR text = '' LIMIT 10")]


def recheck_links(conn, now):
    """조회수가 아직 없거나, 하루 안 된 글이라 조회수가 덜 쌓인 상위 글을 다시 읽는다."""
    day_ago = (now - timedelta(days=1)).isoformat()
    week_ago = (now - timedelta(days=7)).isoformat()
    rows = conn.execute(
        "SELECT url FROM threads_apify WHERE posted_at >= ? AND url != '' AND (views_at IS NULL OR views_at <= posted_at "
        "OR julianday(views_at) - julianday(posted_at) < 1) AND scraped_at <= ? "
        "ORDER BY (COALESCE(likes,0) + 2*COALESCE(replies,0) + 3*COALESCE(reposts,0)) * 1.0 / MAX(COALESCE(followers,0), 300) DESC LIMIT ?",
        (week_ago, day_ago, RECHECK_MAX)).fetchall()
    return [r[0] for r in rows]


def save(conn, items, source, now):
    n = 0
    for p in items:
        pid = str(p.get("post_code") or "")
        if not pid:
            continue
        text = p.get("text_content") or p.get("text") or ""
        views = p.get("view_count") if p.get("view_count_status") == "available" else None
        conn.execute(
            "INSERT INTO threads_apify (post_id, code, url, username, text, posted_at, likes, replies, reposts, quotes, media_type, "
            "is_reply, source, topics, scraped_at, views, view_status, shares, followers, display_name, bio, verified, has_media, "
            "is_quote, views_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(post_id) DO UPDATE SET "
            "likes=excluded.likes, replies=excluded.replies, reposts=excluded.reposts, quotes=excluded.quotes, "
            "text=CASE WHEN excluded.text != '' THEN excluded.text ELSE text END, "
            "topics=CASE WHEN excluded.text != '' THEN excluded.topics ELSE topics END, "
            "shares=COALESCE(excluded.shares, shares), followers=COALESCE(excluded.followers, followers), scraped_at=excluded.scraped_at, "
            "views=COALESCE(excluded.views, views), view_status=excluded.view_status, "
            "views_at=CASE WHEN excluded.views IS NOT NULL THEN excluded.views_at ELSE views_at END, "
            "source=CASE WHEN instr(threads_apify.source, excluded.source) > 0 "
            "THEN threads_apify.source ELSE threads_apify.source || ', ' || excluded.source END",
            (pid, pid, p.get("post_url") or "", p.get("username"), text, p.get("created_at"), p.get("like_count"),
             p.get("reply_count"), p.get("repost_count"), p.get("quote_count"), p.get("media_type"),
             int(bool(p.get("is_reply"))), source, ", ".join(t for t in topics_of(text) if t != "기타"), now,
             views, p.get("view_count_status"), p.get("share_count"), p.get("followers_count"), p.get("display_name"),
             (p.get("bio") or "")[:300], int(bool(p.get("is_verified"))), int(bool(p.get("has_media"))),
             int(bool(p.get("is_quote_post"))), now if views is not None else None))
        n += 1
    return n


def fill_team_links(conn, items):
    """팀이 폼에 넣은 링크에 Apify가 가져온 본문·숫자를 채운다 (링크의 글 코드로 맞춤)."""
    by_code = {str(p.get("post_code")): p for p in items if p.get("post_code")}
    filled = 0
    for link, in conn.execute("SELECT link FROM threads_saved").fetchall():
        m = re.search(r"/(?:post|t)/([\w-]+)", link or "")
        p = by_code.get(m.group(1)) if m else None
        if not p:
            continue
        text = p.get("text_content") or p.get("text") or ""
        conn.execute("UPDATE threads_saved SET likes=?, replies=?, reposts=?, author=COALESCE(NULLIF(author,''), ?), "
                     "text=CASE WHEN text='' THEN ? ELSE text END, "
                     "topics=CASE WHEN COALESCE(topics,'')='' THEN ? ELSE topics END WHERE link=?",
                     (p.get("like_count"), p.get("reply_count"), p.get("repost_count"), p.get("username"),
                      text, ", ".join(t for t in topics_of(text) if t != "기타"), link))
        filled += 1
    return filled


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    load_env()
    conn = connect()
    migrate(conn)
    now_dt = datetime.now(timezone.utc)
    links = team_links(conn)
    recheck = recheck_links(conn, now_dt)
    users = accounts()
    account_day = now_dt.toordinal() % 2 == 0   # 참고 계정은 이틀에 한 번
    plan = (f"키워드 {len(THREADS_KEYWORDS)}개 × {PER_KEYWORD}개, 계정 {len(users)}곳 × {PER_ACCOUNT}개"
            f"{'' if account_day else ' (오늘은 쉼)'}, 다시 읽기 {len(recheck)}개, 팀 링크 {len(links)}개")
    if args.dry_run:
        print("수집 계획:", plan)
        return
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        print("APIFY_TOKEN 이 없어 쓰레드 자동 수집을 건너뛰어요 (THREADS_APIFY.md 참고).")
        return
    now = now_dt.isoformat(timespec="seconds")
    total = 0
    for q in THREADS_KEYWORDS:
        items = run_actor(token, {"mode": "search", "keywords": [q], "search_filter": "top", "start_date": "7 days",
                                  "max_posts": PER_KEYWORD})
        total += save(conn, items, f"검색:{q}", now)
        print(f"✅ 검색 '{q}': {len(items)}개")
    if account_day:
        for i in range(0, len(users), 20):
            items = run_actor(token, {"mode": "user", "usernames": users[i:i + 20], "max_posts": PER_ACCOUNT})
            total += save(conn, items, "계정", now)
            print(f"✅ 계정 {len(users[i:i + 20])}곳: {len(items)}개")
    for i in range(0, len(recheck), 20):
        items = run_actor(token, {"mode": "post_link", "post_links": recheck[i:i + 20], "max_posts": 10})
        total += save(conn, items, "다시 읽기", now)
        print(f"✅ 조회수 다시 읽기 {len(recheck[i:i + 20])}개: {len(items)}개")
    for i in range(0, len(links), 20):
        items = run_actor(token, {"mode": "post_link", "post_links": links[i:i + 20], "max_posts": 10})
        total += save(conn, items, "팀 링크", now)
        print(f"✅ 팀 링크 {len(links[i:i + 20])}개 중 {fill_team_links(conn, items)}개에 본문·숫자 채움")
    today = now_dt.date().isoformat()
    conn.execute("INSERT INTO threads_cost VALUES (?, ?) ON CONFLICT(date) DO UPDATE SET results = results + excluded.results",
                 (today, total))
    conn.commit()
    print(f"완료: 쓰레드 글 {total}개 저장 (예상 비용 약 ${total * PRICE_PER_1K / 1000:.2f})")


if __name__ == "__main__":
    sys.exit(main())
