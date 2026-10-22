"""경제 매체 공식 RSS(인베스팅닷컴 한국어판·국내 경제지·해외 경제 매체)를 수집한다. 키·로그인 필요 없음.

    python press_collect.py
제목·링크·시간만 저장하고 기사 본문은 가져오지 않는다.
다음 금융처럼 공식 RSS가 없는 곳은 그 기사를 쓰는 언론사의 RSS로 대신한다.
"""
import hashlib
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from common import connect
from google_collect import fetch
from topics import topics_of

ATOM = "{http://www.w3.org/2005/Atom}"

# (출처, 분야, 지역, 주소)
FEEDS = [
    ("인베스팅닷컴", "주식 시장", "KR", "https://kr.investing.com/rss/news_25.rss"),
    ("인베스팅닷컴", "경제", "KR", "https://kr.investing.com/rss/news_14.rss"),
    ("인베스팅닷컴", "경제 지표", "KR", "https://kr.investing.com/rss/news_95.rss"),
    ("인베스팅닷컴", "실적 발표", "KR", "https://kr.investing.com/rss/news_1062.rss"),
    ("인베스팅닷컴", "암호화폐", "KR", "https://kr.investing.com/rss/news_301.rss"),
    ("인베스팅닷컴", "외환", "KR", "https://kr.investing.com/rss/news_1.rss"),
    ("인베스팅닷컴", "많이 본 기사", "KR", "https://kr.investing.com/rss/news_285.rss"),
    ("연합뉴스", "경제", "KR", "https://www.yna.co.kr/rss/economy.xml"),
    ("연합뉴스", "마켓", "KR", "https://www.yna.co.kr/rss/market.xml"),
    ("한국경제", "증권", "KR", "https://www.hankyung.com/feed/finance"),
    ("한국경제", "경제", "KR", "https://www.hankyung.com/feed/economy"),
    ("매일경제", "증권", "KR", "https://www.mk.co.kr/rss/50200011/"),
    ("매일경제", "경제", "KR", "https://www.mk.co.kr/rss/30100041/"),
    ("이데일리", "증권", "KR", "http://rss.edaily.co.kr/stock_news.xml"),
    ("조선비즈", "전체", "KR", "https://biz.chosun.com/arc/outboundfeeds/rss/?outputType=xml"),
    ("CNBC", "Top News", "US", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114"),
    ("CNBC", "Markets", "US", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258"),
    ("MarketWatch", "Top Stories", "US", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("CoinDesk", "Crypto", "US", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS press_news (
    id TEXT PRIMARY KEY, source TEXT, section TEXT, region TEXT, title TEXT, link TEXT,
    published TEXT, topics TEXT, collected_at TEXT
);
"""


def when(text):
    if not text:
        return None
    try:
        return parsedate_to_datetime(text).astimezone(timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        try:  # Atom 은 ISO 날짜. 인베스팅닷컴은 시간대 표시 없이 UTC 로 준다
            d = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
            return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")
        except ValueError:
            return None


def items_of(root):
    for it in root.findall(".//item"):
        yield it.findtext("title"), it.findtext("link"), it.findtext("pubDate")
    for it in root.findall(f".//{ATOM}entry"):
        link = it.find(f"{ATOM}link")
        yield it.findtext(f"{ATOM}title"), link.get("href") if link is not None else "", it.findtext(f"{ATOM}updated")


def main():
    conn = connect()
    conn.executescript(SCHEMA)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    total = 0
    for source, section, region, url in FEEDS:
        root = fetch(url)
        if root is None:
            continue
        n = 0
        for title, link, pub in items_of(root):
            title = re.sub(r"\s+", " ", (title or "")).strip()
            if not title or not link:
                continue
            tps = [t for t in topics_of(title) if t != "기타"]
            # '많이 본 기사'는 같은 기사가 다른 분야에도 있어서, 인기 표시만 덧붙이고 덮어쓰지 않는다
            conn.execute(
                "INSERT INTO press_news VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "section = CASE WHEN excluded.section = '많이 본 기사' THEN press_news.section || ' · 많이 본 기사' "
                "ELSE press_news.section END, collected_at = excluded.collected_at",
                (hashlib.sha1(link.strip().encode()).hexdigest()[:16], source, section, region, title, link.strip(),
                 when(pub), ", ".join(tps), now))
            n += 1
        total += n
        print(f"✅ {source} {section}: {n}건")
    conn.commit()
    print(f"\n완료: 매체 기사 {total}건 확인")


if __name__ == "__main__":
    main()
