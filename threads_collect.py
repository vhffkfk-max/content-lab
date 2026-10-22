"""쓰레드 공식 키워드 검색으로 경제 키워드의 공개 글을 모은다.

    python threads_collect.py
threads_keyword_search 권한 심사를 통과하기 전에는 연결한 내 계정의 글만 검색된다 (메타 정책).
개인정보처리방침에 적은 대로 90일이 지난 글은 매번 지운다.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from common import connect, load_env
from topics import topics_of

API = "https://graph.threads.com/v1.0"
FIELDS = "id,text,media_type,permalink,timestamp,username,has_replies,is_quote_post,is_reply"
KEYWORDS = ["미국주식", "국내주식", "주식", "코인", "비트코인", "재테크", "경제", "금리", "환율",
            "부동산", "ETF", "배당", "엔비디아", "테슬라", "삼성전자"]
RETENTION_DAYS = 90

SCHEMA = """
CREATE TABLE IF NOT EXISTS threads_posts (
    id TEXT PRIMARY KEY, keyword TEXT, search_type TEXT, username TEXT, text TEXT, media_type TEXT,
    permalink TEXT, timestamp TEXT, is_reply INTEGER, topics TEXT, collected_at TEXT
);
"""


def search(token, q, search_type):
    params = {"q": q, "search_type": search_type, "limit": 50, "fields": FIELDS, "access_token": token}
    try:
        with urllib.request.urlopen(f"{API}/keyword_search?{urllib.parse.urlencode(params)}", timeout=40) as r:
            return json.load(r).get("data", [])
    except urllib.error.HTTPError as e:
        body = json.loads(e.read() or b"{}")
        print(f"⚠️  '{q}' 건너뜀: {body.get('error', {}).get('message') or body.get('error_message') or e}")
        return []
    except (TimeoutError, urllib.error.URLError) as e:
        print(f"⚠️  '{q}' 건너뜀: 응답 지연 ({e})")
        return []


def main():
    load_env()
    token = os.environ.get("THREADS_ACCESS_TOKEN")
    if not token:
        print("THREADS_ACCESS_TOKEN 이 없어 쓰레드 수집을 건너뛰어요 (THREADS_SETUP.md 참고).")
        return
    conn = connect()
    conn.executescript(SCHEMA)
    now = datetime.now(timezone.utc)
    stamp = now.isoformat(timespec="seconds")
    total, authors = 0, set()
    for q in KEYWORDS:
        for st in ("TOP", "RECENT"):
            for p in search(token, q, st):
                conn.execute(
                    "INSERT INTO threads_posts VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                    "text=excluded.text, collected_at=excluded.collected_at",
                    (p["id"], q, st, p.get("username"), p.get("text") or "", p.get("media_type"), p.get("permalink"),
                     p.get("timestamp"), int(bool(p.get("is_reply"))),
                     ", ".join(t for t in topics_of(p.get("text")) if t != "기타"), stamp))
                total += 1
                authors.add(p.get("username"))
            time.sleep(1)
    cutoff = (now - timedelta(days=RETENTION_DAYS)).isoformat(timespec="seconds")
    removed = conn.execute("DELETE FROM threads_posts WHERE collected_at < ?", (cutoff,)).rowcount
    conn.commit()
    note = " (아직 심사 전이라 내 계정 글만 검색돼요)" if len(authors - {None}) <= 1 else ""
    print(f"✅ 쓰레드 글 {total}건 · 작성자 {len(authors - {None})}명{note} · 90일 지난 글 {removed}건 정리")


if __name__ == "__main__":
    sys.exit(main())
