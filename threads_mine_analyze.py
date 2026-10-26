"""황소개미(@bullant_economy) 쓰레드 계정 일일 진단 — AI 티 점검, 프로필 피드 점검, 솔루션·다음 글 초안 → output/site/thm_ai.json

    python threads_mine_analyze.py            # ANTHROPIC_API_KEY 필요
    python threads_mine_analyze.py --dry-run  # 프롬프트만 출력
진단 기준(AI 티 신호 S1~S10, 형식 믹스 목표 등)은 Social Media Strategist 에이전트가 설계한 것 (추정치 포함, 2~4주 뒤 보정).
글이 그대로면 다시 부르지 않는다.
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from typing import List

from common import OUTPUT_DIR, load_env

MODEL = "claude-sonnet-5-5"   # 쓰레드 분석은 Sonnet (대표 결정 2026-10-26)
SITE = OUTPUT_DIR / "site"
OUT = SITE / "thm_ai.json"

SYSTEM = """너는 경제 쓰레드 계정 '황소개미'(@bullant_economy)의 일일 성장 감사관이다.
입력: 최근 약 30개 글(시각, 조회·좋아요·답글·리포스트·인용·공유, 반응률, 확산배수, 첫 줄 유형, 길이, 주제), 팔로워 수, 계정 지표,
같은 주 한국 경제 쓰레드 글 중앙값(벤치마크), 프로필 첫 화면(최근 12개)의 구성과 자동 경고, 지난 진단의 watch_items.
목표: 팔로워를 늘리는 것. ① AI 티 점검 ② 정보 품질 점검(양질의 정보는 필수) ③ 프로필을 스크롤한 방문자가 팔로우하고 싶은 피드인지 ④ 바로 실행할 해법과 일주일 계획.
추가 입력: today_info(연구소가 오늘 모은 경제 매체 헤드라인·X/트루스 브리핑·쓰레드에서 반응 큰 주제), engage_targets(우리 분야에서 조회가 큰 계정·글).

[AI 티 신호, 각 1~5점(5가 가장 AI 같음)]
S1 불릿·번호 남용 / S2 줄마다 같은 자리 이모지 / S3 '~입니다·~할 수 있습니다' 교과서 종결 비율 / S4 판박이 도입·마무리(첫·끝 문장 반복)
S5 숫자·날짜·종목·출처 없는 일반론 / S6 화자 부재(1인칭·감정·입장 없음) / S7 과도한 대칭·고른 문장 길이 / S8 설명 없는 전문용어 나열
S9 결론 회피 양비론 / S10 번역투 접속사('또한/따라서/결론적으로/~에 있어서')

[정보 품질, 글마다 1~5점(5가 가장 좋음)]
근거(숫자·날짜·출처가 있나) / 정확성(틀리거나 과장된 말 없나) / 새로움(뉴스 재탕이 아니라 해석·연결이 있나) / 쓸모(읽고 나서 판단·행동에 도움 되나).
양질의 정보 없이 반응만 노린 글(자극적 제목, 근거 없는 전망)은 단기 조회가 높아도 팔로우로 이어지지 않으니 낮게 평가한다.

[팔로우 성장 원칙]
- 팔로우는 '이 계정을 계속 보면 손해 안 본다'는 확신에서 나온다: 매일 같은 시간에, 검증된 정보 + 내 해석.
- 노출: 우리 분야에서 조회 큰 계정 글에 빨리(올라온 지 1시간 안) 의미 있는 댓글(숫자·관점 한 줄)을 달아 프로필 방문을 만든다.
- 재방문: 이름 붙은 시리즈(예: 아침 3줄, 틀린 예측 회고) + 고정글로 '팔로우하면 얻는 것' 약속.
- 저장·공유: 정리형·체크리스트형 글이 공유가 많다. 공유 많은 형식을 주 2~3회.

