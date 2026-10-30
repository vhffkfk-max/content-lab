"""크롤링 전용 계정 로그인(한 번만) — 크롤러만 쓰는 크롬 창을 열어 직접 로그인한다.

    python crawl_login.py          # 인스타 + 쓰레드 로그인 창
    python crawl_login.py --x      # X 로그인 창
    python crawl_login.py --check  # 로그인이 살아 있는지만 확인

- 로그인 정보(쿠키)는 이 PC의 data/crawl_chrome/ 에만 남는다. 깃허브에 안 올림(.gitignore).
- 비밀번호는 창에 직접 입력. 프로그램·채팅에는 적지 않는다.
- 우리 콘텐츠 계정이 아닌 **크롤링 전용 계정**으로만 로그인할 것 (막혀도 피해 없게).
- 같은 프로필을 크롬 두 개가 동시에 못 써서, 창을 여는 동안 PC 크롤러(작업 content-lab-threads-watch)를 잠깐 멈췄다가 창을 닫으면 다시 켠다.
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
TASK = "content-lab-threads-watch"


def ps(cmd):
    return subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True)


def pause_crawler():
    """크롤러와 그 크롬을 멈춤 → 켜져 있었으면 True."""
    running = TASK in ps(f"(Get-ScheduledTask -TaskName '{TASK}' -ErrorAction SilentlyContinue | Where-Object State -eq 'Running').TaskName").stdout
    ps(f"Stop-ScheduledTask -TaskName '{TASK}' -ErrorAction SilentlyContinue; "
       "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*threads_watch*' -and $_.Name -like 'python*' } | "
       "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }; Start-Sleep 2; "
       "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | Where-Object { $_.CommandLine -like '*crawl_chrome*' } | "
       "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
    return running


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
    was = sys.platform == "win32" and pause_crawler()
    print("크롤링 전용 크롬 창을 열어요. 크롤링 전용 계정으로 로그인한 뒤 창을 닫아 주세요.")
    subprocess.run([browser(), f"--user-data-dir={PROFILE}", "--lang=ko-KR", "--no-first-run",
                    "--no-default-browser-check", *(X if a.x else META)])
    if was:
        ps(f"Start-ScheduledTask -TaskName '{TASK}'")
        print("PC 크롤러를 다시 켰어요.")
    print("창이 닫혔어요. 확인: python crawl_login.py --check")


if __name__ == "__main__":
    sys.exit(main())
