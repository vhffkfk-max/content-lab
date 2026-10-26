"""X·트루스소셜 경제 관련 글을 Claude로 한국어 요약·영향 분석해 output/site/x_ai.json 에 저장한다.

    python x_analyze.py            # ANTHROPIC_API_KEY 필요
    python x_analyze.py --dry-run  # API 호출 없이 프롬프트만 출력
대상: 트럼프 최신 글 + 최근 48시간 조회수·리포스트·답글 TOP (x_score.py). 입력이 같으면 다시 부르지 않는다.
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from typing import List

from common import DEFAULT_DB, OUTPUT_DIR, connect, load_env

MODEL = "claude-haiku-5-5"   # 요약·번역이라 Haiku (비용 절약, 대표 결정 2026-10-26)
OUT = OUTPUT_DIR / "site" / "x_ai.json"

SYSTEM = """당신은 한국 경제 크리에이터 팀(@hotconomy, 차트보는 말희아빠)의 해외 시장 리서처입니다.
X(트위터)와 트럼프의 트루스소셜 글 중 경제에 영향을 줄 만한 글을 받아, 한국 투자자에게 무슨 의미인지 정리합니다.

규칙:
- 모두 한국어. 이모지 금지. 원문에 없는 사실·숫자는 지어내지 않습니다(필요하면 [확인]).
- 특정 종목 매수·매도 권유, 가격 방향 단정을 하지 않습니다. '영향을 받을 수 있는 자산·업종'과 '왜 그런지'만 씁니다.
- briefing: 오늘 X·트루스 경제 흐름 4~6줄 (각 70자 안팎, 가장 중요한 것부터).
- posts: 받은 글마다 no(번호 그대로), summary_ko(무슨 말인지 1~2문장 번역·요약), impact(영향 받을 수 있는 자산·업종과 이유 1~2문장,
  경제와 무관하면 '경제 영향 적음'), why(조회·리포스트·답글이 많았다면 왜 퍼졌는지 1문장, 반응 수치가 작으면 빈 문자열),
  idea(우리 인스타·쓰레드·텔레그램에 쓸 콘텐츠 각도 1문장, 쓸 게 없으면 빈 문자열), importance(1~5, 한국 투자자에게 중요한 정도)."""


def load(db):
    import x_score
    sec = x_score.section(connect(db), datetime.now(timezone.utc))
    picked, ids = [], set()
    for h in sec["trump"][:10] + [r for r in sec["rank"]]:
        if h["id"] not in ids:
            ids.add(h["id"])
            picked.append(h)
    return picked[:40]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    args = ap.parse_args()
    load_env()
    posts = load(args.db)
    if not posts:
        print("X·트루스 글이 아직 없어요 — 분석을 건너뛰어요.")
        return
    items = [{"no": i, "platform": p["platform"], "author": p["username"], "group": p["group"], "followers": p["followers"],
              "views": p["views"], "likes": p["likes"], "reposts": p["reposts"], "replies": p["replies"], "time": p["time"],
              "text": p["text"][:900]} for i, p in enumerate(posts, 1)]
    digest = hashlib.sha1(json.dumps([(i["author"], i["text"]) for i in items], ensure_ascii=False).encode()).hexdigest()
    prompt = "X·트루스소셜 글:\n" + json.dumps(items, ensure_ascii=False, indent=1)
    from feedback import feedback_prompt
    prompt += feedback_prompt(["X", "트루스소셜"])   # 사이트에서 남긴 후기
    if args.dry_run:
        print(SYSTEM, "\n\n", prompt[:3000])
        return
    if OUT.exists() and json.loads(OUT.read_text(encoding="utf-8") or "{}").get("digest") == digest:
        print("새 X·트루스 글이 없어 지난 분석을 그대로 써요.")
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY 가 없어 X 분석을 건너뛰어요 — 지난 결과를 유지해요.")
        return

    import anthropic
    from pydantic import BaseModel

    class Note(BaseModel):
        no: int
        summary_ko: str
        impact: str
        why: str
        idea: str
        importance: int

    class Analysis(BaseModel):
        briefing: List[str]
        posts: List[Note]

    client = anthropic.Anthropic()
    try:
        with client.messages.stream(model=MODEL, max_tokens=24000, system=SYSTEM, output_config={"effort": "low"},   # 요약·번역이라 생각량 낮춤 (비용 절약)
                                   
                                    messages=[{"role": "user", "content": prompt}], output_format=Analysis) as stream:
            r = stream.get_final_message()
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
        print(f"⚠️ Claude API 오류: {e} — 지난 결과를 유지해요.")
        return
    if r.stop_reason != "end_turn" or r.parsed_output is None:
        print(f"⚠️ 결과를 받지 못했어요(stop_reason={r.stop_reason}) — 지난 결과를 유지해요.")
        return
    a = r.parsed_output
    by_no = {i: p for i, p in enumerate(posts, 1)}
    notes = [{**n.model_dump(), "id": by_no[n.no]["id"]} for n in a.posts if n.no in by_no]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"digest": digest, "analyzed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                               "briefing": a.briefing, "posts": notes}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ X·트루스 글 {len(posts)}개 분석 (입력 {r.usage.input_tokens:,} / 출력 {r.usage.output_tokens:,} 토큰)")


if __name__ == "__main__":
    sys.exit(main())
