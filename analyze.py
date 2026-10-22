"""수집된 데이터를 분석해 콘텐츠 추천(이유 포함)과 리포트를 만든다.

사용법:
    python analyze.py              # data/insta.db → output/report.html, output/report.json
    python analyze.py --days 14    # 최근 14일 기준으로 분석
    python analyze.py --db data/demo.db
"""
import argparse
import json
import math
import statistics
import webbrowser
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import report
from common import DEFAULT_DB, OUTPUT_DIR, connect
from topics import cta_of, format_of, hook_of, is_promo, length_of, tagcount_of, topics_of

KST = timezone(timedelta(hours=9))
COMMENT_WEIGHT = 3        # 댓글은 좋아요보다 강한 신호라 3배로 계산
OUTLIER_CAP = 10          # 한두 개 초대박 게시물이 평균을 왜곡하지 않게 상한
SLOTS = [(0, 6, "새벽(0~6시)"), (6, 9, "아침(6~9시)"), (9, 12, "오전(9~12시)"), (12, 14, "점심(12~14시)"),
         (14, 18, "오후(14~18시)"), (18, 21, "저녁(18~21시)"), (21, 24, "밤(21~24시)")]
WEEKDAYS = "월화수목금토일"
KR, FOREIGN = "한국", "해외"

TITLE_TEMPLATES = {
    "숫자·리스트형": "{t}, 지금 꼭 알아야 할 3가지",
    "질문형": "{t}, 지금 꼭 알아야 할 것은?",
    "경고·실수형": "{t} 투자할 때 절대 하면 안 되는 실수",
    "속보·뉴스형": "[오늘] {t}에 무슨 일이? 1분 요약",
    "정리·요약형": "{t} 한 장으로 총정리",
    "일반 서술형": "요즘 {t} 이야기, 핵심만 정리했어요",
    "숫자 강조형": "숫자 하나로 보는 {t}",
    "대비형": "{t}, 기대와 현실은 이렇게 달라요",
    "1인칭 경험형": "제가 {t}를 볼 때 꼭 확인하는 것",
    "인용형": "\"{t}, 이것만 알면 돼요\"",
    "짧은 한 줄": "{t}, 한 줄 정리",
}
MIN_FORMAT_N = 4          # 형식·첫 문장 판단에 필요한 최소 게시물 수


def parse_ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z")


def slot_of(dt):
    h = dt.astimezone(KST).hour
    return next(name for a, b, name in SLOTS if a <= h < b)


def region_of(raw):
    return KR if (raw or "").strip().upper() in ("KR", "KOREA", "한국") else FOREIGN


def summarize(items):
    vals = [min(p["outlier"], OUTLIER_CAP) for p in items if p.get("outlier") is not None]
    if not vals:
        return {"n": 0, "avg": None, "median": None}
    return {"n": len(vals), "avg": round(statistics.mean(vals), 2), "median": round(statistics.median(vals), 2)}


def load_posts(conn):
    accounts = {r["username"]: dict(r) for r in conn.execute("SELECT * FROM accounts")}
    posts = []
    for r in conn.execute("SELECT * FROM posts"):
        acc = accounts.get(r["username"])
        if not acc or not r["timestamp"]:
            continue
        p = dict(r)
        p["dt"] = parse_ts(p["timestamp"])
        p["region"] = region_of(acc["region"])
        p["followers"] = acc["followers"] or 0
        p["eng"] = (p["likes"] or 0) + COMMENT_WEIGHT * (p["comments"] or 0)
        p["topics"] = topics_of(p["caption"])
        p["hook"] = hook_of(p["caption"])
        p["format"] = format_of(p["media_type"], p["product_type"])
        p["slot"] = slot_of(p["dt"])
        p["weekday"] = WEEKDAYS[p["dt"].astimezone(KST).weekday()]
        p["promo"] = is_promo(p["caption"])
        p["cta"] = cta_of(p["caption"])
        p["length"] = length_of(p["caption"])
        p["tagcount"] = tagcount_of(p["caption"])
        posts.append(p)

    # 계정별 '평소 반응'(중앙값) 대비 몇 배인지 → 팔로워 규모가 다른 계정끼리 공정 비교
    by_acc = defaultdict(list)
    for p in posts:
        by_acc[p["username"]].append(p)
    for ps in by_acc.values():
        base = statistics.median(p["eng"] for p in ps) if ps else 0
        for p in ps:
            p["outlier"] = round(p["eng"] / base, 2) if base > 0 else None
    return accounts, posts, by_acc


