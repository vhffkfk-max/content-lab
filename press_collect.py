"""경제 매체 공식 RSS(인베스팅닷컴 한국어판·국내 경제지·해외 경제 매체)를 수집한다. 키·로그인 필요 없음.

    python press_collect.py
제목·링크·시간만 저장하고 기사 본문은 가져오지 않는다.
다음 뉴스는 RSS가 없어서 경제 속보 면의 제목·링크·언론사만 읽는다 (DAUM_PAGES).
"""
import hashlib
import html
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from common import connect
from google_collect import UA, fetch
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
    ("머니투데이", "전체", "KR", "https://rss.mt.co.kr/mt_news.xml"),
    ("서울경제", "경제", "KR", "https://www.sedaily.com/rss/Economy"),
    ("아시아경제", "증권", "KR", "https://www.asiae.co.kr/rss/stock.htm"),
    ("아시아경제", "경제", "KR", "https://www.asiae.co.kr/rss/economy.htm"),
    ("헤럴드경제", "금융", "KR", "https://biz.heraldcorp.com/rss/google/finance"),
    ("파이낸셜뉴스", "증권", "KR", "https://www.fnnews.com/rss/r20/fn_realnews_stock.xml"),
    ("파이낸셜뉴스", "경제", "KR", "https://www.fnnews.com/rss/r20/fn_realnews_economy.xml"),
    ("뉴시스", "경제", "KR", "https://www.newsis.com/RSS/economy.xml"),
    ("뉴시스", "금융", "KR", "https://www.newsis.com/RSS/bank.xml"),
    ("연합인포맥스", "전체", "KR", "https://news.einfomax.co.kr/rss/allArticle.xml"),
    ("연합인포맥스", "많이 본 기사", "KR", "https://news.einfomax.co.kr/rss/clickTop.xml"),
    ("이투데이", "증권", "KR", "https://rss.etoday.co.kr/eto/market_news.xml"),
    ("동아일보", "경제", "KR", "https://rss.donga.com/economy.xml"),
    ("SBS Biz", "경제", "KR", "https://news.sbs.co.kr/news/SectionRssFeed.do?sectionId=02&plink=RSSREADER"),
    ("Bloomberg", "Markets", "US", "https://feeds.bloomberg.com/markets/news.rss"),
    ("Bloomberg", "Economics", "US", "https://feeds.bloomberg.com/economics/news.rss"),
    ("Financial Times", "Markets", "US", "https://www.ft.com/markets?format=rss"),
    ("Seeking Alpha", "Market Currents", "US", "https://seekingalpha.com/market_currents.xml"),
    ("연준", "보도자료", "US", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("CNBC", "Top News", "US", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114"),
    ("CNBC", "Markets", "US", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258"),
    ("MarketWatch", "Top Stories", "US", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("CoinDesk", "Crypto", "US", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
]

DAUM_PAGES = ["https://news.daum.net/breakingnews/economy", "https://news.daum.net/economy"]

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


def daum_items(page):
    """다음 뉴스 면 → (제목, 링크, 언론사, 시각). 기사 번호 앞 14자리가 한국시간."""
    try:
        with urllib.request.urlopen(urllib.request.Request(page, headers=UA), timeout=30) as r:
            text = r.read().decode("utf-8", "ignore")
    except Exception as e:
        print(f"⚠️  건너뜀: {page} ({e})")
        return
    for m in re.finditer(r'<a\b[^>]*href="(https://v\.daum\.net/v/(\d{14})\d*)"[^>]*data-title="([^"]*)"[^>]*>(.*?)</a>', text, re.S):
        src = re.search(r'class="txt_info">([^<]+)<', m[4])
        title = html.unescape(urllib.parse.unquote(m[3]))
        try:
            pub = datetime.strptime(m[2], "%Y%m%d%H%M%S").replace(tzinfo=timezone(timedelta(hours=9))).astimezone(timezone.utc)
        except ValueError:
            continue
        yield title, m[1], src[1].strip() if src else "다음", pub.isoformat(timespec="seconds")


def collect_daum(conn, now):
    n = 0
    for page in DAUM_PAGES:
        for title, link, outlet, pub in daum_items(page):
            title = re.sub(r"\s+", " ", title).strip()
            tps = [t for t in topics_of(title) if t != "기타"]
            conn.execute("INSERT INTO press_news VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET collected_at = excluded.collected_at",
                         (hashlib.sha1(link.encode()).hexdigest()[:16], "다음 뉴스", outlet, "KR", title, link, pub, ", ".join(tps), now))
            n += 1
    print(f"✅ 다음 뉴스 경제: {n}건")
    return n


def main():
    conn = connect()
    conn.executescript(SCHEMA)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    soon = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(timespec="seconds")
    total = 0
    for source, section, region, url in FEEDS:
        root = fetch(url)
        if root is None:
            continue
        n = 0
        for title, link, pub in items_of(root):
            title = re.sub(r"\s+", " ", html.unescape(title or "")).strip()
            if not title or not link:
                continue
            tps = [t for t in topics_of(title) if t != "기타"]
            pub_at = when(pub)
            if pub_at and pub_at > soon:   # 시간대 표시 없이 한국시간을 주는 곳(헤럴드경제·연합인포맥스)
                pub_at = (datetime.fromisoformat(pub_at) - timedelta(hours=9)).isoformat(timespec="seconds")
            # '많이 본 기사'는 같은 기사가 다른 분야에도 있어서, 인기 표시만 덧붙이고 덮어쓰지 않는다
            conn.execute(
                "INSERT INTO press_news VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "section = CASE WHEN excluded.section = '많이 본 기사' THEN press_news.section || ' · 많이 본 기사' "
                "ELSE press_news.section END, collected_at = excluded.collected_at",
                (hashlib.sha1(link.strip().encode()).hexdigest()[:16], source, section, region, title, link.strip(),
                 pub_at, ", ".join(tps), now))
            n += 1
        total += n
        print(f"✅ {source} {section}: {n}건")
    total += collect_daum(conn, now)
    conn.commit()
    print(f"\n완료: 매체 기사 {total}건 확인")


if __name__ == "__main__":
    main()
