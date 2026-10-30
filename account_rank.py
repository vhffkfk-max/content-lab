"""인스타·쓰레드·X 계정을 경제 분야별로 나누고 점수를 매겨 벤치마킹할 계정을 고른다.

    python account_rank.py          → output/site/acc_rank.json (+ acc_rank_meta.json)

분야: 미국주식 / 국내주식 / 코인 / 부동산 / 금리·환율 / 재테크·절약 / 경제일반
  - 최근 60일 글에 나온 단어로 자동 분류 (글 수 비율이 가장 높은 분야, 30% 미만이거나 세 분야 이상을 절반 넘게 다루면 경제일반)
  - 손으로 정하고 싶으면 config/account_categories.csv (platform,username,category) — 자동보다 우선
  - 인스타는 accounts.csv 의 category 도 따름 (경제일반이라고 적힌 곳만 자동 분류)
점수 (같은 채널 안에서 백분위, 0~100):
  0.40 반응 크기  = 글당 가중 반응 중앙값 (조회수가 대부분 보이는 채널은 반응 0.25 + 조회 중앙값 0.15)
  0.20 반응률    = 가중 반응 ÷ max(팔로워, 1000) 중앙값   → 작은 계정도 잘하면 올라옴 (팔로워 모르면 중간값)
  0.25 히트율    = 채널 상위 20% 반응을 낸 글 비율
  0.15 꾸준함    = 주당 글 수 (7개에서 끝)
글이 5개 미만이면 우연일 수 있어 점수 ×0.85. 등급: S 85↑ / A 70↑ / B 50↑ / C. 글이 3개 미만이면 점수 안 매김.
S·A 계정 중 분야별 상위 8곳은 무료 크롤러(threads_watch·insta_watch)가 더 자주 찾아본다 (bench 목록).
"""
import csv
import json
import re
import statistics as st
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from common import OUTPUT_DIR, ROOT, connect
from threads_score import MEDIA_BIO, MEDIA_NAME, SPAM, hook_of
from topics import topics_of

KST = timezone(timedelta(hours=9))
SITE = OUTPUT_DIR / "site"
OVERRIDE = ROOT / "config" / "account_categories.csv"
DAYS = 60
MIN_POSTS = 3
BENCH_PER_CAT = 8
CATS = {
    "미국주식": ["미국주식", "미장", "미국 주식", "나스닥", "s&p", "다우", "뉴욕증시", "월가", "서학개미", "엔비디아", "테슬라", "애플",
             "마이크로소프트", "구글", "아마존", "팔란티어", "빅테크", "브로드컴", "qqq", "voo", "spy", "schd", "tqqq", "soxl",
             "nasdaq", "nvidia", "nvda", "tesla", "tsla", "apple", "aapl", "microsoft", "amazon", "palantir", "wall street", "stocks"],
    "국내주식": ["국내주식", "국장", "코스피", "코스닥", "삼성전자", "하이닉스", "현대차", "2차전지", "이차전지", "에코프로", "상한가",
             "밸류업", "동학개미", "공모주", "셀트리온", "한화", "lg에너지", "kospi", "kosdaq"],
    "코인": ["비트코인", "이더리움", "코인", "알트", "리플", "솔라나", "업비트", "바이낸스", "빗썸", "도지", "밈코인", "크립토", "가상자산",
           "bitcoin", "btc", "ethereum", "eth", "crypto", "xrp", "solana", "altcoin", "memecoin"],
    "부동산": ["부동산", "아파트", "전세", "월세", "청약", "집값", "분양", "재건축", "재개발", "주담대", "경매", "갭투자", "매매가", "임대",
            "real estate", "housing", "mortgage"],
    "금리·환율": ["금리", "기준금리", "연준", "fomc", "파월", "환율", "달러", "물가", "인플레이션", "경기침체", "국채", "관세", "금값",
              "fed", "inflation", "recession", "tariff", "tariffs", "treasury", "cpi"],
    "재테크·절약": ["재테크", "가계부", "절약", "짠테크", "적금", "예금", "월급", "연봉", "연말정산", "절세", "isa", "irp", "연금",
               "부업", "n잡", "파이어족", "저축", "사회초년생", "personal finance", "budget", "saving", "401k", "roth"],
}
CAT_NAMES = list(CATS) + ["경제일반"]
WORD = re.compile(r"^[a-z0-9&+ ]+$")
PATTERNS = {c: [re.compile(r"(?<![a-z])" + re.escape(k) + r"(?![a-z])") if WORD.match(k) else re.compile(re.escape(k)) for k in ks]
            for c, ks in CATS.items()}
