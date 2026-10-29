"""data/telegram.json(내 PC가 모은 텔레그램 글)을 분석해 사이트용 output/site/tg_*.json 을 만든다.

    python tg_analyze.py            # 통계 + Claude 추천 (내 PC Claude Code(Max) 없으면 통계만)
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

SYSTEM = """당신은 텔레그램 채널 '{room}' 을(를) 키우는 콘텐츠 에디터입니다. 목표는 이 채널의 구독자와 조회수를 늘리는 것.
다른 업체 텔레그램 방에서 반응(조회수·반응·답글)이 평소보다 컸던 글, 우리 채널의 최근 글과 성과, 오늘 모은 경제 뉴스·트렌드를 받아
'왜 반응이 컸는지'와 '오늘 우리 채널에 올릴 문구', '채널을 키울 방법'을 씁니다.

규칙:
- 모두 한국어. 텔레그램 말투(짧은 줄, 핵심 먼저, 필요하면 ▶ · ✔ 같은 기호)는 써도 되지만 이모지는 한 글에 2개 이하.
- 데이터에 없는 숫자·사실은 지어내지 말고 [확인] 으로 비웁니다. 뉴스 제목에 있는 사실만 씁니다.
- 다른 방 글을 베끼지 않습니다. 구성과 말투 방식만 빌려 새로 씁니다.
- today 문구는 우리 채널 최근 글(my_recent_posts)의 말투·호칭·서명·자주 다루는 주제(차트 분석 등)를 따라 씁니다. 다른 방 이름이나 서명, 말투를 쓰지 않습니다.
- 특정 종목 매수·매도 권유, 목표가, 수익 보장, '지금 사라' 같은 표현을 쓰지 않습니다(유사투자자문 문제).
  정보 정리·해설·질문 위주로 쓰고, 주식·코인 글 끝에는 '투자 판단은 본인 몫' 같은 한 줄을 넣습니다.
- summary: 다른 방들의 반응 큰 글에서 보이는 공통점 3줄(각 60자 안팎).
- formulas: 따라 쓸 수 있는 텔레그램 글 공식 3~5개. name, pattern(구성 한 줄), example(우리 방용 예시 문구 1~3줄), when(언제 쓰나).
- 시장 분위기 먼저 판단: 오늘 헤드라인·X/트루스 브리핑·다른 방 글에 급락·약세·공포가 보이면 '하락장 모드'로 씁니다.
  하락장 모드: 왜 빠지는지 원인 정리(뉴스 근거) → 숫자로 보는 현재 위치(과거 비슷한 하락과 비교, 근거 없는 수치는 [확인]) →
  흔들리지 않게 체크리스트(현금 비중·분할·손절 기준 같은 일반 원칙, 특정 종목 권유 금지) → 반등 때 확인할 신호.
  공포를 키우는 표현('폭락 온다', '끝났다')은 쓰지 않고, 차분하게 정리해 주는 채널이라는 인상을 줍니다.
- now_kst(지금 시각) 이후 시간표 칸을 먼저 씁니다. 이미 지난 칸은 '오늘 장 정리'처럼 지금 올려도 되는 글로 바꾸고, 7개를 채웁니다.
- today: 오늘 우리 채널에 올릴 글 7개를 아래 시간표 순서 그대로 (하루 6~8개를 매일 고르게 올리는 게 조회율이 가장 높았음).
  1) 07:30 아침 브리핑 — 밤사이 미국장·코인·환율 핵심 3줄
  2) 08:50 장 시작 전 — 오늘 볼 차트 1~2개와 확인할 가격대
  3) 10:30 장중 차트 업데이트
  4) 13:30 장중 차트 업데이트 (국내장이 조용하면 코인)
  5) 15:40 장 마감 정리
  6) 20:30 저녁 미장·코인 차트 프리뷰 (우리 채널 반응이 가장 좋은 시간대)
  7) 21:30 공유용 심층 분석 — 저장·전달하고 싶은 정리 글, 끝에 '필요한 분께 전달해 주세요' 한 줄 (전달이 새 구독자를 데려옴)
  토·일요일은 국내장이 없으니 2~5번을 코인 차트·주간 정리·다음 주 일정으로 바꿉니다.
  장중 글(3·4번)은 미리 알 수 없는 가격을 지어내지 말고, 볼 자리·시나리오와 [확인] 칸으로 씁니다.
  각 글: time(위 시각), type(위 이름), text(그대로 붙여넣을 완성 문구, 600자 이내), why(왜 오늘 이 글인지 한 줄), based_on(근거 뉴스·주제).
