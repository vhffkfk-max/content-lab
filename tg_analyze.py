"""data/telegram.json(내 PC가 모은 텔레그램 글)을 분석해 사이트용 output/site/tg_*.json 을 만든다.

    python tg_analyze.py            # 통계 + Claude 추천 (ANTHROPIC_API_KEY 없으면 통계만)
    python tg_analyze.py --dry-run  # Claude 호출 없이 프롬프트만 출력
'평소 대비 ○배' = 그 방 글들의 중앙값 대비. 채널은 조회수, 그룹은 반응 + 3×답글.
Claude 는 다른 업체 방의 반응 큰 글 + 연구소가 모은 오늘의 뉴스로 '오늘 내 방에 올릴 문구'를 쓴다.
Claude 추천은 하루 한 번(07시 이후 첫 실행)만 쓴다 (비용 절약). 실패하면 지난 추천을 그대로 둔다.
"""
import argparse
import hashlib
import json
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import List

from common import DATA_DIR, OUTPUT_DIR, load_env
from topics import topics_of

MODEL = "claude-opus-5-5"
SRC = DATA_DIR / "telegram.json"
SITE = OUTPUT_DIR / "site"
KST = timezone(timedelta(hours=9))
SLOTS = [(5, 9, "아침 05-09"), (9, 12, "오전 09-12"), (12, 15, "점심 12-15"), (15, 18, "오후 15-18"),
         (18, 22, "저녁 18-22"), (22, 29, "밤 22-05")]

SYSTEM = """당신은 한국 경제 크리에이터 @hotconomy 가 운영하는 경제 텔레그램 방의 콘텐츠 에디터입니다.
다른 업체 텔레그램 방에서 반응(조회수·반응·답글)이 평소보다 컸던 글과, 오늘 모은 경제 뉴스·트렌드를 받아
'왜 반응이 컸는지'와 '오늘 우리 방에 올릴 문구'를 씁니다.

규칙:
- 모두 한국어. 텔레그램 말투(짧은 줄, 핵심 먼저, 필요하면 ▶ · ✔ 같은 기호)는 써도 되지만 이모지는 한 글에 2개 이하.
- 데이터에 없는 숫자·사실은 지어내지 말고 [확인] 으로 비웁니다. 뉴스 제목에 있는 사실만 씁니다.
- 다른 방 글을 베끼지 않습니다. 구성과 말투 방식만 빌려 새로 씁니다.
- 특정 종목 매수·매도 권유, 목표가, 수익 보장, '지금 사라' 같은 표현을 쓰지 않습니다(유사투자자문 문제).
  정보 정리·해설·질문 위주로 쓰고, 주식·코인 글 끝에는 '투자 판단은 본인 몫' 같은 한 줄을 넣습니다.
- summary: 다른 방들의 반응 큰 글에서 보이는 공통점 3줄(각 60자 안팎).
- formulas: 따라 쓸 수 있는 텔레그램 글 공식 3~5개. name, pattern(구성 한 줄), example(우리 방용 예시 문구 1~3줄), when(언제 쓰나).
- today: 오늘 우리 방에 올릴 글 5개. time(추천 시간대, 반응 좋은 시간대 참고), type(아침 브리핑/속보 해설/3줄 요약/질문·투표/장 마감 정리 등),
  text(그대로 붙여넣을 완성 문구, 600자 이내), why(왜 오늘 이 글인지 한 줄), based_on(근거 뉴스·주제).
- posts: 받은 '반응 큰 글' 각각에 no(번호 그대로), why(왜 반응이 컸는지 1문장), hook(첫 줄 방식 짧게)."""


def score(m, kind):
    if kind == "채널" and m.get("views") is not None:
        return m["views"]
    return (m.get("reactions") or 0) + 3 * (m.get("replies") or 0)


def slot_of(dt):
    h = dt.astimezone(KST).hour
    h = h + 24 if h < 5 else h
    return next(name for a, b, name in SLOTS if a <= h < b)


def length_of(text):
    n = len(text)
    return "짧음(~100자)" if n < 100 else "보통(100~400자)" if n < 400 else "김(400자~)"


def summarize(items):
    xs = [min(i["x"], 10) for i in items if i["x"] is not None]
    return {"n": len(items), "avg": round(statistics.mean(xs), 2) if xs else None}