def account_stats(conn, accounts, by_acc, now):
    snaps = defaultdict(list)
    for r in conn.execute("SELECT * FROM account_snapshots ORDER BY date"):
        snaps[r["username"]].append(dict(r))
    rows = []
    for username, acc in accounts.items():
        ps = by_acc.get(username, [])
        last28 = [p for p in ps if p["dt"] >= now - timedelta(days=28)]
        engs = [p["eng"] for p in last28] or [p["eng"] for p in ps]
        followers = acc["followers"] or 0
        er = round(statistics.median(engs) / followers * 100, 2) if engs and followers else None
        growth = None
        s = snaps.get(username, [])
        if len(s) >= 2 and s[0]["followers"]:
            diff = s[-1]["followers"] - s[0]["followers"]
            growth = {"diff": diff, "pct": round(diff / s[0]["followers"] * 100, 2),
                      "since": s[0]["date"]}
        top = max(last28 or ps, key=lambda p: p["outlier"] or 0, default=None)
        likes_hidden = bool(ps) and all(p["likes"] is None for p in ps)
        rows.append({
            "username": username, "name": acc["name"], "region": region_of(acc["region"]),
            "category": acc["category"], "followers": followers,
            "posts_per_week": round(len(last28) / 4, 1), "er": er, "growth": growth,
            "likes_hidden": likes_hidden,
            "days_since_last": (now - max(p["dt"] for p in ps)).days if ps else None,
            "top_post": post_brief(top) if top else None,
        })
    rows.sort(key=lambda r: (r["er"] or 0) * math.log10(max(r["followers"], 10)), reverse=True)
    return rows


def post_brief(p):
    first = (p["caption"] or "").strip().split("\n", 1)[0]
    return {"username": p["username"], "region": p["region"], "outlier": p["outlier"],
            "likes": p["likes"], "comments": p["comments"], "permalink": p["permalink"],
            "format": p["format"], "hook": p["hook"], "topics": p["topics"],
            "date": p["dt"].astimezone(KST).strftime("%m/%d %H:%M"),
            "caption": first[:90] + ("…" if len(first) > 90 else "")}


def group_stats(items, key):
    groups = defaultdict(list)
    for p in items:
        for k in (p[key] if isinstance(p[key], list) else [p[key]]):
            groups[k].append(p)
    return {k: summarize(v) for k, v in groups.items()}


def best_of(stats, min_n, exclude=()):
    """평균이 가장 높은 항목. 표본이 적은 항목은 1.0배 쪽으로 당겨서(축소 추정) 우연한 1~2개에 휘둘리지 않게."""
    cands = [(k, s) for k, s in stats.items()
             if s["n"] >= min_n and s["avg"] is not None and k not in exclude]
    return max(cands, key=lambda kv: (kv[1]["avg"] * kv[1]["n"] + 5) / (kv[1]["n"] + 5), default=(None, None))


def hashtag_topic_hits(conn, since):
    hits = defaultdict(int)
    for r in conn.execute("SELECT caption, timestamp FROM hashtag_posts"):
        if r["timestamp"] and parse_ts(r["timestamp"]) < since:
            continue
        for t in topics_of(r["caption"]):
            hits[t] += 1
    return dict(hits)


