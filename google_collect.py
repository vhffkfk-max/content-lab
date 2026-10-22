"""구글 뉴스 RSS(주제별 기사)와 구글 트렌드 RSS(급상승 검색어)를 수집한다. 키·로그인 필요 없음.

    python google_collect.py
같은 기사·검색어는 한 번만 저장되고, 매일 돌리면 추세가 쌓인다.
"""
import hashlib
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from common import connect
from topics import TOPICS, topics_of

UA = {"User-Agent": "Mozilla/5.0 (content-lab research bot)"}
TRENDS_NS = {"ht": "https://trends.google.com/trending/rss"}
EDITIONS = {"KR": "hl=ko&gl=KR&ceid=KR:ko", "US": "hl=en-US&gl=US&ceid=US:en"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS google_news (
    id TEXT, topic TEXT, region TEXT, title TEXT, source TEXT, published TEXT, link TEXT, collected_at TEXT,
    PRIMARY KEY (id, topic)
);
CREATE TABLE IF NOT EXISTS google_daily (
    date TEXT, topic TEXT, region TEXT, n INTEGER, per_day REAL, PRIMARY KEY (date, topic, region)
);
CREATE TABLE IF NOT EXISTS google_trends (
    geo TEXT, term TEXT, traffic INTEGER, published TEXT, news_title TEXT, news_link TEXT, collected_at TEXT,
    PRIMARY KEY (geo, term, published)
);
"""


def fetch(url):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                return ET.fromstring(r.read())
        except Exception as e:  # 네트워크 일시 오류는 다시 시도, 그래도 안 되면 그 항목만 건너뜀
            if attempt == 2:
                print(f"⚠️  건너뜀: {url[:80]}… ({e})")
                return None
            time.sleep(3 * (attempt + 1))


# 캡션용 키워드가 뉴스 검색엔 너무 넓은 주제(예: '실적'은 지자체 실적 기사까지 걸림)는 검색어를 따로 정한다
NEWS_QUERIES = {
    "실적발표": {"KR": '"실적 발표" OR 잠정실적 OR 어닝서프라이즈 OR 어닝쇼크', "US": "earnings report OR earnings beat OR guidance"},
    "국내 대형주": {"KR": '"삼성전자 주가" OR 코스피 OR "SK하이닉스 주가" OR "현대차 주가"', "US": '"Samsung Electronics" OR KOSPI OR "SK Hynix"'},
    "초보·투자마인드": {"KR": '"투자 초보" OR "재테크 초보" OR "투자 입문" OR 복리', "US": '"beginner investors" OR "investing for beginners" OR "compound interest"'},
    "연금·절세": {"KR": '연금저축 OR 퇴직연금 OR "ISA 계좌" OR 절세', "US": '"Roth IRA" OR 401k OR "tax-loss harvesting"'},
    "급락·변동성": {"KR": '"증시 급락" OR 폭락 OR "변동성 확대" OR 공포지수', "US": '"stock market sell-off" OR "market crash" OR VIX'},
    "정치·관세": {"KR": '관세 OR "트럼프 관세" OR "무역 협상"', "US": "tariffs OR \"trade war\""},
    "부동산": {"KR": '아파트 OR 집값 OR 부동산 OR 청약', "US": '"housing market" OR "mortgage rates" OR "home prices"'},
}


def topic_query(words, korean):
    """주제 키워드 중 한글(또는 영어)만 골라 OR 검색어로. 너무 짧은 영어 약어는 엉뚱한 기사가 섞여서 뺀다."""
    picked = [w for w in words if bool(re.search(r"[가-힣]", w)) == korean and (korean or len(w) >= 4)][:4]
    return " OR ".join(f'"{w}"' if " " in w else w for w in picked)


def iso(text):
    try:
        return parsedate_to_datetime(text).astimezone(timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return None


def collect_news(conn, now):
    total = 0
    for topic, words in TOPICS.items():
        for region, edition in EDITIONS.items():
            q = NEWS_QUERIES.get(topic, {}).get(region) or topic_query(words, korean=(region == "KR"))
            if not q:
                continue
            # RSS 는 한 번에 최대 100건이라 7일치는 모든 주제가 100건으로 똑같아진다 → 최근 24시간 기사 수를 매일 기록
            url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q + ' when:1d')}&{edition}"
            root = fetch(url)
            if root is None:
                continue
            n, times = 0, []
            for it in root.findall(".//item"):
                link, source = it.findtext("link") or "", it.findtext("source") or ""
                title = re.sub(rf"\s+-\s+{re.escape(source)}$", "", it.findtext("title") or "") if source else it.findtext("title")
                conn.execute("INSERT OR REPLACE INTO google_news VALUES (?,?,?,?,?,?,?,?)",
                             (hashlib.sha1(link.encode()).hexdigest()[:16], topic, region, title, source,
                              iso(it.findtext("pubDate")), link, now))
                n += 1
                if iso(it.findtext("pubDate")):
                    times.append(datetime.fromisoformat(iso(it.findtext("pubDate"))))
            total += n
            # 100건이 꽉 차면 그 100건이 나온 시간 폭으로 하루 기사량을 추정한다
            span_h = max(1.0, (datetime.now(timezone.utc) - min(times)).total_seconds() / 3600) if times else 24
            per_day = round(n / min(span_h, 24) * 24) if n >= 100 else n
            today = datetime.now(timezone(timedelta(hours=9))).date().isoformat()
            conn.execute("INSERT OR REPLACE INTO google_daily VALUES (?,?,?,?,?)", (today, topic, region, n, per_day))
            print(f"✅ 뉴스 {topic} ({region}): 하루 약 {per_day}건 속도")
            time.sleep(1)
    conn.commit()
    return total


def collect_trends(conn, now):
    for geo in ("KR", "US"):
        root = fetch(f"https://trends.google.com/trending/rss?geo={geo}")
        if root is None:
            continue
        items = root.findall(".//item")
        for it in items:
            news = it.find("ht:news_item", TRENDS_NS)
            traffic = int(re.sub(r"\D", "", it.findtext("ht:approx_traffic", namespaces=TRENDS_NS) or "0") or 0)
            conn.execute("INSERT OR REPLACE INTO google_trends VALUES (?,?,?,?,?,?,?)", (
                geo, it.findtext("title"), traffic, iso(it.findtext("pubDate")),
                news.findtext("ht:news_item_title", namespaces=TRENDS_NS) if news is not None else "",
                news.findtext("ht:news_item_url", namespaces=TRENDS_NS) if news is not None else "", now))
        econ = sum(1 for it in items if topics_of(it.findtext("title")) != ["기타"])
        print(f"✅ 트렌드 {geo}: 급상승 검색어 {len(items)}개 (경제 관련 {econ}개)")
    conn.commit()


def main():
    conn = connect()
    conn.executescript(SCHEMA)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    total = collect_news(conn, now)
    collect_trends(conn, now)
    print(f"\n완료: 뉴스 {total}건 확인")


if __name__ == "__main__":
    main()