[피드 기준 (추정치)]
정체성: 최근 12개만 보고 "○○한 사람이 △△을 □□하게 알려주는 계정" 한 줄이 나와야 함.
주제 비율: 핵심(주식·거시) 60 / 인접(코인·재테크) 30 / 실험 10.
형식 믹스: 정보·해설 30 / 의견·해석 25 / 경험·고백 15 / 질문·참여 15 / 짧은 한 줄 15.
반복 피로: 같은 형식 3연속, 첫 문장 패턴 반복, 같은 종목 12개 중 4회 이상. 시리즈 코너 1~2개(12개 중 2~4개)가 적당.
빈도: 하루 1~3개, 글 사이 3시간 이상, 48시간 이상 공백은 경고. 고정글이 '팔로우하면 얻는 것'을 보여주는지(데이터 없으면 확인 요청).

[절차]
1) 글마다 형식(정보/의견/경험/질문/한줄)을 판단해 피드 형식 믹스를 계산한다.
2) S1~S10 점수와 근거 인용, AI 티가 가장 강한 글 3개와 사람 말투로 고친 버전.
3) 정체성 한 줄, 목표 대비 부족한 형식·주제, 반복 피로.
4) 반응 상위·하위 3개 글과 이유(올린 지 24시간 안 된 글은 비교에서 뺌, 벤치마크와 비교).
5) 우선순위 해법 5개(what/why=근거 지표/how=구체 실행/expected=무슨 숫자가 좋아지면 성공).
6) 피드에서 부족한 형식 위주로 바로 올릴 초안 3개 — 반드시 today_info 의 실제 뉴스·숫자를 근거로 쓰고 sources 에 근거를 적는다.
7) 일주일 계획(7일, 하루 1~2개: 요일·시간·형식·주제·첫 줄)과 댓글 노출 전략(engage_targets 중 어디에 어떤 댓글을 달지 3개).

[규칙]
- 숫자는 입력 데이터로 계산한 값만. 추정은 '추정' 표시, 없는 데이터는 data_gaps 에.
- 표본 3개 미만 그룹은 '판단 보류'.
- 특정 종목·코인 매수·매도, 목표가, 수익 보장 표현 금지. 초안도 관찰·해석까지만.
- 모두 한국어. 초안은 사람 말투: 종결어미 섞기, 1인칭, 구체 숫자·날짜 1개 이상, 불릿 최대 3개, 이모지 최대 1개, 해시태그 최대 1개,
  '또한/따라서/결론적으로/여러분은 어떻게 생각하시나요?' 같은 상투구 금지.
