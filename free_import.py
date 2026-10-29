"""무료 크롤러(내 PC의 threads_watch.py)가 올린 data/free_crawl.json 을 매일 분석 표(data/insta.db)에 넣는다.

    python free_import.py

유료 수집(apify_instagram.py · apify_threads.py)을 대신한다 — 2026-10-29 대표 결정으로 Apify 끔.
  - 인스타: posts(같은 글은 주소로 찾아 숫자만 갱신), accounts·account_snapshots(팔로워)
  - 쓰레드: threads_apify (source '무료크롤러')
릴스 조회수는 공개 '퍼가기' 화면 값이라 예전 Apify 재생수와 셈법이 다를 수 있다.
"""
import json
import sys
from datetime import datetime, timezone

from common import ROOT, connect
from topics import topics_of

FREE = ROOT / "data" / "free_crawl.json"
KIND = {"릴스": ("VIDEO", "REELS"), "카드뉴스": ("CAROUSEL_ALBUM", "FEED"), "사진": ("IMAGE", "FEED")}


def iso(ts, fmt="%Y-%m-%dT%H:%M:%S+0000"):
    return datetime.fromtimestamp(ts, timezone.utc).strftime(fmt)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if not FREE.exists():
        print("무료 크롤러 파일이 없어요 (PC 크롤러가 아직 안 올림)")
        return
    d = json.loads(FREE.read_text(encoding="utf-8"))
    age_h = (datetime.now(timezone.utc).timestamp() - d["updated"]) / 3600
    conn = connect()
    if "slides" not in {r[1] for r in conn.execute("PRAGMA table_info(posts)")}:
        conn.execute("ALTER TABLE posts ADD COLUMN slides INTEGER")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for a in d.get("ig_accounts", []):
        conn.execute("UPDATE accounts SET followers=?, last_collected=? WHERE username=?", (a["followers"], iso(d["updated"]), a["username"]))
        conn.execute("INSERT OR REPLACE INTO account_snapshots VALUES (?,?,?,(SELECT media_count FROM accounts WHERE username=?))",
                     (a["username"], today, a["followers"], a["username"]))
    ig = 0
    for p in d.get("instagram", []):
        mtype, product = KIND.get(p.get("kind"), ("IMAGE", "FEED"))
        old = conn.execute("SELECT id FROM posts WHERE permalink LIKE ?", (f"%/{p['code']}/%",)).fetchone()
        if old:
            conn.execute("UPDATE posts SET likes=COALESCE(?, likes), comments=COALESCE(?, comments), views=COALESCE(?, views), "
                         "collected_at=?, slides=COALESCE(?, slides) WHERE id=?",
                         (p["likes"], p["comments"], p["views"], iso(p["at"], "%Y-%m-%dT%H:%M:%S+00:00"), p.get("slides"), old[0]))
        else:
            conn.execute("INSERT INTO posts (id, username, caption, media_type, product_type, timestamp, permalink, likes, comments, "
                         "views, collected_at, slides) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (p["code"], p["username"], p["text"], mtype, product, iso(p["taken_at"]),
                          f"https://www.instagram.com/{'reel' if product == 'REELS' else 'p'}/{p['code']}/",
                          p["likes"], p["comments"], p["views"], iso(p["at"], "%Y-%m-%dT%H:%M:%S+00:00"), p.get("slides")))
        ig += 1
    th = 0
    for p in d.get("threads", []):
        at = iso(p["at"], "%Y-%m-%dT%H:%M:%S+00:00")
        conn.execute(
            "INSERT INTO threads_apify (post_id, code, url, username, text, posted_at, likes, replies, reposts, is_reply, source, topics, "
            "scraped_at, views, view_status, followers, views_at) VALUES (?,?,?,?,?,?,?,?,?,0,'무료크롤러',?,?,?,?,?,?) "
            "ON CONFLICT(post_id) DO UPDATE SET likes=COALESCE(excluded.likes, likes), replies=COALESCE(excluded.replies, replies), "
            "reposts=COALESCE(excluded.reposts, reposts), views=COALESCE(excluded.views, views), "
            "view_status=COALESCE(excluded.view_status, view_status), followers=COALESCE(excluded.followers, followers), "
            "scraped_at=excluded.scraped_at, views_at=CASE WHEN excluded.views IS NOT NULL THEN excluded.views_at ELSE views_at END, "
            "text=CASE WHEN text IS NULL OR text = '' THEN excluded.text ELSE text END, "
            "source=CASE WHEN instr(threads_apify.source, '무료크롤러') > 0 THEN threads_apify.source "
            "ELSE threads_apify.source || ', 무료크롤러' END",
            (p["code"], p["code"], p["url"], p["username"], p["text"], iso(p["taken_at"], "%Y-%m-%dT%H:%M:%S+00:00"), p["likes"],
             p["replies"], p["reposts"], ", ".join(t for t in topics_of(p["text"]) if t != "기타"), at, p["views"],
             "available" if p["views"] is not None else None, p["followers"], at))
        th += 1
    conn.commit()
    print(f"무료 크롤러 → 인스타 글 {ig}개 · 쓰레드 글 {th}개 · 인스타 계정 팔로워 {len(d.get('ig_accounts', []))}곳"
          f" (PC가 {age_h:.1f}시간 전에 올림{' — PC 크롤러가 꺼져 있는지 확인' if age_h > 6 else ''})")


if __name__ == "__main__":
    main()
