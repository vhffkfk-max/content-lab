"""연결된 내 인스타 계정의 게시물과 공식 인사이트(도달·저장·공유·조회수)를 수집한다.

    python own_collect.py            # 최근 30개 게시물
다른 계정은 좋아요·댓글만 볼 수 있지만, 내 계정은 인사이트까지 볼 수 있다 (instagram_manage_insights 권한).
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from common import connect, load_env

SCHEMA = """
CREATE TABLE IF NOT EXISTS own_posts (
    id TEXT PRIMARY KEY, username TEXT, caption TEXT, media_type TEXT, product_type TEXT, timestamp TEXT,
    permalink TEXT, likes INTEGER, comments INTEGER, reach INTEGER, saved INTEGER, shares INTEGER,
    views INTEGER, interactions INTEGER, collected_at TEXT
);
CREATE TABLE IF NOT EXISTS own_snapshots (
    date TEXT PRIMARY KEY, username TEXT, followers INTEGER, media_count INTEGER
);
"""
# 지표 이름은 API 버전·게시물 종류에 따라 거절되기도 해서, 안 되면 줄여서 다시 묻는다
METRIC_SETS = ["reach,saved,shares,views,total_interactions", "reach,saved,shares,total_interactions", "reach,saved"]


def main():
    load_env()
    token, uid = os.environ.get("IG_ACCESS_TOKEN"), os.environ.get("IG_USER_ID")
    if not token or not uid:
        print("IG_ACCESS_TOKEN/IG_USER_ID 가 없어 내 계정 수집을 건너뛰어요.")
        return
    base = f"https://graph.facebook.com/{os.environ.get('GRAPH_API_VERSION', 'v25.0')}"

    def get(path, params):
        url = f"{base}/{path}?" + urllib.parse.urlencode({**params, "access_token": token})
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            return {"error": json.loads(e.read() or b"{}").get("error", {})}
        except (TimeoutError, urllib.error.URLError) as e:
            return {"error": {"message": str(e)}}

    conn = connect()
    conn.executescript(SCHEMA)
    now = datetime.now(timezone.utc)
    me = get(uid, {"fields": "username,followers_count,media_count"})
    if "error" in me:
        print(f"⚠️ 내 계정 정보를 받지 못했어요: {me['error'].get('message')}")
        return
    conn.execute("INSERT OR REPLACE INTO own_snapshots VALUES (?,?,?,?)",
                 (now.date().isoformat(), me.get("username"), me.get("followers_count"), me.get("media_count")))
    media = get(f"{uid}/media", {"fields": "id,caption,media_type,media_product_type,timestamp,permalink,like_count,comments_count",
                                 "limit": 30}).get("data", [])
    n = 0
    for m in media:
        values = {}
        for metrics in METRIC_SETS:
            r = get(f"{m['id']}/insights", {"metric": metrics})
            if "error" not in r:
                values = {d["name"]: (d.get("values") or [{}])[0].get("value", d.get("total_value", {}).get("value")) for d in r.get("data", [])}
                break
        conn.execute("INSERT OR REPLACE INTO own_posts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            m["id"], me.get("username"), m.get("caption") or "", m.get("media_type"), m.get("media_product_type"),
            m.get("timestamp"), m.get("permalink"), m.get("like_count"), m.get("comments_count"),
            values.get("reach"), values.get("saved"), values.get("shares"), values.get("views"),
            values.get("total_interactions"), now.isoformat(timespec="seconds")))
        n += 1
        time.sleep(0.5)
    conn.commit()
    print(f"✅ 내 계정 @{me.get('username')}: 팔로워 {me.get('followers_count'):,} · 게시물 {n}개 인사이트 수집")


if __name__ == "__main__":
    sys.exit(main())
