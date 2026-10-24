"""인스타그램 공식 Graph API(Business Discovery)로 계정·게시물·해시태그 데이터를 수집한다.

사용법:
    python collect.py                     # accounts.csv + hashtags.csv 전체 수집
    python collect.py --max-posts 100     # 계정당 최근 게시물 100개까지
    python collect.py --only themotleyfool,bitcoinmagazine
    python collect.py --skip-hashtags
"""
import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from common import ROOT, connect, load_env

MEDIA_FIELDS = "id,caption,like_count,comments_count,media_type,media_product_type,timestamp,permalink"
HASHTAG_FIELDS = "id,caption,like_count,comments_count,media_type,permalink,timestamp"
RATE_LIMIT_CODES = {4, 17, 32, 613}
DELAY_SEC = 1.0


class RateLimited(Exception):
    pass


class ApiError(Exception):
    def __init__(self, code, message):
        super().__init__(f"[{code}] {message}")
        self.code = code


class Blocked(Exception):
    """토큰이 끊겼거나 메타가 앱·계정을 막음 — 더 부르면 의심만 커지니 바로 멈춘다."""


BLOCK_HINTS = ("cannot call api", "api access blocked", "session has been invalidated", "error validating access token",
               "has not authorized application", "password", "checkpoint")


def write_health(status, message, ok=0, skipped=0, calls=0):
    """수집 상태를 output/site/ig_health.json 에 남긴다 (사이트 경고, 워크플로 실패 알림, 텔레그램 알림에 씀)."""
    out = ROOT / "output" / "site" / "ig_health.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([{"checked": datetime.now(timezone.utc).isoformat(timespec="seconds"), "status": status,
                                "message": message, "ok": ok, "skipped": skipped, "calls": calls}], ensure_ascii=False, indent=1),
                   encoding="utf-8")


class Graph:
    def __init__(self, token, ig_user_id, version):
        self.token = token
        self.ig_user_id = ig_user_id
        self.base = f"https://graph.facebook.com/{version}"
        self.calls = 0

    def get(self, path, params):
        query = urllib.parse.urlencode({**params, "access_token": self.token})
        url = f"{self.base}/{path}?{query}"
        # 해시태그 인기 게시물 조회는 응답이 1분 넘게 걸리기도 해서, 넉넉히 기다리고 두 번까지 다시 시도한다
        for attempt in range(3):
            self.calls += 1
            try:
                with urllib.request.urlopen(url, timeout=90) as resp:
                    return json.load(resp)
            except urllib.error.HTTPError as e:
                try:
                    err = json.loads(e.read() or b"{}").get("error", {})
                except json.JSONDecodeError:
                    err = {}
                code = err.get("code", e.code)
                if code in RATE_LIMIT_CODES:
                    raise RateLimited(err.get("message", "호출 한도 초과"))
                msg = err.get("message", str(e))
                if code in (190, 102) or any(h in msg.lower() for h in BLOCK_HINTS):
                    raise Blocked(f"[{code}] {msg}")
                raise ApiError(code, msg)
            except (TimeoutError, urllib.error.URLError, ConnectionError) as e:
                if attempt == 2:
                    raise ApiError("timeout", f"응답 지연으로 실패 ({e})")
                time.sleep(5 * (attempt + 1))


def fetch_account(graph, username, max_posts, with_views):
    fields = MEDIA_FIELDS + (",view_count" if with_views else "")
    info, posts, cursor = None, [], None
    while len(posts) < max_posts:
        limit = min(50, max_posts - len(posts))
        media_expr = "media" + (f".after({cursor})" if cursor else "") + f".limit({limit}){{{fields}}}"
        expr = (f"business_discovery.username({username})"
                f"{{username,name,biography,followers_count,media_count,{media_expr}}}")
        bd = graph.get(graph.ig_user_id, {"fields": expr})["business_discovery"]
        info = info or bd
        media = bd.get("media", {})
        batch = media.get("data", [])
        posts.extend(batch)
        cursor = media.get("paging", {}).get("cursors", {}).get("after")
        if not batch or not cursor:
            break
        time.sleep(DELAY_SEC)
    return info, posts


def fetch_hashtag(graph, tag):
    found = graph.get("ig_hashtag_search", {"user_id": graph.ig_user_id, "q": tag}).get("data", [])
    if not found:
        return []
    hashtag_id = found[0]["id"]
    # 인기 해시태그는 한 번에 많이 달라고 하면 '데이터를 줄여 달라'(code 1)며 거절해서 점점 줄여 재시도
    for limit in (50, 25, 10):
        time.sleep(DELAY_SEC)
        try:
            res = graph.get(f"{hashtag_id}/top_media",
                            {"user_id": graph.ig_user_id, "fields": HASHTAG_FIELDS, "limit": limit})
            return res.get("data", [])
        except ApiError as e:
            if e.code != 1 or limit == 10:
                raise


def read_csv(name):
    path = ROOT / name
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [row for row in csv.DictReader(f) if (row.get("username") or row.get("tag") or "").strip()]


