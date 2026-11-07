"""지금 뉴스 묶음 — 매체 RSS·다음·구글 뉴스 기사를 '같은 소식' 하나로 묶어 data/news_pool.json 에 저장 (hot_now.py 재료).

    python news_pool.py   # 묶인 결과 미리 보기

- 같은 소식: 제목의 글자 조각(바이그램)이 충분히 겹치면 하나로 묶고, '몇 곳이 다뤘나'를 남김 — 많이 다룰수록 큰 소식이라는 신호
- 대표 기사: 바로 읽히는 링크(구글 뉴스 우회 주소 말고), 국내 기사 먼저
- 구글 뉴스 걸러내기: 국내판은 한글 제목만, 해외판은 믿을 만한 매체만 (주식 자동 기사·코인 거래소 글 제외)
- 경제 아닌 것 빼기: 종합 피드에 섞인 스포츠·연예·사진 기사, 자동 실적 기사
live_news.py 가 30분마다 만든다 (크롤러가 곧이어 DB 를 되돌리므로 DB 대신 이 파일을 hot_now 가 읽음).
"""
import html
import json
import re
from datetime import datetime, timedelta, timezone

from common import DATA_DIR, connect

OUT = DATA_DIR / "news_pool.json"
KST = timezone(timedelta(hours=9))
HANGUL = re.compile(r"[가-힣]")
TRUSTED_US = {"reuters", "bloomberg", "bloomberg.com", "cnbc", "the wall street journal", "wsj", "financial times", "ft", "associated press", "ap news",
              "barron's", "marketwatch", "yahoo finance", "investing.com", "forbes", "fortune", "axios", "the new york times", "the washington post",
              "bbc", "cnn", "politico", "nikkei asia", "the economist", "business insider", "techcrunch", "the information", "semafor", "coindesk"}
# 제목 앞뒤 꾸밈말은 같은 소식 판단에서 뺌
NOISE = re.compile(r"\[[^\]]{1,12}\]|【[^】]{1,12}】|\([^)]{1,8}\)|속보|단독|종합|특징주|영상|포토|오늘의|(?:\s[-–|]\s[^-–|]{1,30}$)")
SIMILAR, OVERLAP = 0.33, 0.62
MERGE_OVERLAP = 0.5   # 묶음끼리 한 번 더 합칠 때 (작은 쪽 조각 중 이만큼 겹치면 같은 소식)
JUNK_TITLE = re.compile(r"^\s*\[(?:사진|포토|표|한번에|영상|부고|인사|헤드라인|오늘의[^\]]*)\]|외국환율고시표|^실적 발표|reports? (?:Q\d )?(?:results|earnings) tomorrow|^Earnings to watch", re.I)
JUNK_LINK = re.compile(r"/(?:sports?|entertainment|enter|culture)/", re.I)
SAME_SOURCE = {"매일경제 마켓": "매일경제", "Investing.com 한국어": "인베스팅닷컴", "Investing.com": "인베스팅닷컴", "조선일보": "조선비즈"}


def keep(source, title, region):
    """구글 뉴스 기사를 재료로 쓸까."""
    if region == "KR":
        return bool(HANGUL.search(title))
    return (source or "").strip().lower() in TRUSTED_US


def junk(title, link=""):
    """경제 소식이 아닌 것: 사진·스포츠·연예, 자동으로 찍어 내는 실적 기사."""
    return bool(JUNK_TITLE.search(title or "") or JUNK_LINK.search(link or ""))


def grams(title):
    """비교용 조각: 한글은 두 글자씩, 영어·숫자는 낱말째."""
    t = NOISE.sub(" ", title)
    out = set()
    for w in re.findall(r"[가-힣]+|[A-Za-z]+|\d+(?:[.,]\d+)*", t):
        if HANGUL.match(w):
            out |= {w[i:i + 2] for i in range(len(w) - 1)} or {w}
        elif len(w) > 1:
            out.add(w.lower())
    return out


def same(a, b):
    both = len(a & b)
    if not both:
        return False
    return both / len(a | b) >= SIMILAR or (both >= 6 and both / min(len(a), len(b)) >= OVERLAP)


def is_direct(link):
    return "news.google." not in (link or "")


