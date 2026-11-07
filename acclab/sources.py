"""계정 전용 추가 소스 — 기존 수집기(press_collect·google_collect·news_pool)는 건드리지 않고, 소재 정제 때만 따로 읽는다.

    python -m acclab.sources            # 지금 읽히는 추가 소스 묶음 미리 보기

- crypto (코인 계정): 블록미디어·토큰포스트(국내), 코인텔레그래프(해외) 공개 RSS. 제목·링크·시간만, 키·로그인 없음.
- 같은 소식은 news_pool.cluster 로 묶는다(몇 곳이 다뤘나). 행사·해커톤 같은 공지는 뺀다.
"""
import html
import re
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

import news_pool

UA = {"User-Agent": "Mozilla/5.0 (content-lab research bot)"}
FEEDS = {
    "crypto": [
        ("블록미디어", "KR", "https://www.blockmedia.co.kr/feed"),
        ("토큰포스트", "KR", "https://www.tokenpost.kr/rss"),
        ("코인텔레그래프", "US", "https://cointelegraph.com/rss"),
    ],
}
JUNK = re.compile(r"해커톤|밋업|컨퍼런스|웨비나|이벤트|AMA|참가자 모집|에어드랍|채용|후원|시상|"
                  r"\bhackathon\b|\bmeetup\b|\bwebinar\b|\bsponsored\b|price prediction", re.I)


def _tag(it, tag):
    m = re.search(rf"(?s)<{tag}>(.*?)</{tag}>", it)
    return html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", m.group(1))).strip() if m else ""


def read(pool, hours=8):
    """그 소재 풀의 최근 기사 → rows (news_pool.cluster 재료). 못 읽는 피드는 건너뜀."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = []
    for name, region, url in FEEDS.get(pool, []):
        try:
            r = requests.get(url, headers=UA, timeout=15)
            r.raise_for_status()
        except requests.RequestException:
            continue
        for it in re.findall(r"(?s)<item>(.*?)</item>", r.text):
            title, link = _tag(it, "title"), re.sub(r"\?utm_[^#]*$", "", _tag(it, "link"))
            try:
                when = parsedate_to_datetime(_tag(it, "pubDate")).astimezone(timezone.utc)
            except (TypeError, ValueError):
                continue
            if not title or not link or when < since or JUNK.search(title):
                continue
            rows.append({"title": title, "source": name, "link": link, "published": when.isoformat(timespec="seconds"),
                         "region": region, "popular": False})
    return rows


def clusters(pool, hours=8):
    out = news_pool.cluster(read(pool, hours))
    for c in out:
        c["pool"] = pool
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    for p in FEEDS:
        cs = clusters(p)
        print(f"== {p}: 소식 {len(cs)}개")
        for c in cs[:20]:
            print(f"  {c['n']}곳 {c['time']} {c['title'][:60]} ({','.join(c['sources'])})")