def build(data, now):
    chats = {str(c["id"]): c for c in data["chats"]}
    by_chat = defaultdict(list)
    for m in data["messages"]:
        c = chats.get(str(m["chat_id"]))
        if not c:
            continue
        m = dict(m, dt=datetime.fromisoformat(m["date"]), kind=c["kind"], role=c["role"], chat=c["title"])
        m["score"] = score(m, c["kind"])
        by_chat[str(m["chat_id"])].append(m)
    msgs = []
    chat_rows = []
    for cid, ms in by_chat.items():
        c = chats[cid]
        base = max(statistics.median(m["score"] for m in ms), 5) if len(ms) >= 5 else None
        for m in ms:
            m["x"] = round(m["score"] / base, 1) if base else None
        msgs += ms
        span = max((now - min(m["dt"] for m in ms)).days, 1)
        chat_rows.append({"title": c["title"], "username": c["username"], "kind": c["kind"], "role": c["role"],
                          "members": c["members"], "posts": len(ms), "per_day": round(len(ms) / min(span, data["days"]), 1),
                          "median": round(statistics.median(m["score"] for m in ms)),
                          "metric": "조회수" if c["kind"] == "채널" else "반응+답글",
                          "best_slot": max(((s, summarize([m for m in ms if slot_of(m["dt"]) == s])) for _, _, s in SLOTS),
                                           key=lambda t: t[1]["avg"] or 0)[0]})
    others = [m for m in msgs if m["role"] == "other"]
    week = [m for m in others if m["dt"] >= now - timedelta(days=7) and m["x"] is not None and m["text"]]
    # 자동 공시봇처럼 글이 많은 방이 목록을 다 차지하지 않게 방마다 3개까지
    hot, per_room = [], defaultdict(int)
    for m in sorted(week, key=lambda m: (min(m["x"], 10), m["score"]), reverse=True):
        if per_room[m["chat"]] < 3 and len(hot) < 30:
            hot.append(m)
            per_room[m["chat"]] += 1
    hours = [{"key": s, **summarize([m for m in others if slot_of(m["dt"]) == s])} for _, _, s in SLOTS]
    lengths = [{"key": k, **summarize([m for m in others if length_of(m["text"]) == k])}
               for k in ("짧음(~100자)", "보통(100~400자)", "김(400자~)")]
    medias = [{"key": k, **summarize([m for m in others if m["media"] == k])} for k in ("글", "사진", "영상", "링크", "파일")]
    mine = sorted((m for m in msgs if m["role"] == "mine"), key=lambda m: m["dt"], reverse=True)[:30]
    brief = lambda m: {"id": f"{m['chat_id']}_{m['id']}", "chat": m["chat"], "kind": m["kind"], "text": m["text"][:600],
                       "views": m["views"], "reactions": m["reactions"], "replies": m["replies"], "forwards": m["forwards"],
                       "x": m["x"], "media": m["media"], "link": m["link"],
                       "topics": ", ".join(t for t in topics_of(m["text"]) if t != "기타"),
                       "time": m["dt"].astimezone(KST).strftime("%m/%d %H:%M")}
    meta = [{"chats": len(chat_rows), "others": sum(1 for c in chat_rows if c["role"] == "other"),
             "mine": sum(1 for c in chat_rows if c["role"] == "mine"), "posts": len(msgs), "week": len(week),
             "collected": data["collected"]}]
    return {"tg_meta": meta, "tg_chats": sorted(chat_rows, key=lambda c: (c["role"] != "mine", -c["posts"])),
            "tg_hot": [brief(m) for m in hot], "tg_mine": [brief(m) for m in mine],
            "tg_hours": hours, "tg_lengths": [l for l in lengths if l["n"]], "tg_media": [x for x in medias if x["n"]]}