FORMAT = {("VIDEO", "REELS"): "릴스", ("CAROUSEL_ALBUM", "FEED"): "카드뉴스", ("IMAGE", "FEED"): "사진"}


def cats_of(text):
    t = (text or "").lower()
    return [c for c, ps in PATTERNS.items() if any(p.search(t) for p in ps)]


def korean(text):
    t = re.sub(r"\s", "", text or "")
    return bool(t) and len(re.findall(r"[가-힣]", t)) / len(t) > 0.15


def ts(s):
    s = (s or "").replace("Z", "+00:00")
    if re.search(r"[+-]\d{4}$", s):
        s = s[:-2] + ":" + s[-2:]
    return datetime.fromisoformat(s)


# ── 채널별 글 모으기: 계정 → [{text, e, views, dt, url, fmt}] ──
def load(conn, since):
    accs = defaultdict(lambda: {"posts": [], "followers": None, "name": "", "bio": "", "csv_cat": None})
    ig_csv = {}
    if (ROOT / "accounts.csv").exists():
        with open(ROOT / "accounts.csv", encoding="utf-8") as f:
            ig_csv = {r["username"].strip().lstrip("@"): r.get("category") for r in csv.DictReader(f) if r.get("username")}
    ig_acc = {r[0]: r for r in conn.execute("SELECT username, followers, name, biography FROM accounts")}
    for u, cap, mt, pt, t, link, likes, comments, views in conn.execute(
            "SELECT username, caption, media_type, product_type, timestamp, permalink, likes, comments, views FROM posts"):
        dt = ts(t)
        if dt < since:
            continue
        a = accs[("instagram", u)]
        row = ig_acc.get(u)
        a["followers"], a["name"], a["bio"] = (row[1], row[2] or "", row[3] or "") if row else (None, "", "")
        a["csv_cat"] = ig_csv.get(u)
        a["posts"].append({"text": cap or "", "e": (likes or 0) + 2 * (comments or 0), "views": views, "dt": dt, "url": link,
                           "fmt": FORMAT.get((mt, pt), "사진")})
    for r in conn.execute("SELECT username, text, posted_at, url, likes, replies, reposts, quotes, shares, views, followers, "
                          "display_name, bio, is_reply, source FROM threads_apify"):
        u, text, posted, url, likes, replies, reposts, quotes, shares, views, followers, name, bio, is_reply, source = r
        if is_reply or not posted or source == "내 계정":
            continue
        dt = ts(posted)
        if dt < since:
            continue
        a = accs[("threads", u)]
        a["followers"] = followers or a["followers"]
        a["name"], a["bio"] = name or a["name"], bio or a["bio"]
        a["posts"].append({"text": text or "", "e": (likes or 0) + 2 * (replies or 0) + 3 * ((reposts or 0) + (quotes or 0) + (shares or 0)),
                           "views": views, "dt": dt, "url": (url or "").replace("threads.net", "threads.com"), "fmt": "글"})
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "x_posts" in tables:
        for r in conn.execute("SELECT platform, username, name, followers, grp, text, created_at, views, likes, reposts, replies, quotes, "
                              "bookmarks, url, is_repost FROM x_posts"):
            plat, u, name, followers, grp, text, created, views, likes, reposts, replies, quotes, bm, url, rp = r
            if rp or not created:
                continue
            dt = ts(created)
            if dt < since:
                continue
            a = accs[("x" if (plat or "x").lower() == "x" else "truth", u)]
            a["followers"], a["name"] = followers or a["followers"], name or a["name"]
            a["posts"].append({"text": text or "", "e": (likes or 0) + 2 * (replies or 0) + 3 * ((reposts or 0) + (quotes or 0)) + 2 * (bm or 0),
                               "views": views, "dt": dt, "url": url, "fmt": "글"})
    return accs


