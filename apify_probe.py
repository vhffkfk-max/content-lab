"""Apify 수집기 시험 (조회수 등 필드가 실제로 나오는지 소량으로 확인). GitHub Actions 'apify-probe' 에서 실행."""
import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone


def run(actor, payload):
    url = f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items?token={os.environ['APIFY_TOKEN']}&timeout=280"
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)


since = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d")
tests = [
    ("apify~instagram-scraper", "인스타 게시물(posts)", {"directUrls": ["https://www.instagram.com/syukaworld/", "https://www.instagram.com/bullstory1/"],
                                                    "resultsType": "posts", "resultsLimit": 5}),
    ("apidojo~tweet-scraper", "X 정책 계정", {"searchTerms": [f"(from:realDonaldTrump OR from:WhiteHouse OR from:SecScottBessent OR from:federalreserve) -filter:replies since:{since}"],
                                          "sort": "Latest", "maxItems": 50}),
    ("apidojo~tweet-scraper", "X 경제 키워드 화제", {"searchTerms": [f"(tariff OR Fed OR inflation OR bitcoin OR \"stock market\") min_faves:5000 lang:en -filter:replies since:{since}"],
                                              "sort": "Top", "maxItems": 50}),
    ("tri_angle~truth-scraper", "트루스소셜 트럼프 글", {"profiles": ["realDonaldTrump"], "resultsType": "posts", "maxPostsAndReplies": 5, "cleanContent": True}),
]
for actor, name, payload in tests:
    try:
        items = run(actor, payload)
    except Exception as e:
        print(f"== {name}: 실패 {e}")
        continue
    print(f"== {name}: {len(items)} rows")
    if not items:
        continue
    first = items[0]
    print("   keys:", sorted(first.keys()))
    if "ownerUsername" in first:
        for p in items[:6]:
            print("     ", p.get("ownerUsername"), p.get("type"), p.get("productType"), "좋아요", p.get("likesCount"), "댓글", p.get("commentsCount"),
                  "조회", p.get("videoViewCount"), "재생", p.get("videoPlayCount"), p.get("timestamp"))
        continue
    if "latestPosts" in first:
        for prof in items:
            print("   프로필", prof.get("username"), "팔로워", prof.get("followersCount"), "글", len(prof.get("latestPosts") or []))
            for p in (prof.get("latestPosts") or [])[:4]:
                print("     ", p.get("type"), p.get("productType"), "좋아요", p.get("likesCount"), "댓글", p.get("commentsCount"),
                      "조회", p.get("videoViewCount"), "재생", p.get("videoPlayCount"), p.get("timestamp"))
            if prof.get("latestPosts"):
                print("   latestPost keys:", sorted(prof["latestPosts"][0].keys()))
    else:
        for i in items[:5]:
            a = i.get("author") or i.get("account") or {}
            print("    ", (a.get("userName") or a.get("username")), "조회", i.get("viewCount"), "좋아요", i.get("likeCount") or i.get("favouritesCount"),
                  "RT", i.get("retweetCount") or i.get("reblogsCount"), "답글", i.get("replyCount") or i.get("repliesCount"),
                  i.get("createdAt"), str(i.get("text") or i.get("content") or "")[:60].replace("\n", " "))