def cluster(rows):
    """rows: {title, source, link, published(UTC ISO), region, popular} → 같은 소식 묶음 (곳 수 많은 순, 같으면 최신 순)."""
    groups = []
    for r in sorted(rows, key=lambda x: x["published"], reverse=True):
        g = grams(r["title"])
        if not g:
            continue
        for c in groups:
            if same(g, c["grams"]):
                c["rows"].append(r)
                c["grams"] |= g if len(c["grams"]) < 40 else set()
                break
        else:
            groups.append({"grams": set(g), "rows": [r]})
    merged = []   # 첫 줄이 달라 따로 묶인 같은 소식을 큰 묶음부터 합침
    for c in sorted(groups, key=lambda c: -len(c["rows"])):
        for m in merged:
            both = len(c["grams"] & m["grams"])
            if both >= 6 and both / min(len(c["grams"]), len(m["grams"])) >= MERGE_OVERLAP:
                m["rows"] += c["rows"]
                break
        else:
            merged.append(c)
    out = []
    for c in merged:
        best = sorted(c["rows"], key=lambda r: (not is_direct(r["link"]), r["region"] != "KR", -len(r["title"])))
        srcs = list(dict.fromkeys(SAME_SOURCE.get(r["source"], r["source"]) for r in best if r["source"]))
        latest = max(r["published"] for r in c["rows"])
        out.append({"title": best[0]["title"], "time": datetime.fromisoformat(latest).astimezone(KST).strftime("%H:%M"), "published": latest,
                    "sources": srcs[:6], "n": len(srcs) or 1, "region": best[0]["region"], "popular": any(r.get("popular") for r in c["rows"]),
                    "links": [r["link"] for r in best if is_direct(r["link"])][:3] or [best[0]["link"]]})
    out.sort(key=lambda x: x["published"], reverse=True)
    out.sort(key=lambda x: (-x["n"], not x["popular"]))
    return out


def dedupe(rows):
    """사이트 기사 목록용 — 같은 소식은 처음 것만 (순서 유지)."""
    seen, out = [], []
    for r in rows:
        g = grams(r.get("title") or "")
        if g and any(same(g, s) for s in seen):
            continue
        if g:
            seen.append(g)
        out.append(r)
    return out


def gather(conn, hours=3):
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    rows, seen = [], set()
    if "press_news" in tables:
        for r in conn.execute("SELECT source, section, region, title, link, published FROM press_news WHERE published >= ?", (since,)):
            if junk(r["title"], r["link"]):
                continue
            src = r["section"] if r["source"] == "다음 뉴스" else r["source"]   # 다음은 실제 언론사로 셈
            rows.append({"title": html.unescape(r["title"]), "source": src, "link": r["link"], "published": r["published"], "region": r["region"],
                         "popular": "많이 본 기사" in (r["section"] or "")})
            seen.add(r["link"])
    if "google_news" in tables:
        for r in conn.execute("SELECT source, region, title, link, published FROM google_news WHERE published >= ?", (since,)):
            title = html.unescape(re.sub(r"\s+-\s+[^-]{1,40}$", "", r["title"] or "")).strip()
            if r["link"] not in seen and keep(r["source"], title, r["region"]) and not junk(title, r["link"]):
                seen.add(r["link"])
                rows.append({"title": title, "source": r["source"], "link": r["link"], "published": r["published"], "region": r["region"], "popular": False})
    return rows


def save(conn):
    rows = gather(conn)
    if len(rows) < 30:   # 주말·새벽엔 범위를 넓힘
        rows = gather(conn, hours=8)
    clusters = cluster(rows)
    OUT.write_text(json.dumps({"at": datetime.now(KST).isoformat(timespec="seconds"), "articles": len(rows), "clusters": clusters},
                              ensure_ascii=False, indent=0), encoding="utf-8")
    return len(rows), len(clusters)


def load(max_age_h=2):
    """저장된 묶음. 없거나 오래됐으면 None."""
    try:
        d = json.loads(OUT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if datetime.now(KST) - datetime.fromisoformat(d["at"]) <= timedelta(hours=max_age_h) else None


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    a, b = save(connect())
    print(f"기사 {a}개 → 소식 {b}개")
    for c in load()["clusters"][:30]:
        print(f"{c['n']}곳 {c['time']} {c['title'][:50]} ({','.join(c['sources'][:4])})")
