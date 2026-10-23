"""Apify 쓰레드 수집기(themineworks/threads-scraper)로 쓰레드 공개 글을 좋아요·답글·리포스트·인용 수와 함께 모은다.

    python apify_threads.py           # APIFY_TOKEN 필요 (GitHub 비밀값 / .env)
    python apify_threads.py --dry-run # 호출 없이 무엇을 수집할지만 출력

모으는 것:
  - 경제 키워드 검색 인기 글 (THREADS_KEYWORDS)
  - 지정한 쓰레드 계정의 최근 글 (threads_accounts.csv, 없으면 기본 목록)
  - 팀이 폼에 넣은 링크 → 본문·숫자를 자동으로 채움
메타 공식 API가 아니라 공개 페이지를 읽는 외부 서비스다. 로그인·계정 연결은 하지 않는다.
비용: 글 1,000개당 약 1.2~2달러 + 실행당 0.002달러.
"""
import argparse
import csv
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

from common import ROOT, connect, load_env
from topics import topics_of

ACTOR = "themineworks~threads-scraper"
API = f"https://api.apify.com/v2/acts/{ACTOR}/run-sync-get-dataset-items"
THREADS_KEYWORDS = ["미국주식", "주식", "코인", "비트코인", "재테크", "금리", "부동산", "ETF", "엔비디아", "삼성전자"]
PER_KEYWORD = 20
DEFAULT_ACCOUNTS = ["bullstory1", "heoyoopapa", "snowball_economy", "hibi_heebee", "syukaworld", "weolbu_official",
                    "buiknam", "newneek.official", "hankyungmedia_official", "ekke.now"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS threads_apify (
    post_id TEXT PRIMARY KEY, code TEXT, url TEXT, username TEXT, text TEXT, posted_at TEXT,
    likes INTEGER, replies INTEGER, reposts INTEGER, quotes INTEGER, media_type TEXT, is_reply INTEGER,
    source TEXT, topics TEXT, scraped_at TEXT
);
"""


def run_actor(token, payload):
    req = urllib.request.Request(f"{API}?token={token}&timeout=280", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return [i for i in json.load(r) if i.get("_type") != "info"]
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
    return [r[0] for r in conn.execute("SELECT link FROM threads_saved WHERE likes IS NULL OR text = '' LIMIT 30")]


def save(conn, items, source, now):
    n = 0
    for p in items:
        pid = str(p.get("post_id") or p.get("code") or "")
        if not pid:
            continue
        text = p.get("text") or ""
        conn.execute(
            "INSERT INTO threads_apify VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(post_id) DO UPDATE SET "
            "likes=excluded.likes, replies=excluded.replies, reposts=excluded.reposts, quotes=excluded.quotes, "
            "scraped_at=excluded.scraped_at, source=CASE WHEN instr(threads_apify.source, excluded.source) > 0 "
            "THEN threads_apify.source ELSE threads_apify.source || ', ' || excluded.source END",
            (pid, p.get("code"), p.get("url"), p.get("username"), text, p.get("posted_at"), p.get("like_count"),
             p.get("reply_count"), p.get("repost_count"), p.get("quote_count"), p.get("media_type"),
             int(bool(p.get("is_reply"))), source, ", ".join(t for t in topics_of(text) if t != "기타"), now))
        n += 1
    return n


def fill_team_links(conn, items):
    """팀이 폼에 넣은 링크에 Apify가 가져온 본문·숫자를 채운다 (링크의 글 코드로 맞춤)."""
    by_code = {str(p.get("code")): p for p in items if p.get("code")}
    filled = 0
    for link, in conn.execute("SELECT link FROM threads_saved").fetchall():
        m = re.search(r"/(?:post|t)/([\w-]+)", link or "")
        p = by_code.get(m.group(1)) if m else None
        if not p:
            continue
        text = p.get("text") or ""
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
    conn.executescript(SCHEMA)
    links = team_links(conn)
    users = accounts()
    plan = f"키워드 {len(THREADS_KEYWORDS)}개 × {PER_KEYWORD}개, 계정 {len(users)}곳, 팀 링크 {len(links)}개"
    if args.dry_run:
        print("수집 계획:", plan)
        return
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        print("APIFY_TOKEN 이 없어 쓰레드 자동 수집을 건너뛰어요 (THREADS_APIFY.md 참고).")
        return
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    total = 0
    for q in THREADS_KEYWORDS:
        items = run_actor(token, {"mode": "search", "searchQuery": q, "resultType": "top", "maxPosts": PER_KEYWORD,
                                  "includeReplies": False, "includeReposts": False})
        total += save(conn, items, f"검색:{q}", now)
        print(f"✅ 검색 '{q}': {len(items)}개")
    items = run_actor(token, {"mode": "profile", "profileUsernames": users, "maxPosts": len(users) * 6,
                              "includeReplies": False, "includeReposts": False})
    total += save(conn, items, "계정", now)
    print(f"✅ 계정 {len(users)}곳: {len(items)}개")
    if links:
        items = run_actor(token, {"mode": "post", "postUrls": links, "maxPosts": len(links)})
        total += save(conn, items, "팀 링크", now)
        print(f"✅ 팀 링크 {len(links)}개 중 {fill_team_links(conn, items)}개에 본문·숫자 채움")
    conn.commit()
    print(f"완료: 쓰레드 글 {total}개 저장 (예상 비용 약 ${total * 0.002:.2f})")


if __name__ == "__main__":
    sys.exit(main())