def overrides():
    if not OVERRIDE.exists():
        return {}
    with open(OVERRIDE, encoding="utf-8") as f:
        return {(r["platform"].strip().lower(), r["username"].strip().lstrip("@")): r["category"].strip()
                for r in csv.DictReader(f) if (r.get("username") or "").strip() and (r.get("category") or "").strip() in CAT_NAMES}


def classify(posts):
    hits = Counter()
    for p in posts:
        hits.update(set(cats_of(p["text"])))
    n = len(posts) or 1
    mix = [{"cat": c, "share": round(k / n * 100)} for c, k in hits.most_common(3)]
    if len(mix) >= 3 and mix[2]["share"] >= 50:     # 매일 시황 정리처럼 여러 분야를 다 다루면 경제일반(종합)
        return "경제일반", mix
    return (mix[0]["cat"] if mix and mix[0]["share"] >= 30 else "경제일반"), mix


def pct_rank(values):
    """값 → 같은 목록 안 백분위(0~100)."""
    s = sorted(values)
    n = len(s)
    return lambda v: 100.0 * sum(x <= v for x in s) / n if n else 0


def best_hour(posts):
    by = defaultdict(list)
    for p in posts:
        by[p["dt"].astimezone(KST).hour].append(p["e"])
    good = {h: st.median(v) for h, v in by.items() if len(v) >= 2}
    if not good:
        return None
    h = max(good, key=good.get)
    return f"{h}시"