- 경제 채널 25곳 1년 치(22만 개) 분석 결론을 따릅니다: 글 하나 조회수는 시간·요일·형식·첫 줄과 거의 상관없음(±5%),
  하루 글 수를 늘려도 글당 조회는 거의 안 줄어듦(1~3개 1.07배 → 21개 이상 0.98배) → 글 수를 줄이라고 하지 않습니다.
  성장한 채널의 공통점은 매일 빠짐없이 올리기, 형식(정체성) 유지, 인스타·쓰레드 등 외부에서 데려오기.
  800자 이상 정리 글은 전달이 2.3배, 영상·파일·링크는 1.6~1.9배.
- growth: 우리 채널을 키우기 위해 이번 주 해볼 것 3~5개. 다른 방 데이터와 우리 채널 성과(my_stats, my_top_posts)를 근거로, 무엇을·언제·어떻게를 근거 수치와 함께 한 줄씩.
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
    x = SITE / "x_ai.json"   # X·트루스소셜(트럼프·백악관·시장 속보) 오늘 브리핑
    x_brief = (json.loads(x.read_text(encoding="utf-8") or "{}").get("briefing") or []) if x.exists() else []
    return {"headlines": heads, "news_topics": topics, "instagram_recommended": recs, "x_truth_briefing": x_brief}


REFRESH_HOURS = (7, 12, 18)   # 하루 3번 최신 뉴스로 다시 씀 (07시·12시·18시 이후 첫 갱신 때)