- 비판은 글 번호(no)와 인용으로 근거를 댄다. 지난 watch_items 가 있으면 먼저 변화를 보고한다."""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    load_env()
    load = lambda n: json.loads((SITE / f"{n}.json").read_text(encoding="utf-8")) if (SITE / f"{n}.json").exists() else []
    meta, posts, feed = load("thm_meta"), load("thm_posts"), load("thm_feed")
    if not posts:
        print("황소개미 글이 아직 없어요 — 진단을 건너뛰어요.")
        return
    prev = json.loads(OUT.read_text(encoding="utf-8") or "{}") if OUT.exists() else {}
    items = [{"no": i, "time": p["time"], "views": p["views"], "likes": p["likes"], "replies": p["replies"], "reposts": p["reposts"],
              "quotes": p["quotes"], "shares": p["shares"], "rate": p["rate"], "spread": p["spread"], "hook": p["hook"],
              "length": p["length"], "media": p["media"], "topics": p["topics"], "text": p["text"]} for i, p in enumerate(posts, 1)]
    x = load("x_ai")
    today_info = {"headlines": [f"[{h['source']}] {h['title']}" for h in load("press_headlines")[:15]],
                  "x_truth_briefing": (x.get("briefing") if isinstance(x, dict) else []) or [],
                  "threads_hot_topics": [f"{t.get('topics') or '주제 미상'} — {t['text'][:60]} (조회 {t.get('views')})" for t in load("thx_top")[:5]]}
    engage = [{"account": "@" + h["username"], "views": h["views"], "followers": h["followers"], "url": h["url"], "text": h["text"][:120]}
              for h in [r for r in load("thx_rank") if r.get("list") == "views"][:8]]
    ctx = {"account": meta[0] if meta else {}, "feed_first12": feed[0] if feed else {}, "posts": items,
           "today_info": today_info, "engage_targets": engage, "last_watch_items": prev.get("watch_items", [])}
    digest = hashlib.sha1(json.dumps([(i["text"][:80], i["views"]) for i in items], ensure_ascii=False).encode()).hexdigest()
    prompt = "황소개미 계정 데이터:\n" + json.dumps(ctx, ensure_ascii=False, indent=1)
    from feedback import feedback_prompt
    prompt += feedback_prompt(["황소개미 진단"])
    if args.dry_run:
        print(SYSTEM, "\n\n", prompt[:3000])
        return
    if prev.get("digest") == digest:
        print("황소개미 글·숫자가 그대로라 지난 진단을 써요.")
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY 가 없어 진단을 건너뛰어요.")
        return

    import anthropic
    from pydantic import BaseModel

    class Signal(BaseModel):
        id: str
        score: int
        evidence: str

    class AiPost(BaseModel):
        no: int
        excerpt: str
        signals: List[str]
        rewrite: str

    class PostWhy(BaseModel):
        no: int
        excerpt: str
        why: str

    class Solution(BaseModel):
        priority: int
        what: str
        why: str
        how: str
        expected: str

    class Draft(BaseModel):
        format: str
        topic: str
        text: str
        why_now: str
        sources: List[str]

    class Quality(BaseModel):
        no: int
        score: int
        issue: str

    class PlanDay(BaseModel):
        day: str
        time: str
        format: str
        topic: str
        hook: str

    class Engage(BaseModel):
        target: str
        url: str
        comment: str

    class MixItem(BaseModel):
        key: str
        share: int
        target: int

    class Audit(BaseModel):
        overall_grade: str
        grade_reason: str
        identity_line: str
        changes_since_last: str
        ai_score: float
        ai_signals: List[Signal]
        ai_worst: List[AiPost]
        quality_score: float
        quality_low: List[Quality]
        format_mix: List[MixItem]
        feed_issues: List[str]
        top_posts: List[PostWhy]
        bottom_posts: List[PostWhy]
        solutions: List[Solution]
        next_posts: List[Draft]
        week_plan: List[PlanDay]
        engage: List[Engage]
        watch_items: List[str]
        data_gaps: List[str]

    client = anthropic.Anthropic()
    try:
        with client.messages.stream(model=MODEL, max_tokens=24000, system=SYSTEM, output_config={"effort": "medium"},
                                    messages=[{"role": "user", "content": prompt}], output_format=Audit) as stream:
            r = stream.get_final_message()
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
        print(f"⚠️ Claude API 오류: {e} — 지난 진단을 유지해요.")
        return
    if r.stop_reason != "end_turn" or r.parsed_output is None:
        print(f"⚠️ 진단 결과를 받지 못했어요({r.stop_reason}) — 지난 진단을 유지해요.")
        return
    a = r.parsed_output.model_dump()
    by_no = {i: p for i, p in enumerate(posts, 1)}
    for key in ("ai_worst", "top_posts", "bottom_posts"):
        for x in a[key]:
            x["url"] = (by_no.get(x["no"]) or {}).get("url", "")
    OUT.write_text(json.dumps({"digest": digest, "analyzed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **a},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ 황소개미 진단 (등급 {a['overall_grade']}, AI 티 {a['ai_score']}) · 입력 {r.usage.input_tokens:,} / 출력 {r.usage.output_tokens:,} 토큰")


if __name__ == "__main__":
    sys.exit(main())