def build(conn, now=None):
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=DAYS)
    accs = load(conn, since)
    manual = overrides()
    weeks = DAYS / 7
    rows = []
    for (plat, user), a in accs.items():
        seen, posts = set(), []          # 같은 글이 수집 경로별로 두 번 들어온 것 빼기 (반응 큰 쪽만)
        for p in sorted(a["posts"], key=lambda p: p["e"], reverse=True):
            key = (p["url"] or "").split("?")[0].rstrip("/") or re.sub(r"\W", "", p["text"])[:60]
            if key not in seen:
                seen.add(key)
                posts.append(p)
        if len(posts) < MIN_POSTS:
            continue
        text_all = " ".join(p["text"] for p in posts)
        econ = sum(bool(cats_of(p["text"]) or topics_of(p["text"]) not in ([], ["기타"])) for p in posts) / len(posts)
        if plat == "threads" and econ < 0.4:      # 쓰레드는 검색으로 걸린 비경제 계정이 많아 경제 글 40% 이상만
            continue
        if SPAM.search(text_all[:5000]) and plat == "threads":
            continue
        cat, mix = classify(posts)
        if plat == "instagram" and a["csv_cat"] in CAT_NAMES and a["csv_cat"] != "경제일반":
            cat = a["csv_cat"]
        cat = manual.get((plat, user), cat)
        es = [p["e"] for p in posts]
        f = a["followers"]
        media = bool(MEDIA_NAME.search(f"{user} {a['name']}") or MEDIA_BIO.search(a["bio"] or ""))
        top = sorted(posts, key=lambda p: p["e"], reverse=True)[:3]
        # 잘 된 글 5개의 첫 줄 유형 (평서형은 특징이 아니라 다른 유형이 있으면 그걸 보여 줌)
        hooks = Counter(h for h in (hook_of(p["text"]) for p in sorted(posts, key=lambda p: p["e"], reverse=True)[:5]) if h != "평서형")
        rows.append({
            "platform": plat, "username": user, "name": a["name"], "followers": f, "category": cat, "mix": mix,
            "region": "한국" if sum(korean(p["text"]) for p in posts) >= len(posts) / 2 else "해외", "media": media,
            "posts": len(posts), "per_week": round(len(posts) / weeks, 1),
            "med_e": round(st.median(es)), "rate": round(st.median(es) / max(f, 1000) * 100, 2) if f else None,
            "views_med": round(st.median([p["views"] for p in posts if p["views"]])) if any(p["views"] for p in posts) else None,
            "best_hour": best_hour(posts), "formats": dict(Counter(p["fmt"] for p in posts).most_common()),
            "top_hook": hooks.most_common(1)[0][0] if hooks else "평서형",
            "topics": [t for t, _ in Counter(t for p in posts for t in topics_of(p["text"]) if t != "기타").most_common(3)],
            "avg_len": round(st.mean(len(p["text"]) for p in posts)),
            "last": max(p["dt"] for p in posts).astimezone(KST).strftime("%m/%d"),
            "best": [{"url": p["url"], "text": re.sub(r"\s+", " ", p["text"])[:90], "e": p["e"], "views": p["views"], "fmt": p["fmt"],
                      "date": p["dt"].astimezone(KST).strftime("%m/%d")} for p in top],
            "_es": es,
        })
    # 채널 안에서 백분위로 점수
    for plat in {r["platform"] for r in rows}:
        rs = [r for r in rows if r["platform"] == plat]
        all_e = sorted(e for r in rs for e in r["_es"])
        cut = all_e[int(len(all_e) * 0.8)] if all_e else 0
        for r in rs:
            r["hit"] = round(sum(e >= cut and e > 0 for e in r["_es"]) / len(r["_es"]) * 100)
        size, hit, act = (pct_rank([r[k] for r in rs]) for k in ("med_e", "hit", "per_week"))
        rate = pct_rank([r["rate"] for r in rs if r["rate"] is not None])
        views = pct_rank([r["views_med"] for r in rs if r["views_med"]])
        has_views = sum(bool(r["views_med"]) for r in rs) >= len(rs) / 2    # 쓰레드처럼 조회수가 거의 다 보이면 크기에 조회도 반영
        for r in rs:
            big = (0.25 * size(r["med_e"]) + 0.15 * (views(r["views_med"]) if r["views_med"] else 50)) if has_views else 0.40 * size(r["med_e"])
            s = (big + 0.20 * (rate(r["rate"]) if r["rate"] is not None else 50) + 0.25 * hit(r["hit"])
                 + 0.15 * act(min(r["per_week"], 7)))
            r["score"] = round(s * (1 if r["posts"] >= 5 else 0.85))
            r["grade"] = "S" if r["score"] >= 85 else "A" if r["score"] >= 70 else "B" if r["score"] >= 50 else "C"
    for r in rows:
        r.pop("_es")
    rows.sort(key=lambda r: r["score"], reverse=True)
    # 분야별 벤치마킹 대상 (한국 계정, 언론 빼고, S·A 중 상위)
    bench = defaultdict(list)
    for r in rows:
        key = (r["platform"], r["category"])
        if r["grade"] in ("S", "A") and r["region"] == "한국" and not r["media"] and len(bench[key]) < BENCH_PER_CAT:
            bench[key].append(r["username"])
            r["bench"] = True
    meta = {"updated": now.astimezone(KST).strftime("%Y-%m-%d %H:%M"), "days": DAYS, "cats": CAT_NAMES,
            "counts": {p: dict(Counter(r["category"] for r in rows if r["platform"] == p)) for p in ("instagram", "threads", "x", "truth")},
            "bench": {p: sorted({u for (pl, _), us in bench.items() if pl == p for u in us}) for p in ("instagram", "threads", "x", "truth")}}
    return rows, meta


def bench_accounts(platform):
    """무료 크롤러가 더 자주 볼 계정 (acc_rank_meta.json 의 bench). 파일이 없으면 빈 목록."""
    try:
        return json.loads((SITE / "acc_rank_meta.json").read_text(encoding="utf-8"))[0]["bench"].get(platform, [])
    except (OSError, ValueError, KeyError, IndexError):
        return []


def main():
    conn = connect()
    rows, meta = build(conn)
    SITE.mkdir(parents=True, exist_ok=True)
    (SITE / "acc_rank.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    (SITE / "acc_rank_meta.json").write_text(json.dumps([meta], ensure_ascii=False, indent=1), encoding="utf-8")
    for p, c in meta["counts"].items():
        print(f"  {p}: {sum(c.values())}곳 {c}")
    print(f"✅ 계정 순위: {len(rows)}곳, 벤치마킹 대상 {sum(len(v) for v in meta['bench'].values())}곳")


if __name__ == "__main__":
    main()
