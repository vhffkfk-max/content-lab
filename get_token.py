"""Graph API 탐색기에서 받은 '짧은 토큰'을 60일짜리 토큰으로 바꾸고,
내 인스타그램 비즈니스 계정 ID를 찾아 .env 에 저장한다.

.env 에 META_APP_ID, META_APP_SECRET, SHORT_TOKEN 을 먼저 적은 뒤:
    python get_token.py
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from common import ENV_PATH, load_env


def get(url, params):
    try:
        with urllib.request.urlopen(f"{url}?{urllib.parse.urlencode(params)}", timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        msg = json.loads(e.read() or b"{}").get("error", {}).get("message", str(e))
        sys.exit(f"❌ Meta 응답 오류: {msg}")


def set_env(updates):
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    keys = set(updates)
    out = [l for l in lines if l.split("=", 1)[0].strip() not in keys]
    out += [f"{k}={v}" for k, v in updates.items()]
    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")


def main():
    load_env()
    ver = os.environ.get("GRAPH_API_VERSION", "v25.0")
    app_id, secret, short = (os.environ.get(k) for k in ("META_APP_ID", "META_APP_SECRET", "SHORT_TOKEN"))
    if not (app_id and secret and short):
        sys.exit("❌ .env 에 META_APP_ID, META_APP_SECRET, SHORT_TOKEN 을 먼저 적어주세요 (SETUP_GUIDE.md 4~5단계).")
    base = f"https://graph.facebook.com/{ver}"

    long_token = get(f"{base}/oauth/access_token", {
        "grant_type": "fb_exchange_token", "client_id": app_id,
        "client_secret": secret, "fb_exchange_token": short})["access_token"]

    pages = get(f"{base}/me/accounts", {
        "fields": "name,instagram_business_account{id,username}", "access_token": long_token}).get("data", [])
    linked = [p for p in pages if p.get("instagram_business_account")]
    if not linked:
        sys.exit("❌ 인스타그램이 연결된 페이스북 페이지를 찾지 못했어요. SETUP_GUIDE.md 2단계와 권한 선택을 확인해 주세요.")
    ig = linked[0]["instagram_business_account"]
    set_env({"IG_ACCESS_TOKEN": long_token, "IG_USER_ID": ig["id"], "SHORT_TOKEN": ""})
    print(f"✅ 연결 완료: @{ig.get('username')} (페이지: {linked[0]['name']})")
    print("   60일짜리 토큰을 .env 에 저장했어요. 만료되면 이 과정을 다시 하면 됩니다.")


if __name__ == "__main__":
    main()
