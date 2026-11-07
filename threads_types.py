"""쓰레드 연구소 — 경제 쓰레드 글을 '글 형태' A~H로 나누고, 형태별로 왜 잘 되는지·지금 뭘 쓸지·공략집을 만든다.

    python threads_types.py            # 통계 + 추천 (+ 하루 한 번 Claude 해석·공략집)
    python threads_types.py --ai       # Claude 해석을 지금 다시
    python threads_types.py --no-ai    # 숫자만

입력: data/insta.db 의 threads_apify (크롤러가 매시간 쌓는 쓰레드 글·조회수)
출력: output/site/thl_types.json (형태별 숫자·예시), thl_reco.json (지금 쓸 형태·주제), thl_ai.json (왜 되나·공략집)
분류는 규칙(정해진 말·모양)으로 한다. AI 해석은 '가설'로만 표시한다.
"""
import argparse
import hashlib
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from common import OUTPUT_DIR, connect, load_env
from threads_score import excluded_reason, is_media, length_of

KST = timezone(timedelta(hours=9))
SITE = OUTPUT_DIR / "site"
DAYS = 90
VIRAL_VIEWS, VIRAL_SPREAD = 100_000, 5

TYPES = {
    "A": ("속보·뉴스 요약형", "새 소식을 빠르게 전한다. '속보', '[ ]', 발표·보도 같은 말로 시작"),
    "B": ("숫자·리스트 정리형", "1. 2. 3. 이나 '- '로 줄을 나눠 정보를 정리"),
    "C": ("비교·편 가르기형", "A vs B, '~할래 ~할래'처럼 둘 중 하나를 고르게 함"),
    "D": ("질문·참여형", "물음으로 끝나 댓글을 부름"),
    "E": ("경험·썰형", "'내가·친구가·저는'으로 겪은 이야기를 풀어 감"),
    "F": ("경고·단언형", "'절대 ~하지 마', '반드시' 처럼 세게 주장"),
    "G": ("한 줄 반응형", "두 줄 안의 짧은 감상·드립"),
    "H": ("짧은 의견형", "200자 안쪽으로 내 생각·전망을 말함"),
    "I": ("긴 해설·정보형", "200자 넘게 현상을 풀어 설명함"),
}
R_NEWS = re.compile(r"^\s*(\[|【|속보|단독|긴급|방금|오늘\s*발표|breaking)|(발표했|밝혔|보도|전망이다|합의했|결정했|기자)", re.I)
R_LIST = re.compile(r"^\s*(\d{1,2}[.)]|[①-⑩]|[-•·▶✔✅]\s)", re.M)
R_VS = re.compile(r"\bvs\b|VS|(할래|살래|갈래|고를래)\s*[?？]?|\w+냐\s*\w+냐|어느\s*쪽|누가\s*이길|A\s*or\s*B", re.I)
R_STORY = re.compile(r"(내가|나는|저는|제가|친구가|친구는|와이프|남편|아내|엄마가|아빠가|회사에서|우리\s*집|했더니|해보니|해봤|였는데)")
R_WARN = re.compile(r"(절대|하지\s*마|하지마|반드시|무조건|꼭\s*(알|해|봐)|조심|주의|경고|망한|큰일|모르면\s*손해|후회)")
R_Q = re.compile(r"([?？]|까요|나요|인가요|있나요|어때요|어떻게\s*생각)\s*$")


def classify(text, press=False):
    t = (text or "").strip()
    lines = [l for l in t.split("\n") if l.strip()]
    first = lines[0] if lines else ""
    if press or R_NEWS.search(first) or R_NEWS.search(t[:120]) and len(t) < 400:
        return "A"
    if R_VS.search(t):
        return "C"
    if len(R_LIST.findall(t)) >= 3 or re.search(r"\d+\s*가지", first):
        return "B"
    if R_STORY.search(t[:200]) and len(lines) >= 3:
        return "E"
    if R_WARN.search(t[:120]):
        return "F"
    if R_Q.search(t) or R_Q.search(lines[-1] if lines else ""):
        return "D"
    if len(t) < 70 and len(lines) <= 2:
        return "G"
    return "H" if len(t) < 200 else "I"


