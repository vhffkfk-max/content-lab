"""X(트위터)·트루스소셜의 경제에 영향 주는 글을 **조회수**와 함께 모은다 (Apify).

    python x_collect.py            # APIFY_TOKEN 필요
    python x_collect.py --dry-run  # 무엇을 수집할지만 출력

모으는 것 (매일, 최근 하루):
  - x_accounts.csv 계정들 (정책·인물·시장 속보·분석·코인 묶음별 검색) — 답글은 빼고
  - 경제 키워드로 크게 퍼진 글 (좋아요 3천 이상, 영어)
  - 트럼프 트루스소셜 (트럼프는 X보다 트루스소셜에 더 많이 씀, 조회수는 공개 안 됨)
비용: X 1천 개당 0.4달러(검색 1번당 최소 50개 과금), 트루스소셜 1천 개당 약 1~5달러 → 하루 약 0.2달러, 월 6달러 안팎.
"""
import argparse
import csv
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from common import ROOT, connect, load_env

X_ACTOR = "apidojo~tweet-scraper"
TRUTH_ACTOR = "tri_angle~truth-scraper"
GROUP_RULES = {   # 묶음별 검색 조건과 최대 개수
    "정책": ("", 60), "인물": (" min_faves:3000", 40), "시장 속보": (" min_faves:200", 100), "분석": ("", 40), "코인": (" min_faves:300", 40)}
VIRAL_QUERY = ('("stock market" OR "S&P 500" OR Nasdaq OR "rate cut" OR "interest rates" OR tariffs OR inflation OR recession '
               'OR bitcoin OR "Treasury yields" OR "jobs report") min_faves:3000 lang:en -filter:replies')
TRUTH_MAX = 20

SCHEMA = """
CREATE TABLE IF NOT EXISTS x_posts (
    id TEXT PRIMARY KEY, platform TEXT, username TEXT, name TEXT, followers INTEGER, grp TEXT, text TEXT, created_at TEXT,
    views INTEGER, likes INTEGER, reposts INTEGER, replies INTEGER, quotes INTEGER, bookmarks INTEGER, url TEXT, lang TEXT,
    is_repost INTEGER, source TEXT, collected_at TEXT
);
CREATE TABLE IF NOT EXISTS x_cost (date TEXT PRIMARY KEY, x_results INTEGER, truth_results INTEGER);
"""


def run_actor(token, actor, payload):
    url = f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items?token={token}&timeout=280"
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        print(f"⚠️ Apify 오류({e.code}): {e.read()[:200].decode('utf-8', 'ignore')}")
    except Exception as e:
        print(f"⚠️ Apify 호출 실패: {e}")
    return []


def accounts():
    with open(ROOT / "x_accounts.csv", encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f) if (r.get("username") or "").strip()]


def x_time(s):
    try:
        return datetime.strptime(s, "%a %b %d %H:%M:%S %z %Y").astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


def save_x(conn, items, groups, source, now):
    n = 0
    for t in items:
        if not t.get("id") or t.get("type") not in (None, "tweet"):
            continue
        a = t.get("author") or {}
        user = a.get("userName") or ""
        text = t.get("fullText") or t.get("text") or ""
        card = t.get("card") or {}
        # 링크만 있는 글(트럼프가 자주 씀)은 링크 미리보기 제목·설명이나 영상 여부를 붙여 무슨 내용인지 알 수 있게
        extra = " / ".join(x for x in [card.get("title"), card.get("description")] if x) if isinstance(card, dict) else ""
        if t.get("videos") or (t.get("extendedEntities") or {}).get("media"):
            kinds = {m.get("type") for m in (t.get("extendedEntities") or {}).get("media", [])}
            extra = (extra + " / " if extra else "") + ("[영상 첨부]" if "video" in kinds or t.get("videos") else "[이미지 첨부]")
        if extra:
            text = f"{text}\n[링크·첨부: {extra}]"
        conn.execute(
            "INSERT INTO x_posts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "views=excluded.views, likes=excluded.likes, reposts=excluded.reposts, replies=excluded.replies, quotes=excluded.quotes, "
            "bookmarks=excluded.bookmarks, followers=excluded.followers, collected_at=excluded.collected_at",
            ("x:" + str(t["id"]), "X", user, a.get("name"), a.get("followers"), groups.get(user.lower(), "화제"),
             text, x_time(t.get("createdAt")), t.get("viewCount"), t.get("likeCount"),
             t.get("retweetCount"), t.get("replyCount"), t.get("quoteCount"), t.get("bookmarkCount"),
             t.get("url") or t.get("twitterUrl"), t.get("lang"), int(bool(t.get("isRetweet"))), source, now))
        n += 1
    return n


