"""쓰레드 자동 수집 글 점수·등급·잡음 거르기 (analyze.py 가 부름).

지표 (조회수 기준):
  가중 반응  = 좋아요 + 2×답글 + 3×리포스트 + 3×인용 + 3×공유
  반응률     = 가중 반응 ÷ 조회
  확산배수   = 조회 ÷ max(팔로워, 300)          → 팔로워 밖으로 퍼졌는지 (바이럴 신호)
  조회 속도  = 조회 ÷ max(올린 지 몇 시간, 1)
점수 = 같은 나이 구간(0~6시간, 6~24시간, 1~3일, 3~7일) 안 백분위로 0.45×확산배수 + 0.35×반응률 + 0.20×조회 속도
등급: 바이럴(조회 1만↑·확산 5배↑·반응률 2%↑) / 따라 할 가치(점수 70↑·조회 2천↑·반응률 3%↑) /
      조회 대기(조회수 미공개인데 가중 반응 ÷ max(팔로워,300) ≥ 5%)
기준값은 추정치 — 데이터가 한 달 쌓이면 우리 중앙값으로 바꾼다.
"""
import re
import statistics as st
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from topics import topics_of

KST = timezone(timedelta(hours=9))
MEDIA_NAME = re.compile(r"news|뉴스|일보|신문|방송|미디어|media|tv|press|경제지|매거진|magazine", re.I)
MEDIA_BIO = re.compile(r"기자|언론|보도|제보|공식\s*계정|official account|신문사|방송사")
SPAM = re.compile(r"리딩방|수익\s*보장|추천인|추천\s*코드|오픈\s*채팅|open\.kakao|무료\s*종목|vip\s*방|선착순|수익\s*인증|문의\s*주세요", re.I)
POLITICS = re.compile(r"검찰|살인|국회|탄핵|선거|대통령|범죄|경찰|재판|구속|정당|의원")
AGE_BUCKETS = [(0, 6, "6시간 안"), (6, 24, "하루 안"), (24, 72, "1~3일"), (72, 168, "3~7일")]


def hook_of(text):
    first = (text or "").strip().split("\n")[0][:80]
    if not first:
        return "본문 없음"
    if re.search(r"속보|단독|긴급|방금|\[breaking", first, re.I):
        return "속보형"
    if re.search(r"주의|조심|절대|경고|위험|하지\s*마|망한|큰일", first):
        return "경고형"
    if re.search(r"저는|제가|나는|내가|했더니|해보니|해봤|월급|제\s*계좌", first):
        return "경험형"
    if first.rstrip().endswith(("?", "까요", "나요", "죠", "니")) or "?" in first:
        return "질문형"
    if re.search(r"\d+\s*(가지|개|%|억|만|배|년|위|원|달러|번)", first):
        return "숫자형"
    if re.search(r"사실|오히려|틀렸|아닙니다|착각|모르는|진짜 이유", first):
        return "반전형"
    return "평서형"


def length_of(text):
    n = len(text or "")
    return "100자 미만" if n < 100 else "100~300자" if n < 300 else "300~500자" if n < 500 else "500자 이상"


def is_media(r):
    name = f"{r['username'] or ''} {r['display_name'] or ''}"
    return bool(MEDIA_NAME.search(name) or MEDIA_BIO.search(r["bio"] or ""))


def excluded_reason(r):
    # 언론 계정도 경제 뉴스면 남긴다 (경제 뉴스로 조회수가 잘 나온 글도 참고 대상) — 대신 '언론' 표시
    text = r["text"] or ""
    if SPAM.search(text):
        return "광고·리딩방"
    if len(text.strip()) < 15:
        return "너무 짧음"
    letters = re.findall(r"[^\W\d_]", text)
    if letters and len(re.findall(r"[가-힣]", text)) / len(letters) < 0.3:
        return "한국어 아님"
    econ = [t for t in (r["topics"] or "").split(", ") if t and t not in ("기타", "정치·관세")]
    if not econ or (POLITICS.search(text[:200]) and len(econ) < 2):
        return "경제 주제 아님"
    return None


def pct_rank(values):
    """값 목록 → 각 값의 백분위(0~1)."""
    order = sorted(values)
    n = len(order)
    return [(sum(1 for v in order if v < x) + 0.5 * sum(1 for v in order if v == x)) / n if n else 0 for x in values]