def ts(s):
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def metrics(r, now):
    v, f = r["views"] or 0, max(r["followers"] or 0, 300)
    eng = (r["likes"] or 0) + 2 * (r["replies"] or 0) + 3 * ((r["reposts"] or 0) + (r["quotes"] or 0) + (r["shares"] or 0))
    at = ts(r["posted_at"])
    age_h = max((now - at).total_seconds() / 3600, 1) if at else None
    return {"views": v, "spread": round(v / f, 1), "rate": round(eng / v * 100, 2) if v else None,
            "reply_rate": round((r["replies"] or 0) / v * 1000, 2) if v else None,
            "share_rate": round(((r["reposts"] or 0) + (r["quotes"] or 0) + (r["shares"] or 0)) / v * 1000, 2) if v else None,
            "vph": round(v / age_h) if age_h else None, "age_h": round(age_h, 1) if age_h else None}


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 2) if xs else None


def load(conn, now):
    since = (now - timedelta(days=DAYS)).isoformat()
    from apify_threads import MY_ACCOUNTS
    mine = {u.lower() for u in MY_ACCOUNTS}
    out, own = [], []
    for r in conn.execute("SELECT * FROM threads_apify WHERE is_reply = 0 AND views IS NOT NULL AND views > 0 AND posted_at >= ?", (since,)):
        r = dict(r)
        is_mine = (r["username"] or "").lower() in mine
        if (r["source"] or "").startswith("해외") or (not is_mine and excluded_reason(r)):
            continue
        press = is_media(r)
        at = ts(r["posted_at"])
        p = {"code": r["code"], "url": r["url"], "username": r["username"], "followers": r["followers"], "text": r["text"],
             "topics": r["topics"] or "", "press": press, "type": classify(r["text"], press), "length": length_of(r["text"]),
             "media": bool(r["has_media"]), "likes": r["likes"], "replies": r["replies"], "reposts": r["reposts"],
             "time": at.astimezone(KST).strftime("%m/%d %H:%M") if at else "", "hour": at.astimezone(KST).hour if at else None,
             **metrics(r, now)}
        (own if is_mine else out).append(p)
    return out, own


def score(p):   # 조회 크기 + 확산 + 반응을 같이 보는 간단 점수 (예시 고르기용)
    import math
    return math.log10(p["views"] + 10) + math.log10(p["spread"] + 1) * 1.2 + (p["rate"] or 0) / 4


def brief(p, n=400):
    keep = ("url", "username", "followers", "views", "spread", "rate", "replies", "reposts", "likes", "time", "topics", "length", "media", "type", "press")
    return {**{k: p[k] for k in keep}, "text": (p["text"] or "")[:n]}


def type_stats(posts):
    by = defaultdict(list)
    for p in posts:
        by[p["type"]].append(p)
    allv = med([p["views"] for p in posts]) or 1
    res = []
    for k, (name, desc) in TYPES.items():
        ps = by.get(k, [])
        if not ps:
            res.append({"type": k, "name": name, "desc": desc, "n": 0})
            continue
        viral = [p for p in ps if p["views"] >= VIRAL_VIEWS or p["spread"] >= VIRAL_SPREAD]
        lens = Counter(p["length"] for p in viral or ps).most_common(1)[0][0]
        hours = Counter(p["hour"] for p in viral or ps if p["hour"] is not None).most_common(3)
        topics = Counter(t for p in viral or ps for t in p["topics"].split(", ") if t and t != "기타").most_common(4)
        s = {"type": k, "name": name, "desc": desc, "n": len(ps), "share": round(len(ps) / len(posts) * 100, 1),
             "med_views": med([p["views"] for p in ps]), "med_spread": med([p["spread"] for p in ps]),
             "med_rate": med([p["rate"] for p in ps]), "reply_rate": med([p["reply_rate"] for p in ps]),
             "share_rate": round(sum(1 for p in ps if p["share_rate"]) / len(ps) * 100, 1),
             "reply_pct": round(sum(1 for p in ps if p["replies"]) / len(ps) * 100, 1),
             "viral_pct": round(len(viral) / len(ps) * 100, 1), "views_idx": round((med([p["views"] for p in ps]) or 0) / allv, 2),
             "media_pct": round(sum(p["media"] for p in ps) / len(ps) * 100), "best_length": lens,
             "best_hours": [h for h, _ in hours], "best_topics": [t for t, _ in topics],
             "examples": [brief(p) for p in sorted(ps, key=score, reverse=True)[:6]]}
        res.append(s)
    # 형태마다 '무엇에 강한가' (전체 형태 중 몇 등인가)
    have = [s for s in res if s["n"] >= 15]
    for key, label in (("med_views", "조회"), ("med_spread", "확산"), ("reply_rate", "댓글"), ("share_rate", "공유"), ("viral_pct", "터질 확률")):
        for i, s in enumerate(sorted(have, key=lambda s: s[key] or 0, reverse=True)):
            s.setdefault("ranks", {})[label] = i + 1
    for s in res:
        s["strong"] = [l for l, r in (s.get("ranks") or {}).items() if r <= 2]
        s["small_sample"] = s["n"] < 15
    return res


