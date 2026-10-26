"""X·트루스소셜 수집 글 정리 (analyze.py 가 부름): 트럼프 최신 글, 반응 랭킹, 묶음별 글, 계정 현황."""
import re
import statistics as st
from collections import defaultdict
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
ECON_EN = re.compile(r"stock|market|fed\b|federal reserve|rate|inflation|tariff|bitcoin|crypto|econom|recession|yield|treasury|dollar|"
                     r"oil|jobs|gdp|earnings|s&p|nasdaq|dow|trade|debt|deficit|bank|price|tax|invest|gold|cpi|employment", re.I)
GROUPS = ["정책", "시장 속보", "분석", "인물", "코인", "화제"]


def brief(r):
    dt = datetime.fromisoformat(r["created_at"])
    return {"id": r["id"], "platform": r["platform"], "username": r["username"], "name": r["name"] or "", "group": r["grp"],
            "followers": r["followers"], "text": (r["text"] or "")[:700], "url": r["url"], "views": r["views"], "likes": r["likes"] or 0,
            "reposts": r["reposts"] or 0, "replies": r["replies"] or 0, "quotes": r["quotes"] or 0, "bookmarks": r["bookmarks"] or 0,
            "repost": bool(r["is_repost"]), "time": dt.astimezone(KST).strftime("%m/%d %H:%M"),
            "age_h": round((datetime.now(timezone.utc) - dt).total_seconds() / 3600, 1)}


def section(conn, now):
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    empty = {"meta": [], "trump": [], "rank": [], "groups": [], "accounts": []}
    if "x_posts" not in tables:
        return empty
    week = (now - timedelta(days=7)).isoformat()
    rows = [dict(r) for r in conn.execute("SELECT * FROM x_posts WHERE created_at >= ? ORDER BY created_at DESC", (week,))]
    # 키워드로 걸린 화제 글은 경제 단어가 있어야 남김 (정치·사건 화제 글 거르기)
    rows = [r for r in rows if r["source"] != "키워드 화제" or ECON_EN.search(r["text"] or "")]
    if not rows:
        return empty
    recent = [r for r in rows if r["created_at"] >= (now - timedelta(hours=48)).isoformat() and not r["is_repost"]]
    trump = [brief(r) for r in rows if (r["username"] or "").lower() == "realdonaldtrump"][:20]
    rank = []
    for key, f in (("views", lambda r: r["views"] or 0), ("reposts", lambda r: (r["reposts"] or 0) + (r["quotes"] or 0)),
                   ("replies", lambda r: r["replies"] or 0)):
        rank += [dict(brief(r), list=key) for r in sorted(recent, key=f, reverse=True)[:10] if f(r) > 0]
    groups = []
    for g in GROUPS:
        gs = sorted([r for r in recent if r["grp"] == g], key=lambda r: (r["views"] or 0, r["likes"] or 0), reverse=True)[:8]
        groups += [dict(brief(r), group=g) for r in gs]
    acc = defaultdict(list)
    for r in rows:
        acc[(r["platform"], r["username"])].append(r)
    accounts = sorted(({"platform": p, "username": u, "name": rs[0]["name"] or "", "group": rs[0]["grp"], "followers": rs[0]["followers"],
                        "posts_7d": len(rs), "median_views": round(st.median(r["views"] for r in rs if r["views"])) if any(r["views"] for r in rs) else None,
                        "top_views": max((r["views"] or 0) for r in rs)} for (p, u), rs in acc.items()),
                      key=lambda a: -(a["median_views"] or 0))
    month = now.strftime("%Y-%m")
    cost = conn.execute("SELECT COALESCE(SUM(x_results),0), COALESCE(SUM(truth_results),0) FROM x_cost WHERE date LIKE ?",
                        (month + "%",)).fetchone() if "x_cost" in tables else (0, 0)
    meta = [{"collected": max(r["collected_at"] for r in rows), "posts_7d": len(rows), "posts_48h": len(recent),
             "accounts": len(accounts), "trump_48h": sum(1 for t in trump if t["age_h"] <= 48),
             "month_cost": round(cost[0] * 0.4 / 1000 + cost[1] * 5 / 1000, 2)}]
    return {"meta": meta, "trump": trump, "rank": rank, "groups": groups, "accounts": accounts}
