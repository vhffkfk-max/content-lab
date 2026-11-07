"""블로그 글 ↔ 오뉴월드 게시물 짝짓기.

기준: 게시 시차(블로그 글 하루 전 ~ 7일 뒤)와 공통 낱말·숫자. 드문 낱말(종목명 등)에 점수를 더 준다.
점수만으로 틀릴 수 있어 '확실 / 검토'로 나눈다. 분석/수동짝.csv (블로그id,게시물id) 가 있으면 그것을 먼저 쓴다.
"""
import csv
import math
import re
from collections import Counter
from datetime import datetime

from studio.paths import CONFIG

STOP = set("그리고 그러나 하지만 그런데 이번 오늘 어제 지금 최근 시장 주가 주식 투자 관련 대한 때문 정도 이후 이상 이하 여러분 생각 어떠세요 댓글 의견 저장 차트 흐름 확인 경우 가능성".split())
JOSA = re.compile(r"(은|는|이|가|을|를|의|에|도|로|으로|와|과|만|에서|까지|부터|보다|처럼|이나|라는|이라는|하며|했다|합니다|입니다|습니다|해요|어요)$")


def tokens(text):
    out = set()
    for w in re.findall(r"[A-Za-z][A-Za-z&]+|[가-힣]{2,}|\d[\d,.]*\d", text or ""):
        w = JOSA.sub("", w) if re.match(r"[가-힣]", w) else w.lower()
        if len(w) >= 2 and w not in STOP:
            out.add(w.replace(",", ""))
    return out


def _dt(s):
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def score_pairs(blogs, posts, before=None, after=None):
    before = CONFIG["match_days_before"] if before is None else before
    after = CONFIG["match_days_after"] if after is None else after
    btok = {b["id"]: tokens(b.get("title", "") + " " + b.get("text", "")[:1500]) for b in blogs}
    ptok = {p["id"]: tokens(p.get("caption", "")) for p in posts}
    df = Counter(t for s in list(btok.values()) + list(ptok.values()) for t in s)
    n = max(1, len(blogs) + len(posts))
    idf = lambda t: math.log((n + 1) / (df[t] + 1)) + .2
    rows = []
    for b in blogs:
        bd = _dt(b.get("date"))
        title_tok = tokens(b.get("title", ""))
        for p in posts:
            pd = _dt(p.get("date"))
            if not (bd and pd):
                continue
            lag = (pd - bd).total_seconds() / 86400
            if not -before <= lag <= after:
                continue
            common = btok[b["id"]] & ptok[p["id"]]
            if not common:
                continue
            base = sum(idf(t) for t in ptok[p["id"]]) or 1
            s = sum(idf(t) for t in common) / base
            s += .15 * len(title_tok & ptok[p["id"]])
            s += .1 * sum(1 for t in common if t[0].isdigit())
            s *= 1 - .05 * max(0, lag)
            rows.append({"blog": b["id"], "post": p["id"], "score": round(s, 3), "lag_days": round(lag, 2), "common": sorted(common, key=idf, reverse=True)[:6]})
    return sorted(rows, key=lambda r: -r["score"])


def assign(blogs, posts, manual=None, sure=.55, maybe=.25):
    """점수 높은 순으로 1:1 배정. manual = [(블로그id, 게시물id)]."""
    pairs, used_b, used_p = [], set(), set()
    for b, p in manual or []:
        pairs.append({"blog": b, "post": p, "score": None, "lag_days": None, "common": [], "level": "수동"})
        used_b.add(b)
        used_p.add(p)
    for r in score_pairs(blogs, posts):
        if r["blog"] in used_b or r["post"] in used_p or r["score"] < maybe:
            continue
        pairs.append({**r, "level": "확실" if r["score"] >= sure else "검토"})
        used_b.add(r["blog"])
        used_p.add(r["post"])
    return pairs


def load_manual(path):
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            return [(r[0].strip(), r[1].strip()) for r in csv.reader(f) if len(r) >= 2 and r[0].strip() and r[0].strip() != "블로그id"]
    except OSError:
        return []
