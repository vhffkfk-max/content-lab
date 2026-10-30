"""크롤링 전용 계정으로 로그인된 크롬(crawl_login.py 로 만든 프로필)으로 화면을 연다.

    from logged_browser import ready, visit, close
    if ready():
        html, bodies = visit("https://www.threads.com/@id", scrolls=2)

- 화면을 열고 아래로 조금 내리면서, 그 화면이 스스로 불러오는 데이터(JSON)를 옆에서 같이 받아 둔다.
  (따로 숨은 주소를 부르지 않음 — 사람이 화면을 볼 때 오가는 것과 같은 것만)
- 계정이 막히지 않게 화면 사이마다 4~9초 쉬고, 한 바퀴가 끝나면 close() 로 크롬을 닫는다.
- 로그인이 풀리면(로그인 화면으로 넘어가면) 그 플랫폼은 이번 실행 동안 쓰지 않고 로그인 없는 방식으로 돌아간다.
"""
import json
import logging
import random
import time

from post_reader import LOGIN_PROFILE, _walk
from publish.render import browser

log = logging.getLogger("threads_watch")
_pw = _ctx = _page = None
_off = set()       # 로그인이 풀린 플랫폼
_last = 0.0


def _plat(url):
    return "instagram" if "instagram.com" in url else "threads" if "threads." in url else "x"


def ready(platform="threads"):
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return LOGIN_PROFILE.exists() and platform not in _off


def _open():
    global _pw, _ctx, _page
    if _page:
        return _page
    from playwright.sync_api import sync_playwright
    _pw = sync_playwright().start()
    _ctx = _pw.chromium.launch_persistent_context(str(LOGIN_PROFILE), executable_path=browser(), headless=True,
                                                  locale="ko-KR", viewport={"width": 1280, "height": 900})
    _page = _ctx.pages[0] if _ctx.pages else _ctx.new_page()
    return _page


def visit(url, scrolls=1, wait_ms=5000):
    """→ (화면 html, [그 화면이 불러온 JSON 들]). 로그인이 풀렸으면 (None, [])."""
    global _last
    plat = _plat(url)
    if plat in _off:
        return None, []
    gap = random.uniform(4, 9) - (time.time() - _last)
    if gap > 0:
        time.sleep(gap)
    page = _open()
    bodies = []

    def on(r):
        if "graphql" in r.url or "/api/v1/" in r.url:
            try:
                bodies.append(json.loads(r.text()))
            except Exception:
                pass
    page.on("response", on)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(wait_ms)
        for _ in range(scrolls):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(random.randint(2000, 3500))
        html = page.content()
    except Exception as e:
        log.info("로그인 크롬으로 못 열었어요 %s: %r", url, e)
        return None, []
    finally:
        page.remove_listener("response", on)
        _last = time.time()
    if "/accounts/login" in page.url or page.url.split("?")[0].endswith("/login"):
        _off.add(plat)
        log.info("⚠️ %s 크롤링 계정 로그인이 풀렸어요 — python crawl_login.py 로 다시 로그인해 주세요", plat)
        return None, []
    return html, bodies


def close():
    global _pw, _ctx, _page
    try:
        if _ctx:
            _ctx.close()
        if _pw:
            _pw.stop()
    except Exception:
        pass
    _pw = _ctx = _page = None


def threads_posts(html, bodies):
    """쓰레드 화면 안 JSON + 불러온 JSON 에서 글 (code 기준 중복 없음)."""
    import re
    posts = []
    for s in re.findall(r'<script type="application/json"[^>]*>(.*?)</script>', html or "", re.S):
        if '"like_count"' in s:
            try:
                _walk(json.loads(s), posts)
            except json.JSONDecodeError:
                pass
    for b in bodies:
        _walk(b, posts)
    return list({p["code"]: p for p in posts if p.get("code")}.values())


def find_key(o, key, out):
    """JSON 안에서 key 가 붙은 값을 모두."""
    if isinstance(o, dict):
        for k, v in o.items():
            if k == key:
                out.append(v)
            find_key(v, key, out)
    elif isinstance(o, list):
        for v in o:
            find_key(v, key, out)
    return out
