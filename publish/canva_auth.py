"""캔바 연결(한 번만): 브라우저로 캔바 로그인 → 토큰을 받아 .env 와 깃허브 Secrets 에 저장 → Pro 계정에서 API가 되는지 바로 시험.

1) 캔바 설정에서 2단계 인증(MFA) 켜기
2) canva.dev → Your integrations → Create an integration (Public 선택 — Private 은 Enterprise 전용)
   - Scopes: design:meta:read, design:content:read, design:content:write, folder:read, folder:write,
             asset:read, asset:write, profile:read
   - Authentication → Redirect URL: http://127.0.0.1:3001/oauth/redirect
   - Client ID / Generate secret 복사 → .env 에 CANVA_CLIENT_ID=..., CANVA_CLIENT_SECRET=... 저장
3) python -m publish.canva_auth          # 로그인 + 시험
   python -m publish.canva_auth --test   # 저장된 토큰으로 시험만
토큰 값은 화면에 출력하지 않는다. refresh token 은 한 번 쓰면 바뀌므로 공용 파일 하나에만 두고 잠금 안에서만 갱신한다.
"""
import base64
import hashlib
import http.server
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

from common import ROOT, load_env

API = "https://api.canva.com/rest/v1"
PORT = 3001
REDIRECT = f"http://127.0.0.1:{PORT}/oauth/redirect"
SCOPES = "design:meta:read design:content:read design:content:write folder:read folder:write asset:read asset:write profile:read"


def token_request(params):
    cid, csec = os.environ["CANVA_CLIENT_ID"], os.environ["CANVA_CLIENT_SECRET"]
    req = urllib.request.Request(f"{API}/oauth/token", data=urllib.parse.urlencode(params).encode(), method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": "Basic " + base64.b64encode(f"{cid}:{csec}".encode()).decode()})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"❌ 캔바 토큰 받기 실패({e.code}): {e.read()[:300].decode('utf-8', 'ignore')}")


# 캔바 토큰은 PC 한 곳(~/.content-lab-ai/canva_token.json)에만 둔다 (2026-11-01).
# 예전엔 폴더마다 .env 에 따로 저장해서, 개발 폴더의 옛 refresh token 이 한 번 더 쓰이거나 두 프로그램이 동시에 갱신하면
# 캔바가 "Refresh token used twice" 로 로그인 전체를 취소했다(10/29, 11/01 두 번). 이제는
#  - 모든 폴더·프로그램이 같은 파일을 읽고, 갱신은 잠금(lock) 안에서 한 번에 하나만
#  - 받은 access token(몇 시간 유효)을 파일에 같이 두고 끝나기 전까지는 갱신 자체를 안 함 → 갱신은 하루 몇 번뿐
#  - .env·깃허브 Secrets 에는 refresh token 을 더 이상 쓰지 않음 (옛 값이 남아도 읽지 않음)
STORE = Path.home() / ".content-lab-ai" / "canva_token.json"
LOCKF = STORE.with_suffix(".lock")


class _Lock:
    def __enter__(self):
        STORE.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(240):   # 최대 2분 기다림
            try:
                self.fd = os.open(LOCKF, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except FileExistsError:
                if time.time() - LOCKF.stat().st_mtime > 180:   # 죽은 프로그램이 남긴 잠금
                    LOCKF.unlink(missing_ok=True)
                time.sleep(0.5)
        sys.exit("❌ 캔바 토큰 잠금을 2분 넘게 못 얻었어요 — 다른 캔바 작업이 끝난 뒤 다시")

    def __exit__(self, *a):
        os.close(self.fd)
        LOCKF.unlink(missing_ok=True)


def _read():
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_tokens(t):
    """캔바 토큰 응답 → 공용 파일 (잠금 안에서 부를 것)."""
    d = {"refresh_token": t["refresh_token"], "access_token": t["access_token"],
         "access_exp": time.time() + int(t.get("expires_in", 3600)) - 600, "saved_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d), encoding="utf-8")
    os.replace(tmp, STORE)
    print("✅ 캔바 토큰 저장 (PC 공용 파일 하나)")


def refresh_access():
    """공용 파일의 access token 을 쓰고, 끝나 가면 잠금 안에서 한 번만 갱신."""
    d = _read()
    if d.get("access_exp", 0) > time.time():
        return d["access_token"]
    with _Lock():
        d = _read()   # 기다리는 동안 다른 프로그램이 이미 갱신했을 수 있음
        if d.get("access_exp", 0) > time.time():
            return d["access_token"]
        if not d.get("refresh_token"):
            sys.exit("❌ 캔바 연결 정보가 없어요 — content-lab-ai 폴더에서 'python -m publish.canva_auth' 로 다시 허용해 주세요.")
        t = token_request({"grant_type": "refresh_token", "refresh_token": d["refresh_token"]})
        save_tokens(t)
        return t["access_token"]


def login():
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    url = "https://www.canva.com/api/oauth/authorize?" + urllib.parse.urlencode({
        "code_challenge": challenge, "code_challenge_method": "S256", "scope": SCOPES, "response_type": "code",
        "client_id": os.environ["CANVA_CLIENT_ID"], "state": state, "redirect_uri": REDIRECT}, quote_via=urllib.parse.quote)
    got = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h2>캔바 연결 완료 — 이 창은 닫아도 돼요.</h2>".encode())

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
    print("브라우저에서 캔바 로그인 → '허용'을 눌러 주세요...")
    webbrowser.open(url)
    while "code" not in got and "error" not in got:
        server.handle_request()
    server.server_close()
    if got.get("error"):
        sys.exit(f"❌ 캔바가 거절했어요: {got.get('error')} {got.get('error_description', '')}")
    if got.get("state") != state:
        sys.exit("❌ 로그인 응답이 맞지 않아요(state 불일치). 다시 실행해 주세요.")
    t = token_request({"grant_type": "authorization_code", "code": got["code"], "code_verifier": verifier, "redirect_uri": REDIRECT})
    with _Lock():
        save_tokens(t)
    return t["access_token"]


def get(token, path):
    req = urllib.request.Request(f"{API}/{path}", headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:300].decode("utf-8", "ignore")


def test(token):
    ok = True
    for label, path in (("내 계정", "users/me"), ("기능(Pro 여부)", "users/me/capabilities"),
                        ("폴더 보기", "folders/root/items?limit=5"), ("디자인 목록", "designs?limit=5")):
        code, body = get(token, path)
        ok &= code == 200 or label == "폴더 보기"   # root 폴더 지원 여부는 문서에 없음 — 실패해도 Phase 2에서 폴더를 새로 만듦
        print(("✅" if code == 200 else "❌"), label, code, json.dumps(body, ensure_ascii=False)[:200] if code == 200 else body)
    print("\n🎉 캔바 API 연결 성공 — Phase 2 진행 가능" if ok else "\n⚠️ 일부 실패 — 위 메시지를 확인해 주세요")


def main():
    load_env()
    missing = [k for k in ("CANVA_CLIENT_ID", "CANVA_CLIENT_SECRET") if not os.environ.get(k)]
    if missing:
        sys.exit(f"❌ .env 에 {', '.join(missing)} 가 없어요 (파일 맨 위 설명 2번 참고).")
    token = refresh_access() if "--test" in sys.argv else login()
    test(token)


if __name__ == "__main__":
    main()