def is_due(ai_path, now):
    """마지막으로 쓴 뒤 07·12·18시 중 하나를 지났으면 다시 쓸 차례."""
    passed = [h for h in REFRESH_HOURS if now.hour >= h]
    if not passed:
        return False
    if not ai_path.exists():
        return True
    last = json.loads(ai_path.read_text(encoding="utf-8") or "{}").get("analyzed_at", "")
    if not last:
        return True
    slot_start = now.replace(hour=passed[-1], minute=0, second=0, microsecond=0)
    return datetime.fromisoformat(last).astimezone(KST) < slot_start


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="차례가 아니어도 Claude 추천을 다시 씀")
    ap.add_argument("--scheduled", action="store_true", help="정해진 시각(07·12·18시) 갱신: 뉴스·인기 글이 그대로면 다시 안 씀")
    ap.add_argument("--due", action="store_true", help="다시 쓸 차례면 0, 아니면 3 으로 끝냄 (워크플로가 뉴스부터 새로 받을지 정할 때)")
    ap.add_argument("--focus", default=os.environ.get("TG_FOCUS", ""), help="이번에 특히 반영할 요청 (예: '지금 하락장')")
    args = ap.parse_args()
    if args.due:
        sys.exit(0 if is_due(SITE / "tg_ai.json", datetime.now(KST)) else 3)
    load_env()
    if SRC.exists():  # 내 PC에서 직접 모은 파일이 있으면 통계부터 새로 (서버에서는 tg_live.py 가 올린 통계를 그대로 씀)
        out = build(json.loads(SRC.read_text(encoding="utf-8")), datetime.now(timezone.utc))
        SITE.mkdir(parents=True, exist_ok=True)
        for name, rows in out.items():
            (SITE / f"{name}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"✅ 텔레그램 통계: 방 {out['tg_meta'][0]['chats']}개, 반응 큰 글 {len(out['tg_hot'])}개")
    load = lambda n: json.loads((SITE / f"{n}.json").read_text(encoding="utf-8")) if (SITE / f"{n}.json").exists() else []
    out = {n: load(n) for n in ("tg_hot", "tg_hours", "tg_lengths", "tg_mine", "tg_chats")}
    if not out["tg_hot"]:
        print("텔레그램 통계가 아직 없어요 — 분석을 건너뛰어요 (TELEGRAM_SETUP.md 참고).")
        return
    # 사이트는 30분마다 갱신되고, Claude 추천은 하루 3번(07·12·18시 이후 첫 갱신) 최신 뉴스로 다시 쓴다
    ai_path = SITE / "tg_ai.json"
    if not args.force and not args.scheduled and not args.dry_run and not is_due(ai_path, datetime.now(KST)):
        print("이번 차례 텔레그램 추천은 이미 썼어요 (07·12·18시에 다시 써요) — 건너뛰어요.")
        return

    hot = out["tg_hot"][:25]
    items = [{"no": i, "room": h["chat"], "x": h["x"], "views": h["views"], "reactions": h["reactions"], "replies": h["replies"],
              "media": h["media"], "time": h["time"], "text": h["text"]} for i, h in enumerate(hot, 1)]
    ctx = {"hot_posts": items, "best_slots": out["tg_hours"], "lengths": out["tg_lengths"],
           "my_recent_posts": [m["text"][:400] for m in out["tg_mine"][:8]],
           "my_top_posts": [{"x": m["x"], "views": m["views"], "reactions": m["reactions"], "time": m["time"], "text": m["text"][:300]}
                            for m in sorted(out["tg_mine"], key=lambda m: -(m["x"] or 0))[:5]],
           "my_stats": [c for c in out["tg_chats"] if c["role"] == "mine"], "today": news_context(),
           "date": datetime.now(KST).strftime("%Y-%m-%d (%a)"), "now_kst": datetime.now(KST).strftime("%H:%M")}
    prompt = "자료:\n" + json.dumps(ctx, ensure_ascii=False, indent=1)
    from feedback import feedback_prompt
    prompt += feedback_prompt(["텔레그램", "텔레그램 문구"])   # 사이트에서 남긴 후기
    if args.focus:
        prompt += f"\n\n대표의 이번 요청 (가장 우선해서 반영): {args.focus}"
    room = next((c["title"] for c in out["tg_chats"] if c["role"] == "mine"), "우리 채널")
    # 비용 절약: 정해진 시각 갱신인데 헤드라인·다른 방 인기 글이 지난번과 같으면 다시 쓰지 않음
    news_key = hashlib.sha1(json.dumps([ctx["today"]["headlines"][:10], [h["text"][:60] for h in hot[:10]], args.focus],
                                       ensure_ascii=False).encode()).hexdigest()
    last_key = json.loads(ai_path.read_text(encoding="utf-8") or "{}").get("news_key") if ai_path.exists() else None
    if args.scheduled and not args.force and last_key == news_key:
        print("뉴스·인기 글이 지난번과 같아 텔레그램 추천을 다시 쓰지 않아요 (비용 절약).")
        return
    if args.dry_run:
        print(SYSTEM.format(room=room), "\n\n", prompt[:3000])
        return
    digest = hashlib.sha1(prompt.encode()).hexdigest()
    if ai_path.exists() and json.loads(ai_path.read_text(encoding="utf-8") or "{}").get("digest") == digest:
        print("입력이 같아 지난 텔레그램 추천을 그대로 써요.")
        return
    if not hot:
        print("반응 큰 글이 아직 없어 Claude 추천을 건너뛰어요.")
        return
    if not __import__("llm").ready():
        print("Claude Code(Max) 가 없는 곳이라 Claude 추천을 건너뛰어요 — 지난 결과를 유지해요.")
        return

    import llm as anthropic   # 내 PC Claude Code(Max 구독)로 실행 — API 요금 없음
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
        growth: List[str]
        posts: List[PostNote]

    client = anthropic.Anthropic()
    try:
        r = client.messages.parse(model=MODEL, max_tokens=16000, system=SYSTEM.format(room=room),
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
                                   "today": [t.model_dump() for t in a.today], "growth": a.growth, "posts": notes, "room": room, "news_key": news_key},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ 텔레그램 추천: 오늘 문구 {len(a.today)}개 · 공식 {len(a.formulas)}개 "
          f"(입력 {r.usage.input_tokens:,} / 출력 {r.usage.output_tokens:,} 토큰)")


if __name__ == "__main__":
    sys.exit(main())
