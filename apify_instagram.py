"""Apify 인스타 수집기(apify/instagram-scraper)로 참고 계정의 최근 게시물을 **릴스 조회수**와 함께 모은다.

    python apify_instagram.py            # APIFY_TOKEN 필요, accounts.csv 전체
    python apify_instagram.py --dry-run  # 무엇을 수집할지만 출력
    python apify_instagram.py --only syukaworld,bullstory1

메타 공식 API(business_discovery)는 남의 게시물 조회수를 주지 않고, 많이 부르면 계정이 막힐 수 있어서
참고 계정 수집은 이걸로 한다. 결과는 collect.py 와 같은 표(accounts, account_snapshots, posts)에 저장 → 분석은 그대로.
  - 조회수는 릴스·영상만 있다 (사진·캐러셀은 인스타가 조회수를 공개하지 않음)
  - 좋아요를 숨긴 게시물은 좋아요가 비어 있다 (분석은 댓글로 비교)
비용: 게시물 1천 개당 약 2.3~2.7달러 + 프로필 1개당 1건. 계정 48개 × 8개 = 하루 약 430건 → 월 30달러 안팎.
"""
import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

from common import ROOT, connect, load_env

ACTOR = "apify~instagram-scraper"
API = f"https://api.apify.com/v2/acts/{ACTOR}/run-sync-get-dataset-items"
PER_ACCOUNT = 8      # 계정당 최근 게시물 수 (옛 글은 DB에 쌓여 있어서 매일 최근 것만 갱신)
BATCH = 12           # 한 번에 넘길 계정 수
TYPE = {"Image": "IMAGE", "Video": "VIDEO", "Sidecar": "CAROUSEL_ALBUM"}


def run_actor(token, payload):
    req = urllib.request.Request(f"{API}?token={token}&timeout=290", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        print(f"⚠️ Apify 오류({e.code}): {e.read()[:200].decode('utf-8', 'ignore')}")
    except Exception as e:
        print(f"⚠️ Apify 호출 실패: {e}")
    return []


def graph_ts(ts):
    """'2026-10-26T01:56:45.000Z' → '2026-10-26T01:56:45+0000' (공식 API와 같은 모양으로 저장)."""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000")
    except (AttributeError, ValueError):
        return None


def save_profile(conn, row, prof, now):
    username = prof["username"]
    conn.execute(
        """INSERT INTO accounts VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(username) DO UPDATE SET region=excluded.region, category=excluded.category,
             name=excluded.name, biography=excluded.biography, followers=excluded.followers,
             media_count=COALESCE(excluded.media_count, media_count), last_collected=excluded.last_collected""",
        (username, row.get("region", ""), row.get("category", ""), prof.get("fullName"), prof.get("biography"),
         prof.get("followersCount"), prof.get("postsCount"), now))
    conn.execute("INSERT OR REPLACE INTO account_snapshots VALUES (?,?,?,?)",
                 (username, now[:10], prof.get("followersCount"), prof.get("postsCount")))


def save_post(conn, p, now):
    code = p.get("shortCode")
    if not code or not p.get("ownerUsername"):
        return False
    likes = p.get("likesCount")
    views = p.get("videoPlayCount") or p.get("videoViewCount")
    product = "REELS" if p.get("productType") == "clips" else "FEED"
    # 예전 공식 API로 모은 같은 게시물(다른 id)은 지우고 하나만 남긴다
    conn.execute("DELETE FROM posts WHERE permalink LIKE ? AND id != ?", (f"%/{code}/%", str(p.get("id"))))
    conn.execute("INSERT OR REPLACE INTO posts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 (str(p.get("id")), p["ownerUsername"], p.get("caption") or "", TYPE.get(p.get("type"), p.get("type")), product,
                  graph_ts(p.get("timestamp")), p.get("url") or f"https://www.instagram.com/p/{code}/",
                  likes if (likes is not None and likes >= 0) else None, p.get("commentsCount"), views, now))
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", help="쉼표로 구분한 아이디만")
    args = ap.parse_args()
    load_env()
    with open(ROOT / "accounts.csv", encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if (r.get("username") or "").strip()]
    for r in rows:
        r["username"] = r["username"].strip().lstrip("@")
    if args.only:
        wanted = {u.strip().lstrip("@").lower() for u in args.only.split(",")}
        rows = [r for r in rows if r["username"].lower() in wanted]
    print(f"수집 계획: 계정 {len(rows)}곳 × 최근 {PER_ACCOUNT}개 + 프로필 {len(rows)}개 (약 {len(rows) * (PER_ACCOUNT + 1)}건)")
    if args.dry_run:
        return
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        print("APIFY_TOKEN 이 없어 인스타 수집을 건너뛰어요.")
        return
    conn = connect()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    by_name = {r["username"].lower(): r for r in rows}
    profiles = posts = 0
    for i in range(0, len(rows), BATCH):
        urls = [f"https://www.instagram.com/{r['username']}/" for r in rows[i:i + BATCH]]
        for prof in run_actor(token, {"directUrls": urls, "resultsType": "details", "resultsLimit": 1}):
            row = by_name.get((prof.get("username") or "").lower())
            if row and prof.get("followersCount") is not None:
                save_profile(conn, row, prof, now)
                profiles += 1
        got = run_actor(token, {"directUrls": urls, "resultsType": "posts", "resultsLimit": PER_ACCOUNT, "skipPinnedPosts": True})
        posts += sum(save_post(conn, p, now) for p in got if (p.get("ownerUsername") or "").lower() in by_name)
        conn.commit()
        print(f"✅ 계정 {i + 1}~{i + len(urls)}: 게시물 {len(got)}개")
    cur = conn.execute("SELECT COUNT(*) FROM posts WHERE collected_at = ? AND views IS NOT NULL", (now,)).fetchone()[0]
    print(f"완료: 프로필 {profiles}개, 게시물 {posts}개 (조회수 있는 릴스·영상 {cur}개) · 예상 비용 약 ${(profiles + posts) * 2.5 / 1000:.2f}")


if __name__ == "__main__":
    sys.exit(main())