def recommend(posts, own, stats, now):
    recent = [p for p in posts if p["age_h"] is not None and p["age_h"] <= 48]
    hot = sorted(recent, key=lambda p: p["vph"] or 0, reverse=True)[:40]
    base = Counter(p["type"] for p in posts)
    hot_c = Counter(p["type"] for p in hot)
    names = {k: v[0] for k, v in TYPES.items()}
    lift = []
    for k in TYPES:
        if hot_c[k] >= 3:
            exp = base[k] / max(len(posts), 1) * len(hot)
            lift.append({"type": k, "name": names[k], "hot_n": hot_c[k], "lift": round(hot_c[k] / max(exp, 0.5), 2)})
    lift.sort(key=lambda x: x["lift"], reverse=True)
    topics = Counter(t for p in hot for t in p["topics"].split(", ") if t and t != "기타").most_common(5)
    st = {s["type"]: s for s in stats}
    # 우리 계정: 형태별 글 수·중간 조회
    ob = defaultdict(list)
    for p in own:
        ob[p["type"]].append(p)
    mine = [{"type": k, "name": names[k], "n": len(ob[k]), "med_views": med([p["views"] for p in ob[k]])} for k in TYPES]
    # 추천: 지금 뜨는 형태 × 지금 뜨는 주제, 우리가 덜 쓴 형태에 가산점
    picks, used = [], set()
    cand = [x["type"] for x in lift] + [s["type"] for s in sorted([s for s in stats if s["n"] >= 15], key=lambda s: s["viral_pct"], reverse=True)]
    for k in cand:
        if k in used or len(picks) >= 4:
            continue
        used.add(k)
        topic = next((t for t, _ in topics if t in (st[k].get("best_topics") or [])), topics[0][0] if topics else "")
        ex = next((p for p in hot if p["type"] == k), None)
        why = []
        lx = next((x for x in lift if x["type"] == k), None)
        if lx and lx["lift"] > 1.1:
            why.append(f"최근 48시간 빨리 크는 글 40개 중 {lx['hot_n']}개가 이 형태 (평소보다 {lx['lift']}배 많음)")
        if st[k].get("viral_pct") is not None:
            why.append(f"지난 {DAYS}일 이 형태 글의 {st[k]['viral_pct']}%가 10만 조회 또는 확산 5배 이상")
        if st[k].get("strong"):
            why.append("특히 " + "·".join(st[k]["strong"]) + "에 강함")
        mn = next(m for m in mine if m["type"] == k)
        if mn["n"] <= 2:
            why.append(f"황소개미는 지난 {DAYS}일 이 형태를 {mn['n']}번만 씀")
        picks.append({"type": k, "name": names[k], "topic": topic, "why": why, "example": brief(ex, 300) if ex else None,
                      "best_length": st[k].get("best_length"), "best_hours": st[k].get("best_hours")})
    return {"at": now.astimezone(KST).strftime("%m/%d %H:%M"), "hot_n": len(hot), "lift": lift, "hot_topics": [t for t, _ in topics],
            "picks": picks, "mine": mine, "mine_n": len(own)}


AI_SYSTEM = """당신은 한국 경제 쓰레드(Threads) 계정 @bullant_economy(황소개미) 의 성장 전략가입니다.
경제 쓰레드 글을 '글 형태' A~I 로 나눈 숫자와 형태별 잘 된 예시를 받습니다.
할 일: 형태마다 왜 잘 되는지(또는 왜 안 되는지)를 숫자 근거로 설명하고, 따라 쓸 틀과 첫 줄 예시를 만들고, 전체 공략집을 씁니다.
규칙: 모두 한국어, 중학생도 이해할 쉬운 말, 이모지 금지. 받은 숫자 밖의 수치는 지어내지 않습니다.
예시 글을 그대로 베끼지 않습니다. 특정 종목 매수·매도 권유, 수익 보장 표현 금지.
표본(n)이 15 미만이면 '표본 적음'이라고 밝히고 단정하지 않습니다.
JSON 하나만 출력합니다:
{"types":[{"type":"A","why":["왜 되나 2~3개, 각 70자 이내, 숫자 근거"],"template":"구조 한 줄 (예: 숫자 한 줄 → 이유 3개 → 질문)",
 "hooks":["황소개미용 첫 줄 예시 2개"],"avoid":"이 형태에서 하지 말 것 한 줄","best_for":"언제 쓰면 좋은지 한 줄"}],
 "playbook":[{"title":"공략 규칙 제목 15자 이내","body":"설명 2문장 이내, 숫자 근거"}],
 "summary":["전체 한눈에 3줄, 각 60자 이내"]}
playbook 은 8~10개."""