def build_recommendations(recent, posts, now, days, tag_hits, top_n):
    kr_recent = [p for p in recent if p["region"] == KR]
    fo_recent = [p for p in recent if p["region"] == FOREIGN]
    kr_accounts = len({p["username"] for p in posts if p["region"] == KR})
    kr_fmt, kr_hook = group_stats(kr_recent, "format"), group_stats(kr_recent, "hook")
    best_slot, _ = best_of(group_stats(kr_recent, "slot"), 3)

    two_weeks = now - timedelta(days=14)
    four_weeks = now - timedelta(days=28)
    topics = {t for p in recent for t in p["topics"]} - {"기타"}
    recs = []
    for t in topics:
        in_t = [p for p in recent if t in p["topics"]]
        kr = summarize([p for p in kr_recent if t in p["topics"]])
        fo = summarize([p for p in fo_recent if t in p["topics"]])
        kr_share = kr["n"] / len(kr_recent) if kr_recent else 0
        fo_share = fo["n"] / len(fo_recent) if fo_recent else 0
        last2 = sum(1 for p in posts if t in p["topics"] and p["dt"] >= two_weeks)
        prev2 = sum(1 for p in posts if t in p["topics"] and four_weeks <= p["dt"] < two_weeks)
        momentum = round(last2 / prev2, 2) if prev2 else (2.0 if last2 >= 3 else 1.0)

        fo_strong = fo["n"] >= 3 and fo["avg"] >= 1.2
        kr_proven = kr["n"] >= 3 and kr["avg"] >= 1.2
        fo_lead = fo_strong and kr_share < fo_share * 0.6
        kr_weak = fo["n"] >= 3 and fo["avg"] >= 1.3 and kr["n"] >= 3 and kr["avg"] < 1.0
        if kr_proven and fo_strong:
            kind = "국내·해외 모두 강세"
        elif kr_proven:
            kind = "국내 검증 주제"
        elif fo_lead:
            kind = "해외 선행 주제 (선점 기회)"
        elif kr_weak:
            kind = "해외 벤치마킹 주제 (방식 바꾸면 기회)"
        else:
            continue

        strength = max(kr["avg"] or 0, fo["avg"] or 0)
        n_total = kr["n"] + fo["n"]
        score = strength * math.log2(1 + n_total) * min(max(momentum, 0.6), 2.0) * (1.2 if fo_lead else 1.0)

        # 해외에서 배워야 하는 주제는 해외 게시물 기준으로 형식·첫 문장을 고른다
        learn_from = [p for p in in_t if p["region"] == FOREIGN] if (fo_lead or kr_weak) else in_t
        fmt, fmt_s = best_of(group_stats(learn_from, "format"), MIN_FORMAT_N)
        if not fmt:
            fmt, fmt_s = best_of(kr_fmt, 3)
        hook, hook_s = best_of(group_stats(learn_from, "hook"), MIN_FORMAT_N, exclude={"일반 서술형"})
        if not hook:
            hook, hook_s = best_of(kr_hook, 3, exclude={"일반 서술형"})
        where = "해외 계정의 " if learn_from is not in_t else ""

        reasons = []
        kr_acc = len({p["username"] for p in in_t if p["region"] == KR})
        fo_acc = len({p["username"] for p in in_t if p["region"] == FOREIGN})
        if fo_strong or kr_weak:
            reasons.append(f"해외 계정의 '{t}' 게시물은 각 계정 평소 반응 대비 평균 {fo['avg']:.1f}배를 기록했어요 (최근 {days}일, {fo_acc}개 계정 {fo['n']}개 게시물).")
        if kr_proven:
            reasons.append(f"한국 계정{'에서도' if fo_strong else '에서'} '{t}' 게시물은 평소 대비 평균 {kr['avg']:.1f}배 반응을 얻었어요 ({kr_acc}개 계정 {kr['n']}개 게시물) — 국내 팔로워에게 이미 통하는 주제예요.")
            if kr_acc == 1:
                reasons.append("다만 한 계정이 몰아 올린 결과라, 다른 계정에서도 통하는지는 아직 몰라요.")
            if fo["n"] >= 3 and not fo_strong:
                reasons.append(f"해외에서는 평범한 반응({fo['avg']:.1f}배)이라, 한국 투자자 특유의 관심사로 보여요.")
        elif fo_lead:
            reasons.append(f"그런데 한국 계정에서는 최근 {days}일간 이 주제 게시물이 {str(kr['n']) + '개뿐이에요' if kr['n'] else '한 개도 없어요'} (전체의 {kr_share*100:.0f}%, 해외는 {fo_share*100:.0f}%). 아직 다루는 사람이 적어 먼저 올리면 선점할 수 있어요.")
            if kr_accounts < 5:
                reasons.append(f"다만 지금 수집한 한국 계정이 {kr_accounts}개뿐이라 '한국엔 드물다'는 판단은 아직 정확하지 않아요. 한국 계정을 더 추가하면 확실해져요.")
        elif kr_weak:
            reasons.append(f"한국 계정도 이 주제를 {kr['n']}개 올렸지만 평균 {kr['avg']:.1f}배로 평소보다 반응이 낮았어요. 주제가 아니라 '전달 방식'이 문제일 가능성이 커요 — 해외 계정 방식을 따라 해볼 만해요.")
        if momentum >= 1.3:
            reasons.append(f"최근 2주 동안 이 주제 게시물이 {prev2}개 → {last2}개로 늘었어요 — 관심이 커지는 중이에요.")
        if tag_hits.get(t):
            reasons.append(f"해시태그 인기 게시물 중 {tag_hits[t]}개가 이 주제를 다루고 있어요.")
        if fmt:
            reasons.append(f"{where}이 주제 게시물은 '{fmt}' 형식이 평균 {fmt_s['avg']:.1f}배로 반응이 가장 좋았어요.")
        if hook and hook_s["avg"] >= 1.1:
            reasons.append(f"{where}첫 문장은 '{hook}' 스타일이 평균 {hook_s['avg']:.1f}배로 가장 잘 먹혔어요.")
        confidence = "높음" if n_total >= 15 else "보통" if n_total >= 6 else "낮음"
        if confidence == "낮음":
            reasons.append("표본이 적어 참고용이에요. 수집을 몇 번 더 돌리면 정확해집니다.")

        examples = sorted(in_t, key=lambda p: p["outlier"] or 0, reverse=True)[:3]
        recs.append({
            "topic": t, "kind": kind, "score": round(score, 2), "confidence": confidence,
            "title_idea": TITLE_TEMPLATES.get(hook or "일반 서술형", TITLE_TEMPLATES["일반 서술형"]).format(t=t),
            "format": fmt, "hook": hook, "slot": best_slot,
            "kr": kr, "foreign": fo, "momentum": momentum, "last2": last2, "prev2": prev2,
            "reasons": reasons, "examples": [post_brief(p) for p in examples],
        })
    recs.sort(key=lambda r: r["score"], reverse=True)
    return recs[:top_n]


