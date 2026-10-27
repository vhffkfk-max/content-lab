"""인스타 토큰에 '발행 권한'(instagram_content_publish)을 더해 다시 받는다 (한 번만). 토큰 값은 화면에 출력하지 않는다.

1) Graph API 탐색기(developers.facebook.com/tools/explorer)에서 연구소 앱 선택 →
   권한: pages_show_list, business_management, instagram_basic, instagram_manage_insights, pages_read_engagement,
         instagram_content_publish  (마지막 하나가 새로 추가) → Generate Access Token → 복사
2) .env 에 SHORT_TOKEN=복사한값 저장
3) python -m publish.ig_token
   → 60일 사용자 토큰 → 만료 없는 페이지 토큰으로 바꾸고, 발행 권한이 들어갔는지 확인한 뒤 .env 와 깃허브 Secrets 를 바꾼다
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

from common import ROOT, load_env
from get_token import set_env

BASE = "https://graph.facebook.com/v25.0"


def get(path, params):
    try:
        with urllib.request.urlopen(f"{BASE}/{path}?{urllib.parse.urlencode(params)}", timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit("❌ Meta 응답 오류: " + json.loads(e.read() or b"{}").get("error", {}).get("message", str(e)))


def main():
    load_env()
    app_id, secret, short = (os.environ.get(k) for k in ("META_APP_ID", "META_APP_SECRET", "SHORT_TOKEN"))
    if not short:
        sys.exit("❌ .env 에 SHORT_TOKEN 을 먼저 넣어 주세요 (이 파일 맨 위 설명 1~2번).")
    user = get("oauth/access_token", {"grant_type": "fb_exchange_token", "client_id": app_id, "client_secret": secret,
                                      "fb_exchange_token": short})["access_token"]
    scopes = get("debug_token", {"input_token": user, "access_token": f"{app_id}|{secret}"}).get("data", {}).get("scopes", [])
    if "instagram_content_publish" not in scopes:
        sys.exit("❌ 토큰에 instagram_content_publish 권한이 없어요. 탐색기에서 권한을 추가하고 다시 받아 주세요.")
    pages = get("me/accounts", {"fields": "name,access_token,instagram_business_account{id,username}", "access_token": user}).get("data", [])
    page = next((p for p in pages if p.get("instagram_business_account")), None)
    if not page:
        sys.exit("❌ 인스타가 연결된 페이스북 페이지를 찾지 못했어요.")
    ig = page["instagram_business_account"]
    limit = get(f"{ig['id']}/content_publishing_limit", {"fields": "config,quota_usage", "access_token": page["access_token"]})
    quota = (limit.get("data") or [{}])[0]
    set_env({"IG_ACCESS_TOKEN": page["access_token"], "IG_USER_TOKEN": user, "IG_USER_ID": ig["id"], "IG_TOKEN_KIND": "page",
             "SHORT_TOKEN": ""})
    print(f"✅ @{ig.get('username')} 발행 권한 확인 (24시간 발행 {quota.get('quota_usage', 0)}/{(quota.get('config') or {}).get('quota_total', '?')})")
    for name, value in (("IG_ACCESS_TOKEN", page["access_token"]), ("IG_USER_ID", ig["id"])):
        subprocess.run(["gh", "secret", "set", name, "--repo", "vhffkfk-max/content-lab"], input=value, text=True, check=True,
                       cwd=ROOT, stdout=subprocess.DEVNULL)
        print(f"✅ 깃허브 Secrets 에 {name} 갱신 (수집도 같은 토큰을 써요)")


if __name__ == "__main__":
    main()
