"""쓰레드 계정을 연결해 60일짜리 접근 토큰을 받는다 (공식 Threads API).

.env 에 THREADS_APP_ID, THREADS_APP_SECRET 을 먼저 적은 뒤:
    python threads_auth.py            # 브라우저로 로그인 → 콜백 페이지의 코드를 붙여넣기
    python threads_auth.py --refresh  # 50일쯤 지났을 때 토큰 연장 (60일 더)
    python threads_auth.py --push     # 토큰을 GitHub 비밀값으로도 등록 (자동 실행용)
토큰 값은 화면에 출력하지 않는다.
"""
import argparse
import json
import os
import secrets
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

from common import ROOT, load_env
from get_token import set_env

REDIRECT_URI = "https://vhffkfk-max.github.io/content-lab/threads-callback.html"
SCOPES = "threads_basic,threads_keyword_search"
API = "https://graph.threads.com"


def call(method, path, params):
    data = urllib.parse.urlencode(params).encode() if method == "POST" else None
    url = f"{API}{path}" + ("" if method == "POST" else "?" + urllib.parse.urlencode(params))
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, method=method), timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = json.loads(e.read() or b"{}")
        msg = body.get("error_message") or body.get("error", {}).get("message") or str(e)
        sys.exit(f"❌ 쓰레드 응답 오류: {msg}")


def push_secrets():
    for name in ("THREADS_ACCESS_TOKEN", "THREADS_USER_ID"):
        subprocess.run(["gh", "secret", "set", name], input=os.environ[name], text=True, check=True,
                       cwd=ROOT, stdout=subprocess.DEVNULL)
        print(f"✅ GitHub 비밀값 {name} 등록")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--push", action="store_true")
    args = ap.parse_args()
    load_env()
    app_id, secret = os.environ.get("THREADS_APP_ID"), os.environ.get("THREADS_APP_SECRET")

    if args.refresh:
        res = call("GET", "/refresh_access_token", {"grant_type": "th_refresh_token",
                                                    "access_token": os.environ["THREADS_ACCESS_TOKEN"]})
        set_env({"THREADS_ACCESS_TOKEN": res["access_token"]})
        os.environ["THREADS_ACCESS_TOKEN"] = res["access_token"]
        print(f"✅ 쓰레드 토큰을 연장했어요 (약 {res.get('expires_in', 0) // 86400}일)")
    else:
        if not (app_id and secret):
            sys.exit("❌ .env 에 THREADS_APP_ID, THREADS_APP_SECRET 을 먼저 적어주세요 (THREADS_SETUP.md 2단계).")
        state = secrets.token_urlsafe(12)
        url = "https://threads.com/oauth/authorize?" + urllib.parse.urlencode({
            "client_id": app_id, "redirect_uri": REDIRECT_URI, "scope": SCOPES,
            "response_type": "code", "state": state})
        print("브라우저에서 쓰레드 로그인 → '허용'을 누르세요. 열리지 않으면 아래 주소를 직접 여세요:\n" + url + "\n")
        webbrowser.open(url)
        code = input("콜백 페이지에 나온 코드를 붙여넣고 Enter: ").strip().replace("#_", "")
        short = call("POST", "/oauth/access_token", {
            "client_id": app_id, "client_secret": secret, "code": code,
            "grant_type": "authorization_code", "redirect_uri": REDIRECT_URI})
        long = call("GET", "/access_token", {"grant_type": "th_exchange_token", "client_secret": secret,
                                             "access_token": short["access_token"]})
        me = call("GET", "/v1.0/me", {"fields": "id,username", "access_token": long["access_token"]})
        set_env({"THREADS_ACCESS_TOKEN": long["access_token"], "THREADS_USER_ID": me["id"]})
        os.environ.update({"THREADS_ACCESS_TOKEN": long["access_token"], "THREADS_USER_ID": me["id"]})
        print(f"✅ 쓰레드 연결 완료: @{me.get('username')} (토큰 약 {long.get('expires_in', 0) // 86400}일)")
    if args.push:
        push_secrets()


if __name__ == "__main__":
    main()
