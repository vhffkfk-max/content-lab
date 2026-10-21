"""60일짜리 사용자 토큰으로 '만료 없는 페이지 토큰'을 받아, 수집이 되는지 확인한 뒤 .env 에 저장한다.

자동 수집(GitHub Actions)은 이 페이지 토큰을 쓴다. 토큰 값은 화면에 출력하지 않는다.
    python make_page_token.py
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from common import load_env
from get_token import set_env


def get(path, params):
    ver = os.environ.get("GRAPH_API_VERSION", "v25.0")
    url = f"https://graph.facebook.com/{ver}/{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit("❌ " + json.loads(e.read() or b"{}").get("error", {}).get("message", str(e)))


def main():
    load_env()
    user_token, ig_id = os.environ.get("IG_ACCESS_TOKEN"), os.environ.get("IG_USER_ID")
    if os.environ.get("IG_TOKEN_KIND") == "page":
        print("✅ 이미 만료 없는 페이지 토큰을 쓰고 있어요.")
        return
    pages = get("me/accounts", {"fields": "name,access_token,instagram_business_account",
                                "access_token": user_token}).get("data", [])
    page = next((p for p in pages if (p.get("instagram_business_account") or {}).get("id") == ig_id), None)
    if not page:
        sys.exit("❌ 인스타가 연결된 페이지를 찾지 못했어요.")
    page_token = page["access_token"]
    test = get(ig_id, {"fields": "business_discovery.username(faststocknews){followers_count}",
                       "access_token": page_token})
    if "business_discovery" not in test:
        sys.exit("❌ 페이지 토큰으로 조회가 안 돼요. 기존 토큰을 계속 씁니다.")
    debug = get("debug_token", {"input_token": page_token, "access_token": page_token}).get("data", {})
    expires = debug.get("expires_at", 0)
    set_env({"IG_ACCESS_TOKEN": page_token, "IG_USER_TOKEN": user_token, "IG_TOKEN_KIND": "page"})
    print(f"✅ 페이지 토큰으로 교체했어요 (페이지: {page['name']}). "
          f"만료: {'없음' if not expires else expires}")


if __name__ == "__main__":
    main()
