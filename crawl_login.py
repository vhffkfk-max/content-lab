"""크롤링 전용 계정 로그인(한 번만) — 크롤러만 쓰는 크롬 창을 열어 직접 로그인한다.

    python crawl_login.py          # 인스타 + 쓰레드 로그인 창
    python crawl_login.py --x      # X 로그인 창
    python crawl_login.py --check  # 로그인이 살아 있는지만 확인

- 로그인 정보(쿠키)는 이 PC의 data/crawl_chrome/ 에만 남는다. 깃허브에 안 올림(.gitignore).
- 비밀번호는 창에 직접 입력. 프로그램·채팅에는 적지 않는다.
- 우리 콘텐츠 계정이 아닌 **크롤링 전용 계정**으로만 로그인할 것 (막혀도 피해 없게).
- 크롤러가 돌 때는 이 창을 닫아 둘 것 (같은 프로필을 동시에 못 씀).
"""
import argparse
import re
import subprocess
import sys

from common import ROOT
from publish.render import browser

PROFILE = ROOT / "data" / "crawl_chrome"
META = ["https://www.instagram.com/accounts/login/", "https://www.threads.com/login"]
X = ["https://x.com/i/flow/login"]


def logged_in():
    """{플랫폼: True/False} — 헤드리스로 열어 로그인된 화면인지 본다."""
    from post_reader import _dom
    out = {}
    dom = _dom("https://www.instagram.com/", login=True)
    out["인스타"] = bool(dom) and '"viewer":null' not in dom and "/accounts/login" not in dom[:20000] and bool(
        re.search(r'"(?:viewerId|viewer_id)":"\d+"', dom))
    dom = _dom("https://www.threads.com/", login=True)
    out["쓰레드"] = bool(re.search(r'"(?:viewerId|viewer_id)":"\d+"', dom))
    dom = _dom("https://x.com/home", login=True)
    out["X"] = "twid=" in dom or '"screen_name"' in dom and "/i/flow/login" not in dom
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--x", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.check:
        for k, v in logged_in().items():
            print(("✅" if v else "❌"), k, "로그인" + ("됨" if v else " 안 됨"))
        return
    PROFILE.mkdir(parents=True, exist_ok=True)
    print("크롤링 전용 크롬 창을 열어요. 크롤링 전용 계정으로 로그인한 뒤 창을 닫아 주세요.")
    subprocess.run([browser(), f"--user-data-dir={PROFILE}", "--lang=ko-KR", "--no-first-run",
                    "--no-default-browser-check", *(X if a.x else META)])
    print("창이 닫혔어요. 확인: python crawl_login.py --check")


if __name__ == "__main__":
    sys.exit(main())
