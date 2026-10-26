"""우리 쓰레드 계정(황소개미 @bullant_economy) 진단용 숫자 (analyze.py 가 부름).

  thm_meta  : 팔로워·글 수·하루 글 수·조회 추세·비교 기준(남의 경제 글 중앙값)
  thm_posts : 최근 30개 글 (조회·반응률·확산배수·답글/공유 비율·첫 줄 유형·주제·길이)
  thm_feed  : 프로필 첫 화면(최근 12개)의 주제·형식 구성과 반복 경고
"""
import statistics as st
from collections import Counter
from itertools import groupby
from datetime import datetime, timedelta, timezone

from threads_score import hook_of, length_of

KST = timezone(timedelta(hours=9))


def section(conn, now, accounts):
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    empty = {"meta": [], "posts": [], "feed": []}
    if "threads_apify" not in tables:
        return empty
    names = {a.lower() for a in accounts}
    rows = [dict(r) for r in conn.execute("SELECT * FROM threads_apify WHERE is_reply = 0 ORDER BY posted_at DESC")
            if (r["username"] or "").lower() in names]
    if not rows:
        return empty
    posts = []
    for r in rows:
        try:
            dt = datetime.fromisoformat((r["posted_at"] or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        v = r["views"]
        weighted = (r["likes"] or 0) + 2 * (r["replies"] or 0) + 3 * ((r["reposts"] or 0) + (r["quotes"] or 0) + (r["shares"] or 0))
        posts.append({"id": "m_" + r["post_id"], "url": r["url"], "text": (r["text"] or "")[:600], "chars": len(r["text"] or ""),
                      "views": v, "likes": r["likes"] or 0, "replies": r["replies"] or 0, "reposts": r["reposts"] or 0,
                      "quotes": r["quotes"] or 0, "shares": r["shares"] or 0,
                      "rate": round(weighted / v * 100, 1) if v else None,
                      "spread": round(v / max(r["followers"] or 0, 300), 1) if v else None,
                      "reply_rate": round((r["replies"] or 0) / v * 1000, 1) if v else None,
                      "share_rate": round(((r["reposts"] or 0) + (r["quotes"] or 0) + (r["shares"] or 0)) / v * 1000, 1) if v else None,
                      "hook": hook_of(r["text"]), "length": length_of(r["text"]), "media": "이미지·영상" if r["has_media"] else "글만",
                      "topics": r["topics"] or "", "time": dt.astimezone(KST).strftime("%m/%d %H:%M"), "dt": dt,
                      "hour": dt.astimezone(KST).hour, "followers": r["followers"]})
    posts.sort(key=lambda p: p["dt"], reverse=True)
    recent = posts[:30]
    viewed = [p for p in recent if p["views"]]
    days14 = [p for p in posts if p["dt"] >= now - timedelta(days=14)]
    first7, prev7 = [p["views"] for p in viewed[:7]], [p["views"] for p in viewed[7:14]]
    # 비교 기준: 같은 주 남의 한국어 경제 쓰레드 글 중앙값
    week = (now - timedelta(days=7)).isoformat()
    others = [r for r in conn.execute("SELECT views, likes, replies, reposts, quotes, shares FROM threads_apify WHERE posted_at >= ? "
                                      "AND views > 0 AND source NOT LIKE '%내 계정%' AND source NOT LIKE '해외%'", (week,))]
    bench_views = st.median(r[0] for r in others) if others else None
    bench_rate = st.median(((r[1] or 0) + 2 * (r[2] or 0) + 3 * ((r[3] or 0) + (r[4] or 0) + (r[5] or 0))) / r[0] * 100 for r in others) if others else None
    meta = [{"username": accounts[0], "followers": next((p["followers"] for p in posts if p["followers"]), None),
             "posts_total": len(posts), "posts_14d": len(days14), "per_day_14d": round(len(days14) / 14, 1),
             "active_days_14d": len({p["dt"].astimezone(KST).date() for p in days14}),
             "median_views": round(st.median(p["views"] for p in viewed)) if viewed else None,
             "median_rate": round(st.median(p["rate"] for p in viewed), 1) if viewed else None,
             "trend": round(st.median(first7) / st.median(prev7), 2) if len(first7) >= 3 and len(prev7) >= 3 else None,
             "bench_views": round(bench_views) if bench_views else None, "bench_rate": round(bench_rate, 1) if bench_rate else None,
             "best_hour": max(Counter(p["hour"] for p in viewed).keys(), key=lambda h: st.median(p["views"] for p in viewed if p["hour"] == h)) if viewed else None,
             "last_post": posts[0]["time"]}]
    feed = recent[:12]
    mix = []
    for dim, key in (("주제", "topics"), ("첫 줄", "hook"), ("길이", "length"), ("미디어", "media")):
        c = Counter((p[key].split(", ")[0] if p[key] else "주제 없음") if key == "topics" else p[key] for p in feed)
        mix += [{"dim": dim, "key": k, "n": n, "share": round(n / len(feed) * 100)} for k, n in c.most_common()]
    warns = []
    hooks = [p["hook"] for p in feed]
    runs = [len(list(g)) for _, g in groupby(hooks)]
    if runs and max(runs) >= 4:
        warns.append(f"같은 첫 줄 방식이 {max(runs)}개 연속이에요 — 프로필을 내려보면 같은 글처럼 보여요.")
    top_topic = Counter(p["topics"].split(", ")[0] for p in feed if p["topics"]).most_common(1)
    if top_topic and top_topic[0][1] / len(feed) >= 0.5:
        warns.append(f"최근 12개 중 '{top_topic[0][0]}' 주제가 {top_topic[0][1]}개 — 한 주제에 몰려 있어요.")
    starts = Counter((p["text"] or "").strip()[:8] for p in feed if p["text"])
    if starts and starts.most_common(1)[0][1] >= 3:
        warns.append(f"'{starts.most_common(1)[0][0]}…'로 시작하는 글이 {starts.most_common(1)[0][1]}개 — 시작 문장이 반복돼요.")
    if meta[0]["active_days_14d"] < 10:
        warns.append(f"최근 14일 중 {meta[0]['active_days_14d']}일만 올렸어요 — 매일 올리는 계정이 빨리 커요.")
    feed_out = [{"mix": mix, "warnings": warns}]
    for p in recent:
        p.pop("dt", None)
    return {"meta": meta, "posts": recent, "feed": feed_out}
