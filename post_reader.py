"""쓰레드·인스타 공개 글 하나 읽기 — 로그인 없이 크롬(헤드리스)으로 연다 (댓글 기회 봇용).

    from post_reader import read
    read("https://www.threads.com/@id/post/CODE")
    → {"platform","url","author","text","posted_at"(유닉스 초 또는 None),"date","views","likes","replies","reposts","top_replies"[...]}
    python post_reader.py <링크>      # 시험

쓰레드: 화면 안 JSON 에서 본문·숫자·상위 답글(좋아요 순 5개)과 조회수를 읽는다.
인스타: 로그인 창 때문에 본문 아래는 막혀 있어서, 미리보기 설명(좋아요·댓글 수·작성자·날짜·캡션)만 읽는다. 상위 댓글은 없음.
로그인·쿠키 저장은 하지 않는다 (매번 새 임시 프로필).
"""
import html
import json
import re
import subprocess
import sys
import tempfile

import requests

from publish.render import browser

THREADS = re.compile(r"https?://(?:www\.)?threads\.(?:net|com)/@?([\w.]+)/post/([\w-]+)")
INSTA = re.compile(r"https?://(?:www\.)?instagram\.com/(?:[\w.]+/)?(?:p|reel|reels)/([\w-]+)")
LINK = re.compile(r"https?://(?:www\.)?(?:threads\.(?:net|com)|instagram\.com)/\S+")


def find_link(text):
    m = LINK.search(text or "")
    return m.group(0).rstrip(").,") if m else None


def _dom(url, wait_ms=8000, timeout=25):
    with tempfile.TemporaryDirectory() as prof:
        r = subprocess.run([browser(), "--headless=new", "--disable-gpu", f"--user-data-dir={prof}", "--lang=ko-KR",
                            f"--virtual-time-budget={wait_ms}", "--dump-dom", url],
                           capture_output=True, timeout=timeout)
    return r.stdout.decode("utf-8", "ignore")


def _walk(o, out):
    if isinstance(o, dict):
        if "caption" in o and "like_count" in o and "code" in o:
            out.append(o)
        for v in o.values():
            _walk(v, out)
    elif isinstance(o, list):
        for v in o:
            _walk(v, out)


def _threads(url, dom):
    m = THREADS.search(url)
    posts = []
    for s in re.findall(r'<script type="application/json"[^>]*>(.*?)</script>', dom, re.S):
        if '"like_count"' in s:
            try:
                _walk(json.loads(s), posts)
            except json.JSONDecodeError:
                pass
    uniq = {}
    for p in posts:
        uniq.setdefault(p["code"], p)
    if not uniq:
        return None
    main = uniq.get(m.group(2)) if m else None
    main = main or next(p for p in uniq.values() if not (p.get("text_post_app_info") or {}).get("is_reply"))
    info = lambda p: p.get("text_post_app_info") or {}
    text = lambda p: (p.get("caption") or {}).get("text") or ""
    replies = sorted((p for p in uniq.values() if info(p).get("is_reply") and p is not main), key=lambda p: -(p.get("like_count") or 0))
    views = re.search(r'"view_counts":(\d+)', dom)
    return {"platform": "threads", "url": url, "author": main["user"]["username"], "text": text(main),
            "posted_at": main.get("taken_at"), "date": None, "views": int(views.group(1)) if views else None,
            "likes": main.get("like_count"), "replies": info(main).get("direct_reply_count"),
            "reposts": info(main).get("repost_count"),
            "top_replies": [f"@{p['user']['username']}: {text(p)[:200]}" for p in replies[:5] if text(p)]}


def _num(s):
    s = s.replace(",", "")
    mult = 1000 if s.endswith("K") else 1_000_000 if s.endswith("M") else 1
    return int(float(s.rstrip("KM")) * mult)


def _insta(url, dom):
    m = re.search(r'<meta[^>]*name="description"[^>]*content="([^"]*)"', dom) or \
        re.search(r'<meta[^>]*content="([^"]*)"[^>]*property="og:description"', dom)
    if not m:
        return None
    d = html.unescape(m.group(1))
    # "9 likes, 0 comments - seoul_economic - October 26, 2026: "캡션"."
    h = re.match(r"([\d.,KM]+) likes?, ([\d.,KM]+) comments? - ([\w.]+) (?:- |on )?([^:]+): [\"“]?(.*?)[\"”]?\.?\s*$", d, re.S)
    if not h:
        return None
    return {"platform": "instagram", "url": url, "author": h.group(3), "text": h.group(5).strip(), "posted_at": None,
            "date": h.group(4).strip(), "views": None, "likes": _num(h.group(1)), "replies": _num(h.group(2)),
            "reposts": None, "top_replies": []}


def _resolve(url):
    """앱 '공유' 링크(threads.com/share/…, instagram.com/share/…)는 원래 글 주소로 넘어가는 주소라 따라가서 바꾼다."""
    if THREADS.search(url) or INSTA.search(url):
        return url
    try:
        r = requests.get(url, allow_redirects=True, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        return r.url.split("?")[0]
    except requests.RequestException:
        return url


def read(url, tries=2):
    url = _resolve(url.replace("threads.net", "threads.com"))
    parse = _threads if THREADS.search(url) else _insta if INSTA.search(url) else None
    if not parse:
        return None
    for _ in range(tries):
        try:
            post = parse(url, _dom(url))
            if post and post["text"]:
                return post
        except (subprocess.TimeoutExpired, StopIteration, KeyError):
            pass
    return None


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(read(sys.argv[1]), ensure_ascii=False, indent=1))
