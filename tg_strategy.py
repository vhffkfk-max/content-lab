"""1년 치 텔레그램 글(data/telegram_history.db)로 '무엇이 잘 되나'를 뽑는다 (전략 회의용, 내 PC에서).

    python tg_strategy.py            # 결과: output/tg_strategy.json + 화면 요약
비교 기준 x = 그 글 조회수 ÷ 같은 채널의 같은 달 조회수 중앙값 (채널 크기·성장 차이를 없앰).
조회수는 시간이 지나며 쌓이므로 올린 지 2일 안 된 글은 뺀다. 채널(조회수 있는 방)만 본다.
"""
import json
import re
import sqlite3
import statistics as st
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from common import DATA_DIR, OUTPUT_DIR
from topics import topics_of

DB = DATA_DIR / "telegram_history.db"
OUT = OUTPUT_DIR / "tg_strategy.json"
KST = timezone(timedelta(hours=9))
WEEK = "월화수목금토일"


def hook_of(text):
    first = (text or "").strip().split("\n")[0]
    if not first:
        return "본문 없음(사진·파일만)"
    if re.search(r"속보|단독|긴급|\[?breaking", first, re.I):
        return "속보·긴급"
    if first.rstrip().endswith(("?", "까요", "나요", "죠")):
        return "질문"
    if re.search(r"\d", first[:30]):
        return "숫자로 시작"
    if re.match(r"^[\[\(【<▶■●◆✅📌🔥🚨⚡]", first):
        return "말머리·기호"
    return "평서문"


def length_of(text):
    n = len(text or "")
    return "0 (사진·파일만)" if n == 0 else "~100자" if n < 100 else "100~300자" if n < 300 else "300~800자" if n < 800 else "800자~"


def slot_of(h):
    return f"{h:02d}시"


def summarize(xs):
    xs = [min(x, 10) for x in xs]
    return {"n": len(xs), "x": round(st.median(xs), 2) if xs else None, "avg": round(st.mean(xs), 2) if xs else None}


def table(posts, key, min_n=20):
    g = defaultdict(list)
    for p in posts:
        g[key(p)].append(p["x"])
    rows = [{"key": k, **summarize(v)} for k, v in g.items() if len(v) >= min_n]
    return sorted(rows, key=lambda r: -(r["x"] or 0))


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    chats = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM chats")}
    cut = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    by_chat = defaultdict(list)
    for r in conn.execute("SELECT * FROM msgs WHERE views IS NOT NULL AND date < ?", (cut,)):
        by_chat[r["chat_id"]].append(dict(r))
    posts, report_chats = [], []
    for cid, ms in by_chat.items():
        ch = chats.get(cid)
        if not ch or ch["kind"] != "채널" or len(ms) < 30:
            continue
        for m in ms:
            m["dt"] = datetime.fromisoformat(m["date"]).astimezone(KST)
            m["month"] = m["dt"].strftime("%Y-%m")
        month_med = {k: max(st.median(m["views"] for m in ms if m["month"] == k), 1) for k in {m["month"] for m in ms}}
        day_count = defaultdict(int)
        for m in ms:
            day_count[m["dt"].date()] += 1
        for m in ms:
            m["x"] = m["views"] / month_med[m["month"]]
            m["chat"], m["role"] = ch["title"], ch["role"]
            m["day_posts"] = day_count[m["dt"].date()]
            m["fwd_rate"] = (m["forwards"] or 0) / max(m["views"], 1) * 1000
        posts += ms
        months = sorted(month_med)
        per_month = [{"month": k, "posts": sum(1 for m in ms if m["month"] == k), "median_views": round(month_med[k]),
                      "forwards": sum((m["forwards"] or 0) for m in ms if m["month"] == k)} for k in months]
        first, last = per_month[0], per_month[-1]
        span_days = max((ms[0]["dt"] - ms[-1]["dt"]).days if ms[0]["dt"] > ms[-1]["dt"] else (ms[-1]["dt"] - ms[0]["dt"]).days, 1)
        report_chats.append({"title": ch["title"], "role": ch["role"], "members": ch["members"], "posts": len(ms),
                             "per_day": round(len(ms) / span_days, 1), "median_views": round(st.median(m["views"] for m in ms)),
                             "view_rate": round(st.median(m["views"] for m in ms) / max(ch["members"], 1) * 100, 1),
                             "fwd_per_1k_views": round(st.mean(m["fwd_rate"] for m in ms), 2),
                             "growth": round(last["median_views"] / max(first["median_views"], 1), 2) if len(per_month) >= 3 else None,
                             "months": per_month})
    others = [p for p in posts if p["role"] == "other"]
    mine = [p for p in posts if p["role"] == "mine"]

    def bucket_posts(n):
        return "1~3개" if n <= 3 else "4~6개" if n <= 6 else "7~10개" if n <= 10 else "11~20개" if n <= 20 else "21개~"

    def analysis(ps, min_n):
        return {
            "day_volume": table(ps, lambda p: bucket_posts(p["day_posts"]), min_n),
            "hour": sorted(table(ps, lambda p: slot_of(p["dt"].hour), min_n), key=lambda r: r["key"]),
            "weekday": sorted(table(ps, lambda p: WEEK[p["dt"].weekday()], min_n), key=lambda r: WEEK.index(r["key"])),
            "media": table(ps, lambda p: p["media"], min_n),
            "length": table(ps, lambda p: length_of(p["text"]), min_n),
            "hook": table(ps, lambda p: hook_of(p["text"]), min_n),
            "link": table(ps, lambda p: "링크 있음" if p["has_link"] else "링크 없음", min_n),
            "forwarded": table(ps, lambda p: "다른 곳에서 전달한 글" if p["is_forward"] else "직접 쓴 글", min_n),
            "topics": table([dict(p, t=t) for p in ps for t in topics_of(p["text"]) if t != "기타"], lambda p: p["t"], min_n),
        }

    top_fwd = sorted((p for p in others if p["forwards"]), key=lambda p: -p["fwd_rate"])[:30]
    out = {
        "made": datetime.now(KST).isoformat(timespec="minutes"),
        "chats": sorted(report_chats, key=lambda c: (c["role"] != "mine", -c["view_rate"])),
        "others": analysis(others, 50), "mine": analysis(mine, 8),
        "mine_top": [{"time": p["dt"].strftime("%m/%d %H:%M"), "views": p["views"], "forwards": p["forwards"], "x": round(p["x"], 2),
                      "media": p["media"], "text": (p["text"] or "")[:200]} for p in sorted(mine, key=lambda p: -p["x"])[:15]],
        "mine_bottom": [{"time": p["dt"].strftime("%m/%d %H:%M"), "views": p["views"], "x": round(p["x"], 2), "media": p["media"],
                         "text": (p["text"] or "")[:120]} for p in sorted(mine, key=lambda p: p["x"])[:10]],
        "most_shared": [{"chat": p["chat"], "views": p["views"], "forwards": p["forwards"], "per_1k": round(p["fwd_rate"], 1),
                         "hook": hook_of(p["text"]), "length": length_of(p["text"]), "text": (p["text"] or "")[:200]} for p in top_fwd],
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ 채널 {len(report_chats)}개, 글 {len(posts):,}개 (내 채널 {len(mine)}개) → {OUT}")


if __name__ == "__main__":
    main()