def score_posts(rows, now):
    """rows: threads_apify 행(dict). 지표·점수·등급을 붙여 돌려준다 (거른 글은 excluded 사유)."""
    seen, kept, dropped = set(), [], Counter()
    for r in rows:
        try:
            dt = datetime.fromisoformat((r["posted_at"] or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        key = (r["text"] or "").strip()[:50]
        if key in seen:
            continue
        seen.add(key)
        why = excluded_reason(r)
        if why:
            dropped[why] += 1
            continue
        age_h = max((now - dt).total_seconds() / 3600, 0.1)
        followers = max(r["followers"] or 0, 300)
        weighted = (r["likes"] or 0) + 2 * (r["replies"] or 0) + 3 * (r["reposts"] or 0) + 3 * (r["quotes"] or 0) + 3 * (r["shares"] or 0)
        views = r["views"]
        kept.append(dict(r, dt=dt, media_acct=is_media(r), age_h=age_h, weighted=weighted,
                         rate=weighted / views if views else None, spread=views / followers if views else None,
                         velocity=views / max(age_h, 1) if views else None, pre=weighted / followers,
                         hook=hook_of(r["text"]), length=length_of(r["text"]),
                         bucket=next(name for a, b, name in AGE_BUCKETS if a <= age_h < b or name == "3~7일")))
    for _, _, name in AGE_BUCKETS:
        group = [p for p in kept if p["bucket"] == name and p["views"]]
        if not group:
            continue
        ps, pr, pv = (pct_rank([p[k] for p in group]) for k in ("spread", "rate", "velocity"))
        for p, a, b, c in zip(group, ps, pr, pv):
            p["score"] = round(100 * (0.45 * a + 0.35 * b + 0.20 * c))
    for p in kept:
        p.setdefault("score", None)
        if p["views"] and p["views"] >= 10000 and p["spread"] >= 5 and p["rate"] >= 0.02:
            p["grade"] = "바이럴"
        elif p["views"] and p["score"] is not None and p["score"] >= 70 and p["views"] >= 2000 and p["rate"] >= 0.03:
            p["grade"] = "따라 할 가치"
        elif not p["views"] and p["pre"] >= 0.05:
            p["grade"] = "조회 대기"
        else:
            p["grade"] = ""
    return kept, dropped


def brief(p):
    return {"id": "a_" + p["post_id"], "username": p["username"], "name": p["display_name"] or "", "followers": p["followers"],
            "verified": bool(p["verified"]), "text": (p["text"] or "")[:500], "url": p["url"], "views": p["views"],
            "likes": p["likes"] or 0, "replies": p["replies"] or 0, "reposts": p["reposts"] or 0, "quotes": p["quotes"] or 0,
            "shares": p["shares"] or 0, "rate": round(p["rate"] * 100, 1) if p["rate"] is not None else None,
            "spread": round(p["spread"], 1) if p["spread"] is not None else None,
            "velocity": round(p["velocity"]) if p["velocity"] is not None else None, "score": p["score"], "grade": p["grade"],
            "hook": p["hook"], "length": p["length"], "media": "이미지·영상" if p["has_media"] else "글만",
            "topics": p["topics"] or "", "source": p["source"], "age": p["bucket"], "press": p["media_acct"],
            "time": p["dt"].astimezone(KST).strftime("%m/%d %H:%M")}


def formats(kept):
    """형식별 중앙 확산배수·반응률 (n<10 숨김, n<30 표본 적음)."""
    viewed = [p for p in kept if p["views"]]
    if not viewed:
        return []
    base_s = st.median(p["spread"] for p in viewed)
    out = []
    for dim, key in (("첫 줄", "hook"), ("길이", "length"), ("미디어", "has_media")):
        g = defaultdict(list)
        for p in viewed:
            g[("이미지·영상" if p["has_media"] else "글만") if key == "has_media" else p[key]].append(p)
        for k, ps in g.items():
            if len(ps) < 10:
                continue
            s = st.median(p["spread"] for p in ps)
            out.append({"dim": dim, "key": k, "n": len(ps), "spread": round(s, 2), "rate": round(st.median(p["rate"] for p in ps) * 100, 1),
                        "vs": round(s / base_s, 2) if base_s else None, "small": len(ps) < 30})
    return sorted(out, key=lambda r: (r["dim"], -r["spread"]))


def section(conn, now):
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    empty = {"meta": [], "top": [], "rising": [], "topics": [], "formats": [], "accounts": [], "hot": [], "rank": []}
    if "threads_apify" not in tables:
        return empty
    cols = {r[1] for r in conn.execute("PRAGMA table_info(threads_apify)")}
    if "views" not in cols:
        return empty
    week = (now - timedelta(days=7)).isoformat()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM threads_apify WHERE is_reply = 0 AND posted_at >= ? AND view_status IS NOT NULL", (week,))]
    kept, dropped = score_posts(rows, now)
    ranked = sorted(kept, key=lambda p: (p["score"] or -1, p["views"] or 0), reverse=True)
    top, per_topic = [], Counter()
    for p in ranked:
        if p["grade"] in ("바이럴", "따라 할 가치"):
            t = (p["topics"] or "기타").split(", ")[0]
            if per_topic[t] < 2:
                top.append(p)
                per_topic[t] += 1
        if len(top) >= 5:
            break
    rising = sorted([p for p in kept if p["age_h"] <= 48 and (p["velocity"] or p["grade"] == "조회 대기")],
                    key=lambda p: (p["velocity"] or 0, p["pre"]), reverse=True)[:15]
    topics = []
    for t in ["AI·반도체", "빅테크", "테슬라", "국내 대형주", "실적발표", "비트코인", "알트코인", "금리·연준", "환율·달러",
              "부동산", "ETF·지수투자", "배당", "초보·투자마인드", "연금·절세"]:
        ps = [p for p in ranked if t in (p["topics"] or "").split(", ") and p["views"]][:5]
        topics += [dict(brief(p), topic=t) for p in ps]
    acc = defaultdict(list)
    for p in kept:
        if "계정" in (p["source"] or "") and p["views"]:
            acc[p["username"]].append(p)
    accounts = sorted(({"username": u, "name": ps[0]["display_name"] or "", "followers": ps[0]["followers"], "posts": len(ps),
                        "median_views": round(st.median(p["views"] for p in ps)), "median_spread": round(st.median(p["spread"] for p in ps), 2),
                        "median_rate": round(st.median(p["rate"] for p in ps) * 100, 1)} for u, ps in acc.items()),
                      key=lambda a: -a["median_views"])
    month = now.strftime("%Y-%m")
    results = conn.execute("SELECT COALESCE(SUM(results),0) FROM threads_cost WHERE date LIKE ?", (month + "%",)).fetchone()[0] \
        if "threads_cost" in tables else 0
    meta = [{"collected": max((r["scraped_at"] for r in rows), default=None), "posts": len(rows), "kept": len(kept),
             "with_views": sum(1 for p in kept if p["views"]), "dropped": ", ".join(f"{k} {v}" for k, v in dropped.most_common()), "press": sum(1 for p in kept if p["media_acct"]),
             "viral": sum(1 for p in kept if p["grade"] == "바이럴"), "copy": sum(1 for p in kept if p["grade"] == "따라 할 가치"),
             "pending": sum(1 for p in kept if p["grade"] == "조회 대기"), "month_cost": round(results * 2.5 / 1000, 2)}]
    # 반응 랭킹: 조회수 / 퍼진 정도(리포스트+인용+공유) / 댓글 — 각 10개
    def top_by(key, n=10):
        return [brief(p) for p in sorted(kept, key=key, reverse=True)[:n] if key(p) > 0]
    rank = {"views": top_by(lambda p: p["views"] or 0),
            "shared": top_by(lambda p: (p["reposts"] or 0) + (p["quotes"] or 0) + (p["shares"] or 0)),
            "replied": top_by(lambda p: p["replies"] or 0)}
    return {"meta": meta, "top": [brief(p) for p in top], "rising": [brief(p) for p in rising], "topics": topics,
            "formats": formats(kept), "accounts": accounts, "hot": [brief(p) for p in ranked[:30]],
            "rank": [dict(h, list=k) for k, hs in rank.items() for h in hs]}
