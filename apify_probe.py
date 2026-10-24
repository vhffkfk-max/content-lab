"""Apify 쓰레드 수집기 시험 (조회수가 실제로 나오는지 소량으로 확인). GitHub Actions 'apify-probe' 에서 실행.

    python apify_probe.py
"""
import json
import os
import urllib.request
from collections import Counter

ACTOR = "futurizerush~meta-threads-scraper"


def run(payload):
    url = f"https://api.apify.com/v2/acts/{ACTOR}/run-sync-get-dataset-items?token={os.environ['APIFY_TOKEN']}&timeout=280"
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)


for name, payload in [
    ("search 미국주식 top", {"mode": "search", "keywords": ["미국주식"], "search_filter": "top", "max_posts": 10}),
    ("user 2 accounts", {"mode": "user", "usernames": ["syukaworld", "bullstory1"], "max_posts": 10}),
]:
    try:
        items = run(payload)
    except Exception as e:
        print(f"== {name}: 실패 {e}")
        continue
    posts = [i for i in items if i.get("like_count") is not None or i.get("view_count") is not None]
    print(f"== {name}: {len(items)} rows, posts {len(posts)}")
    print("   view_count_status:", Counter(i.get("view_count_status") for i in posts))
    print("   followers present:", sum(1 for i in posts if i.get("followers_count")))
    print("   keys:", sorted(items[0].keys())[:60] if items else [])
    for i in posts[:5]:
        print("   ", i.get("username"), i.get("followers_count"), "views", i.get("view_count"), "likes", i.get("like_count"),
              "replies", i.get("reply_count"), "reposts", i.get("repost_count"), i.get("created_at"), (i.get("text") or "")[:40].replace("\n", " "))