def build_insights(recent):
    out = []
    for region in (KR, FOREIGN):
        items = [p for p in recent if p["region"] == region]
        if not items:
            continue
        fmt, fs = best_of(group_stats(items, "format"), 3)
        hook, hs = best_of(group_stats(items, "hook"), 3, exclude={"일반 서술형"})
        if fmt:
            out.append(f"{region} 계정은 '{fmt}' 형식이 평소 대비 {fs['avg']:.1f}배로 가장 반응이 좋아요 ({fs['n']}개 기준).")
        if hook:
            out.append(f"{region} 계정은 첫 문장이 '{hook}'일 때 평균 {hs['avg']:.1f}배 반응을 얻어요.")
    kr_items = [p for p in recent if p["region"] == KR]
    slot, ss = best_of(group_stats(kr_items, "slot"), 3)
    if slot:
        out.append(f"한국 계정은 {slot}에 올린 게시물이 평균 {ss['avg']:.1f}배로 반응이 가장 좋아요 ({ss['n']}개 기준) — 추천 카드의 업로드 시간도 이 기준이에요.")
    day, ds = best_of(group_stats(kr_items, "weekday"), 3)
    if day:
        out.append(f"한국 계정은 {day}요일 게시물이 평균 {ds['avg']:.1f}배로 반응이 가장 좋아요.")
    return out


def build_calendar(recs, recent, now):
    """추천을 앞으로 7일에 하루 하나씩 배치. 반응 좋은 요일에 순위 높은 추천을, 시간은 그 형식이 잘 되는 시간대로."""
    kr = [p for p in recent if p["region"] == KR]
    day_stats = group_stats(kr, "weekday")
    slot_overall, _ = best_of(group_stats(kr, "slot"), 3)
    today = now.astimezone(KST).date()
    days = [today + timedelta(days=i) for i in range(1, 8)]
    shrink = lambda s: (s["avg"] * s["n"] + 5) / (s["n"] + 5) if s and s["avg"] is not None else 1.0
    days.sort(key=lambda d: shrink(day_stats.get(WEEKDAYS[d.weekday()])), reverse=True)
    plan = []
    for r, d in zip(recs, days):
        fmt_posts = [p for p in kr if p["format"] == r["format"]]
        slot, slot_s = best_of(group_stats(fmt_posts, "slot"), 3)
        wd = WEEKDAYS[d.weekday()]
        ds = day_stats.get(wd) or {"avg": None, "n": 0}
        plan.append({
            "date": d.isoformat(), "weekday": wd, "slot": slot or slot_overall or "",
            "slot_basis": f"{r['format']} {slot_s['n']}개 기준 {slot_s['avg']:.1f}배" if slot else "전체 게시물 기준",
            "day_avg": ds["avg"], "day_n": ds["n"],
            "topic": r["topic"], "title": r["title_idea"], "format": r["format"] or "",
            "confidence": r["confidence"],
        })
    plan.sort(key=lambda x: x["date"])
    return plan