def save_account(conn, row, info, posts, now):
    username = info["username"]
    conn.execute(
        """INSERT INTO accounts VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(username) DO UPDATE SET region=excluded.region, category=excluded.category,
             name=excluded.name, biography=excluded.biography, followers=excluded.followers,
             media_count=excluded.media_count, last_collected=excluded.last_collected""",
        (username, row.get("region", ""), row.get("category", ""), info.get("name"),
         info.get("biography"), info.get("followers_count"), info.get("media_count"), now))
    conn.execute("INSERT OR REPLACE INTO account_snapshots VALUES (?,?,?,?)",
                 (username, now[:10], info.get("followers_count"), info.get("media_count")))
    for p in posts:
        conn.execute(
            "INSERT OR REPLACE INTO posts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (p["id"], username, p.get("caption", ""), p.get("media_type"), p.get("media_product_type"),
             p.get("timestamp"), p.get("permalink"), p.get("like_count"), p.get("comments_count"),
             p.get("view_count"), now))
    conn.commit()


def save_hashtag(conn, row, posts, now):
    tag = row["tag"].lstrip("#").strip()
    for p in posts:
        conn.execute(
            "INSERT OR REPLACE INTO hashtag_posts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (p["id"], tag, row.get("region", ""), row.get("category", ""), p.get("caption", ""),
             p.get("media_type"), p.get("timestamp"), p.get("permalink"), p.get("like_count"),
             p.get("comments_count"), now))
    conn.commit()


def main():
    ap = argparse.ArgumentParser(description="인스타그램 경제 계정 데이터 수집")
    ap.add_argument("--max-posts", type=int, default=60, help="계정당 최근 게시물 수 (기본 60)")
    ap.add_argument("--only", help="쉼표로 구분한 아이디만 수집")
    ap.add_argument("--skip-hashtags", action="store_true")
    ap.add_argument("--hashtags-only", action="store_true", help="계정은 건너뛰고 해시태그만 수집")
    ap.add_argument("--db", default=None, help="DB 파일 경로 (기본 data/insta.db)")
    args = ap.parse_args()

    load_env()
    token, ig_user_id = os.environ.get("IG_ACCESS_TOKEN"), os.environ.get("IG_USER_ID")
    if not token or not ig_user_id:
        sys.exit("❌ .env 에 IG_ACCESS_TOKEN, IG_USER_ID 가 없습니다. SETUP_GUIDE.md 를 먼저 따라해 주세요.")
    graph = Graph(token, ig_user_id, os.environ.get("GRAPH_API_VERSION", "v25.0"))
    conn = connect(args.db) if args.db else connect()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    accounts = [] if args.hashtags_only else read_csv("accounts.csv")
    # 호출 한도에 걸려 중간에 멈춰도 매번 같은 계정만 빠지지 않게, 가장 오래전에 수집한 계정부터
    last = {r["username"].lower(): r["last_collected"] or "" for r in conn.execute("SELECT username, last_collected FROM accounts")}
    accounts.sort(key=lambda a: last.get(a["username"].strip().lstrip("@").lower(), ""))
    if args.only:
        wanted = {u.strip().lstrip("@").lower() for u in args.only.split(",")}
        accounts = [a for a in accounts if a["username"].strip().lstrip("@").lower() in wanted]

    ok, skipped, with_views = 0, [], True
    try:
        for row in accounts:
            username = row["username"].strip().lstrip("@")
            try:
                try:
                    info, posts = fetch_account(graph, username, args.max_posts, with_views)
                except ApiError as e:
                    # 일부 API 버전에서 view_count 를 지원하지 않으면 빼고 다시 시도
                    if with_views and e.code == 100 and "view_count" in str(e):
                        with_views = False
                        info, posts = fetch_account(graph, username, args.max_posts, with_views)
                    else:
                        raise
                save_account(conn, row, info, posts, now)
                ok += 1
                print(f"✅ @{username}: 팔로워 {info.get('followers_count'):,} · 게시물 {len(posts)}개 수집")
            except ApiError as e:
                skipped.append((username, str(e)))
                print(f"⚠️  @{username} 건너뜀 — 개인 계정이거나 아이디가 틀렸을 수 있음 {e}")
            time.sleep(DELAY_SEC)

        if not args.skip_hashtags and not args.only:
            for row in read_csv("hashtags.csv"):
                tag = row["tag"].lstrip("#").strip()
                try:
                    posts = fetch_hashtag(graph, tag)
                    save_hashtag(conn, row, posts, now)
                    print(f"✅ #{tag}: 인기 게시물 {len(posts)}개 수집")
                except ApiError as e:
                    print(f"⚠️  #{tag} 건너뜀 {e}")
                time.sleep(DELAY_SEC)
    except RateLimited as e:
        print(f"\n⏸  API 호출 한도에 걸려 중단했습니다 ({e}). 1시간쯤 뒤 다시 실행하면 이어서 됩니다.")
        write_health("rate_limited", str(e), ok, len(skipped), graph.calls)
    except Blocked as e:
        print(f"\n⛔ 인스타 연결이 끊겼거나 메타가 막았어요 — 바로 멈춰요: {e}")
        print("   developers.facebook.com 에서 계정 확인·앱 상태를 확인하고 토큰을 다시 받아 주세요 (SETUP_GUIDE.md).")
        write_health("blocked", str(e), ok, len(skipped), graph.calls)
    else:
        write_health("ok" if ok else "empty", f"계정 {ok}개 성공, {len(skipped)}개 건너뜀", ok, len(skipped), graph.calls)

    print(f"\n완료: 계정 {ok}개 성공, {len(skipped)}개 건너뜀, API 호출 {graph.calls}회")
    if skipped:
        print("건너뛴 계정은 accounts.csv 에서 아이디를 확인하거나 지워주세요:")
        for u, msg in skipped:
            print(f"  - @{u}: {msg}")


if __name__ == "__main__":
    main()