def news_context():
    def load(name):
        p = SITE / f"{name}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    heads = [f"[{h['source']}] {h['title']}" for h in load("press_headlines")[:20]]
    topics = [f"{t['topic']} (하루 기사 {t.get('kr_per_day')}건)" for t in load("google_topics")[:8]]
    recs = [f"{r['topic']}: {r.get('title_idea', '')}" for r in load("recs")[:5]]
    return {"headlines": heads, "news_topics": topics, "instagram_recommended": recs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="오늘 이미 썼어도 Claude 추천을 다시 씀")
    args = ap.parse_args()
    load_env()
    if SRC.exists():  # 내 PC에서 직접 모은 파일이 있으면 통계부터 새로 (서버에서는 tg_live.py 가 올린 통계를 그대로 씀)
        out = build(json.loads(SRC.read_text(encoding="utf-8")), datetime.now(timezone.utc))
        SITE.mkdir(parents=True, exist_ok=True)
        for name, rows in out.items():
            (SITE / f"{name}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"✅ 텔레그램 통계: 방 {out['tg_meta'][0]['chats']}개, 반응 큰 글 {len(out['tg_hot'])}개")
    load = lambda n: json.loads((SITE / f"{n}.json").read_text(encoding="utf-8")) if (SITE / f"{n}.json").exists() else []
    out = {n: load(n) for n in ("tg_hot", "tg_hours", "tg_lengths", "tg_mine")}
    if not out["tg_hot"]:
        print("텔레그램 통계가 아직 없어요 — 분석을 건너뛰어요 (TELEGRAM_SETUP.md 참고).")
        return
    # 사이트는 30분마다 갱신되지만 Claude 추천은 하루 한 번: 07시(뉴스 수집 뒤) 이후 첫 갱신 때만
    ai_path = SITE / "tg_ai.json"
    last = json.loads(ai_path.read_text(encoding="utf-8") or "{}").get("analyzed_at", "") if ai_path.exists() else ""
    today = datetime.now(KST)
    done_today = bool(last) and datetime.fromisoformat(last).astimezone(KST).date() == today.date()
    if not args.force and not args.dry_run and (done_today or today.hour < 7):
        print("오늘의 텔레그램 추천은 하루 한 번(07시 이후)만 써요 — 이번엔 건너뛰어요.")
        return

    hot = out["tg_hot"][:25]
    items = [{"no": i, "room": h["chat"], "x": h["x"], "views": h["views"], "reactions": h["reactions"], "replies": h["replies"],
              "media": h["media"], "time": h["time"], "text": h["text"]} for i, h in enumerate(hot, 1)]
    ctx = {"hot_posts": items, "best_slots": out["tg_hours"], "lengths": out["tg_lengths"],
           "my_recent_posts": [m["text"][:300] for m in out["tg_mine"][:5]], "today": news_context(),
           "date": datetime.now(KST).strftime("%Y-%m-%d (%a)")}
    prompt = "자료:\n" + json.dumps(ctx, ensure_ascii=False, indent=1)
    if args.dry_run:
        print(SYSTEM, "\n\n", prompt[:3000])
        return
    digest = hashlib.sha1(prompt.encode()).hexdigest()
    if ai_path.exists() and json.loads(ai_path.read_text(encoding="utf-8") or "{}").get("digest") == digest:
        print("입력이 같아 지난 텔레그램 추천을 그대로 써요.")
        return
    if not hot:
        print("반응 큰 글이 아직 없어 Claude 추천을 건너뛰어요.")
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY 가 없어 Claude 추천을 건너뛰어요 — 지난 결과를 유지해요.")
        return

    import anthropic
    from pydantic import BaseModel

    class Formula(BaseModel):
        name: str
        pattern: str
        example: str
        when: str

    class TodayPost(BaseModel):
        time: str
        type: str
        text: str
        why: str
        based_on: str

    class PostNote(BaseModel):
        no: int
        why: str
        hook: str

    class Analysis(BaseModel):
        summary: List[str]
        formulas: List[Formula]
        today: List[TodayPost]
        posts: List[PostNote]

    client = anthropic.Anthropic()
    try:
        r = client.messages.parse(model=MODEL, max_tokens=16000, system=SYSTEM,
                                  messages=[{"role": "user", "content": prompt}], output_format=Analysis)
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
        print(f"⚠️ Claude API 오류: {e} — 지난 결과를 유지해요.")
        return
    if r.stop_reason != "end_turn" or r.parsed_output is None:
        print(f"⚠️ 결과를 받지 못했어요(stop_reason={r.stop_reason}) — 지난 결과를 유지해요.")
        return
    a = r.parsed_output
    notes = [{**n.model_dump(), "id": hot[n.no - 1]["id"]} for n in a.posts if 1 <= n.no <= len(hot)]
    ai_path.write_text(json.dumps({"digest": digest, "analyzed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                   "summary": a.summary, "formulas": [f.model_dump() for f in a.formulas],
                                   "today": [t.model_dump() for t in a.today], "posts": notes},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ 텔레그램 추천: 오늘 문구 {len(a.today)}개 · 공식 {len(a.formulas)}개 "
          f"(입력 {r.usage.input_tokens:,} / 출력 {r.usage.output_tokens:,} 토큰)")


if __name__ == "__main__":
    sys.exit(main())