def run_ai(stats, force):
    out = SITE / "thl_ai.json"
    old = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    slim = [{k: s.get(k) for k in ("type", "name", "desc", "n", "share", "med_views", "med_spread", "med_rate", "reply_rate", "share_rate", "reply_pct",
                                   "viral_pct", "views_idx", "media_pct", "best_length", "best_hours", "best_topics", "strong", "small_sample")}
            | {"examples": [{"text": e["text"][:250], "views": e["views"], "spread": e["spread"], "rate": e["rate"], "followers": e["followers"]}
                            for e in s.get("examples", [])[:4]]} for s in stats]
    digest = hashlib.sha1(json.dumps([(s["type"], s.get("n", 0) // 50, [e["text"][:40] for e in s.get("examples", [])[:3]]) for s in stats],
                                     ensure_ascii=False).encode()).hexdigest()
    last = ts(old.get("at")) if old.get("at") else None
    if not force and old.get("digest") == digest:
        print("AI 해석: 입력이 같아 건너뜀"); return
    if not force and last and datetime.now(timezone.utc) - last < timedelta(hours=20):
        print("AI 해석: 하루 한 번만 (지난 해석 유지)"); return
    import llm
    if not llm.ready():
        print("AI 해석: 이 컴퓨터에서 Claude 를 못 불러 건너뜀"); return
    msg = "경제 쓰레드 글 형태별 숫자 (views=조회, spread=조회÷팔로워, rate=반응률%, reply_rate=조회 1000명당 답글 수, share_rate=리포스트·인용·공유가 1번이라도 있는 글 비율%, reply_pct=답글이 달린 글 비율%, viral_pct=10만 조회 또는 확산 5배 이상 비율, views_idx=전체 중간값 대비 조회 배수):\n" + json.dumps(slim, ensure_ascii=False)
    try:
        r = llm.Anthropic().messages.create(model="claude-sonnet-5-5", max_tokens=8000, system=AI_SYSTEM, messages=[{"role": "user", "content": msg}])
        text = r.content[0].text
        data = json.loads(text[text.find("{"): text.rfind("}") + 1])
    except Exception as e:
        print("AI 해석 실패 — 지난 결과 유지:", str(e)[:200]); return
    data.update({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "digest": digest, "model": "claude-sonnet-5-5"})
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print("AI 해석 저장:", len(data.get("types", [])), "형태 ·", len(data.get("playbook", [])), "공략")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ai", action="store_true")
    ap.add_argument("--no-ai", action="store_true")
    a = ap.parse_args()
    load_env()
    now = datetime.now(timezone.utc)
    conn = connect()
    posts, own = load(conn, now)
    if not posts:
        print("쓰레드 글이 없어요 — 건너뜀"); return
    stats = type_stats(posts)
    meta = {"at": now.isoformat(timespec="seconds"), "days": DAYS, "n": len(posts), "own_n": len(own),
            "viral_rule": f"조회 {VIRAL_VIEWS:,} 이상 또는 확산 {VIRAL_SPREAD}배 이상", "med_views": med([p["views"] for p in posts])}
    SITE.mkdir(parents=True, exist_ok=True)
    (SITE / "thl_types.json").write_text(json.dumps({"meta": meta, "types": stats}, ensure_ascii=False), encoding="utf-8")
    (SITE / "thl_reco.json").write_text(json.dumps(recommend(posts, own, stats, now), ensure_ascii=False), encoding="utf-8")
    print(f"쓰레드 연구소: 글 {len(posts)}개 · 우리 글 {len(own)}개 · " + " ".join(f"{s['type']}{s['n']}" for s in stats))
    if not a.no_ai:
        run_ai(stats, a.ai)


if __name__ == "__main__":
    main()