def build_this_week(posts, now):
    week = [p for p in posts if p["dt"] >= now - timedelta(days=7) and not p["promo"]]
    hot = sorted([p for p in week if (p["outlier"] or 0) >= 2], key=lambda p: p["outlier"], reverse=True)[:12]
    per_acc = defaultdict(list)
    for p in week:
        per_acc[p["username"]].append(p)
    accounts = sorted(({
        "username": u, "region": ps[0]["region"], "posts": len(ps),
        "top_outlier": max((p["outlier"] or 0) for p in ps),
        "topics": ", ".join(t for t, _ in Counter(t for p in ps for t in p["topics"] if t != "기타").most_common(3)),
    } for u, ps in per_acc.items()), key=lambda a: a["posts"], reverse=True)
    return [dict(post_brief(p), rank=i) for i, p in enumerate(hot, 1)], accounts


def to_rows(stats):
    return sorted(({"key": k, **s} for k, s in stats.items()), key=lambda r: r["avg"] or 0, reverse=True)


def main():
    ap = argparse.ArgumentParser(description="수집 데이터 분석 + 콘텐츠 추천")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--days", type=int, default=30, help="최근 며칠을 기준으로 볼지 (기본 30)")
    ap.add_argument("--top", type=int, default=8, help="추천 개수 (기본 8)")
    ap.add_argument("--no-open", action="store_true", help="리포트를 브라우저로 열지 않음")
    args = ap.parse_args()

    conn = connect(args.db)
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=args.days)
    accounts, posts, by_acc = load_posts(conn)
    if not posts:
        raise SystemExit("❌ 분석할 게시물이 없습니다. 먼저 collect.py 를 실행하세요 (테스트는 demo_data.py).")
    recent = [p for p in posts if p["dt"] >= since and not p["promo"]]

    tag_hits = hashtag_topic_hits(conn, since)
    data = {
        "generated_at": now.astimezone(KST).strftime("%Y-%m-%d %H:%M"),
        "days": args.days,
        "counts": {
            "accounts_kr": sum(1 for a in accounts.values() if region_of(a["region"]) == KR),
            "accounts_foreign": sum(1 for a in accounts.values() if region_of(a["region"]) == FOREIGN),
            "posts": len(posts), "recent_posts": len(recent),
            "hashtag_posts": conn.execute("SELECT COUNT(*) FROM hashtag_posts").fetchone()[0],
        },
        "recommendations": build_recommendations(recent, posts, now, args.days, tag_hits, args.top),
        "insights": build_insights(recent),
        "topics": [
            {"topic": t,
             "kr": summarize([p for p in recent if p["region"] == KR and t in p["topics"]]),
             "foreign": summarize([p for p in recent if p["region"] == FOREIGN and t in p["topics"]]),
             "hashtag_hits": tag_hits.get(t, 0)}
            for t in sorted({t for p in recent for t in p["topics"]})
        ],
        "formats": {r: to_rows(group_stats([p for p in recent if p["region"] == r], "format")) for r in (KR, FOREIGN)},
        "hooks": {r: to_rows(group_stats([p for p in recent if p["region"] == r], "hook")) for r in (KR, FOREIGN)},
        "ctas": {r: to_rows(group_stats([p for p in recent if p["region"] == r], "cta")) for r in (KR, FOREIGN)},
        "lengths": {r: to_rows(group_stats([p for p in recent if p["region"] == r], "length")) for r in (KR, FOREIGN)},
        "tagcounts": {r: to_rows(group_stats([p for p in recent if p["region"] == r], "tagcount")) for r in (KR, FOREIGN)},
        "slots_kr": [{"key": name, **summarize([p for p in recent if p["region"] == KR and p["slot"] == name])}
                     for _, _, name in SLOTS],
        "accounts": account_stats(conn, accounts, by_acc, now),
        "top_posts": [post_brief(p) for p in sorted(recent, key=lambda p: p["outlier"] or 0, reverse=True)[:20]],
    }
    data["calendar"] = build_calendar(data["recommendations"], recent, now)
    data["this_week"], data["this_week_accounts"] = build_this_week(posts, now)
    data["topics"].sort(key=lambda r: max(r["kr"]["avg"] or 0, r["foreign"]["avg"] or 0), reverse=True)

    OUTPUT_DIR.mkdir(exist_ok=True)
    (OUTPUT_DIR / "report.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path = OUTPUT_DIR / "report.html"
    html_path.write_text(report.render(data), encoding="utf-8")
    print(f"✅ 분석 완료: 게시물 {len(posts)}개 (최근 {args.days}일 {len(recent)}개), 추천 {len(data['recommendations'])}개")
    print(f"   리포트: {html_path}")
    if not args.no_open:
        webbrowser.open(html_path.as_uri())


if __name__ == "__main__":
    main()
