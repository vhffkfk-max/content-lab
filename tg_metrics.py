"""말희아빠 채널 키우기 지표 (tg_live.py 가 30분마다 계산해 사이트에 올림).

  tg_growth  : 내 채널 구독자 수 매일 기록과 증감
  tg_streak  : 이번 달 올린 날 수, 연속으로 올린 날, 최근 30일 하루 글 수·조회
  tg_slots   : 오늘 7개 시간표 중 올린 칸
  tg_shared  : 이번 주 전달 많이 된 내 글 TOP 5 + 최근 30일 조회 1천 회당 전달 수
  tg_rank    : 경쟁 채널 순위 (최근 30일 조회 중앙값 ÷ 그 전 60일) + 이번 주 주제
"""
import statistics as st
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from topics import topics_of

KST = timezone(timedelta(hours=9))
# 하루 7개 시간표: (이름, 추천 시각, 이 시간 사이에 올린 글이면 채운 것으로 봄)
SLOTS = [("아침 브리핑", "07:30", 5, 8.5), ("장 시작 전", "08:50", 8.5, 9.5), ("장중 1", "10:30", 9.5, 12),
         ("장중 2", "13:30", 12, 15.5), ("장 마감", "15:40", 15.5, 18), ("저녁 미장", "20:30", 18, 21.25),
         ("공유용 분석", "21:30", 21.25, 29)]
LONG = 800   # 공유용 분석으로 칠 글 길이


def _hour(dt):
    h = dt.hour + dt.minute / 60
    return h + 24 if h < 5 else h


def compute(conn, chats, now=None):
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(KST).date()
    mine = next((c for c in chats if "내" in c["분석"]), None)
    out = {"tg_growth": [], "tg_streak": [], "tg_slots": [], "tg_shared": [], "tg_rank": []}

    # 경쟁 채널 순위 (다른 채널, 조회수 있는 방)
    since90 = (now - timedelta(days=90)).isoformat()
    week = (now - timedelta(days=7)).isoformat()
    cut2 = (now - timedelta(days=2)).isoformat()   # 조회수가 덜 쌓인 이틀 안 글은 추세 계산에서 뺌
    members = {r[0]: r[1] for r in conn.execute(
        "SELECT chat_id, count FROM members WHERE date = (SELECT MAX(date) FROM members m2 WHERE m2.chat_id = members.chat_id)")}
    week_ago = (today - timedelta(days=7)).isoformat()
    members_7d = {r[0]: r[1] for r in conn.execute("SELECT chat_id, count FROM members WHERE date = ?", (week_ago,))}
    for c in chats:
        if c["종류"] != "채널":
            continue
        rows = conn.execute("SELECT date, views, text FROM msgs WHERE chat_id=? AND date >= ? AND views IS NOT NULL",
                            (c["id"], since90)).fetchall()
        recent = [v for d, v, _ in rows if d >= (now - timedelta(days=30)).isoformat() and d < cut2]
        before = [v for d, v, _ in rows if d < (now - timedelta(days=30)).isoformat()]
        wk = [(v, t) for d, v, t in rows if d >= week]
        topics = Counter(t for _, txt in wk for t in topics_of(txt) if t != "기타")
        cnt = members.get(c["id"]) or int(c["인원"] or 0)
        out["tg_rank"].append({
            "title": c["이름"], "username": c["아이디"], "mine": "내" in c["분석"], "members": cnt,
            "members_7d": cnt - members_7d[c["id"]] if c["id"] in members_7d else None,
            "median_30d": round(st.median(recent)) if recent else None,
            "trend": round(st.median(recent) / st.median(before), 2) if recent and len(before) >= 10 else None,
            "view_rate": round(st.median(recent) / cnt * 100, 1) if recent and cnt else None,
            "week_posts": len(wk), "week_topics": ", ".join(t for t, _ in topics.most_common(3))})
    out["tg_rank"].sort(key=lambda r: -(r["trend"] or 0))

    if not mine:
        return out
    cid = mine["id"]
    # 구독자 기록
    hist = conn.execute("SELECT date, count FROM members WHERE chat_id=? ORDER BY date", (cid,)).fetchall()
    prev = None
    for d, n in hist[-60:]:
        out["tg_growth"].append({"date": d, "members": n, "delta": None if prev is None else n - prev})
        prev = n

    posts = [dict(zip(["date", "text", "views", "forwards", "media", "link_id"], r)) for r in conn.execute(
        "SELECT date, text, views, forwards, media, id FROM msgs WHERE chat_id=? AND date >= ? ORDER BY date",
        (cid, (now - timedelta(days=40)).isoformat()))]
    for p in posts:
        p["dt"] = datetime.fromisoformat(p["date"]).astimezone(KST)
    by_day = defaultdict(list)
    for p in posts:
        by_day[p["dt"].date()].append(p)

    # 꾸준함
    month_days = sum(1 for d in by_day if d.year == today.year and d.month == today.month)
    streak, d = 0, today if today in by_day else today - timedelta(days=1)
    while d in by_day:
        streak += 1
        d -= timedelta(days=1)
    days30 = [today - timedelta(days=i) for i in range(29, -1, -1)]
    out["tg_streak"] = [{"month_days": month_days, "month_so_far": today.day, "streak": streak, "posted_today": today in by_day,
                         "days": [{"date": x.isoformat(), "posts": len(by_day.get(x, [])),
                                   "median_views": round(st.median(p["views"] or 0 for p in by_day[x])) if by_day.get(x) else 0,
                                   "forwards": sum((p["forwards"] or 0) for p in by_day.get(x, [])),
                                   "views": sum((p["views"] or 0) for p in by_day.get(x, []))} for x in days30]}]

    # 오늘 시간표
    todays = by_day.get(today, [])
    for name, at, a, b in SLOTS:
        hit = [p for p in todays if a <= _hour(p["dt"]) < b]
        if name == "공유용 분석":
            hit = [p for p in todays if len(p["text"] or "") >= LONG] or hit
        out["tg_slots"].append({"slot": name, "at": at, "done": bool(hit), "count": len(hit),
                                "first": hit[0]["dt"].strftime("%H:%M") if hit else ""})

    # 전달
    username = mine["아이디"]
    link = (lambda i: f"https://t.me/{username}/{i}") if username else (lambda i: "")
    wk = [p for p in posts if p["dt"].date() > today - timedelta(days=7)]
    out["tg_shared"] = [{"time": p["dt"].strftime("%m/%d %H:%M"), "forwards": p["forwards"] or 0, "views": p["views"] or 0,
                         "chars": len(p["text"] or ""), "media": p["media"], "text": (p["text"] or "")[:200], "link": link(p["link_id"])}
                        for p in sorted(wk, key=lambda p: -(p["forwards"] or 0))[:5] if (p["forwards"] or 0) > 0]
    return out