def clean_html(s):
    s = re.sub(r"<br\s*/?>|</p>", "\n", s or "")
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def save_truth(conn, items, now):
    n = 0
    for p in items:
        if not p.get("id") or "content" not in p:
            continue
        text = clean_html(p.get("content"))
        if not text and p.get("reblog"):
            text = "[리트루스] " + clean_html((p.get("reblog") or {}).get("content"))
        conn.execute(
            "INSERT INTO x_posts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "likes=excluded.likes, reposts=excluded.reposts, replies=excluded.replies, collected_at=excluded.collected_at",
            ("truth:" + str(p["id"]), "트루스소셜", p.get("username") or "realDonaldTrump", "Donald J. Trump", None, "정책", text,
             (p.get("createdAt") or "").replace("Z", "+00:00") or None, None, p.get("favouritesCount"), p.get("reblogsCount"),
             p.get("repliesCount"), None, None, p.get("url"), p.get("language"), int(bool(p.get("reblog"))), "트루스소셜", now))
        n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    load_env()
    accs = accounts()
    by_group = defaultdict(list)
    for a in accs:
        by_group[a["group"]].append(a["username"].strip().lstrip("@"))
    groups = {a["username"].strip().lstrip("@").lower(): a["group"] for a in accs}
    since = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    queries = [(g, f"({' OR '.join('from:' + u for u in us)}) -filter:replies{GROUP_RULES.get(g, ('', 40))[0]} since:{since}",
                GROUP_RULES.get(g, ("", 40))[1]) for g, us in by_group.items()]
    print("수집 계획:", ", ".join(f"{g} {n}개" for g, _, n in queries), f", 키워드 화제 60개, 트루스소셜 {TRUTH_MAX}개")
    if args.dry_run:
        for q in queries:
            print("  ", q[1])
        return
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        print("APIFY_TOKEN 이 없어 X 수집을 건너뛰어요.")
        return
    conn = connect()
    conn.executescript(SCHEMA)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    xn = 0
    for g, q, n in queries:
        items = run_actor(token, X_ACTOR, {"searchTerms": [q], "sort": "Latest", "maxItems": n})
        got = save_x(conn, items, groups, f"계정:{g}", now)
        xn += max(got, 50)
        print(f"✅ X {g}: {got}개")
    items = run_actor(token, X_ACTOR, {"searchTerms": [f"{VIRAL_QUERY} since:{since}"], "sort": "Top", "maxItems": 60})
    got = save_x(conn, items, groups, "키워드 화제", now)
    xn += max(got, 50)
    print(f"✅ X 경제 키워드 화제: {got}개")
    items = run_actor(token, TRUTH_ACTOR, {"profiles": ["realDonaldTrump"], "resultsType": "posts", "maxPostsAndReplies": TRUTH_MAX,
                                           "cleanContent": True})   # 날짜 조건 없이 최근 20개 (이미 있는 글은 숫자만 갱신)
    tn = save_truth(conn, items, now)
    print(f"✅ 트루스소셜 트럼프: {tn}개")
    conn.execute("INSERT INTO x_cost VALUES (?,?,?) ON CONFLICT(date) DO UPDATE SET x_results = x_results + excluded.x_results, "
                 "truth_results = truth_results + excluded.truth_results", (now[:10], xn, tn))
    conn.execute("DELETE FROM x_posts WHERE created_at < ?", ((datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),))
    conn.commit()
    print(f"완료: X {xn}건 과금 기준, 트루스소셜 {tn}건 · 예상 비용 약 ${xn * 0.4 / 1000 + tn * 5 / 1000:.2f}")


if __name__ == "__main__":
    sys.exit(main())
