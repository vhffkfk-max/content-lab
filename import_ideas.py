"""해외 계정에서 터졌지만 한국에는 아직 안 풀린 콘텐츠를 Claude로 골라 output/site/imports.json 에 저장한다.

    python import_ideas.py            # ANTHROPIC_API_KEY 필요
    python import_ideas.py --dry-run  # API 호출 없이 프롬프트만 출력

근거 자료: 해외 계정의 최근 14일 반응 상위 게시물 / 같은 기간 한국 계정 게시물 첫 줄 / 한국 경제 매체·구글 뉴스 제목.
실패하면 지난 결과를 그대로 둔다.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import List

from common import DEFAULT_DB, OUTPUT_DIR, connect, load_env

MODEL = "claude-haiku-5-5"   # 요약·번역이라 Haiku (비용 절약, 대표 결정 2026-10-26)
OUT = OUTPUT_DIR / "site" / "imports.json"

SYSTEM = """당신은 한국 경제 인스타그램 계정 @hotconomy 의 리서처입니다.
해외 경제 인스타 계정에서 반응이 컸던 게시물 중, 한국 인스타·한국 경제 뉴스에서 아직 다뤄지지 않은 것을 찾아
한국 팔로워용 콘텐츠로 들여올 아이디어를 고릅니다.

규칙:
- 후보는 '해외 게시물' 목록에서만 고르고 source 에 그 번호를 그대로 적습니다. 최대 6개, 좋은 것이 적으면 적게 고릅니다.
- 한국 계정 게시물·한국 뉴스 제목 목록에 같은 소재(같은 종목, 같은 사건, 같은 개념·방법)가 이미 있으면 고르지 않습니다.
  why_new 에는 "한국 계정 게시물 N개·한국 뉴스 제목에서 같은 소재를 찾지 못했다"처럼 제공된 자료 기준으로만 근거를 씁니다. 자료 밖의 사실을 단정하지 않습니다.
- 거래소 상장 기념, 회사 행사 사진, 광고·이벤트처럼 콘텐츠 소재가 아닌 게시물은 고르지 않습니다.
- 한국 투자자에게 의미가 없는 미국 전용 제도(예: 401k)는, 한국에 비슷한 제도(연금저축·IRP·ISA 등)로 바꿔 설명할 수 있을 때만 고르고 local_angle 에 그 연결을 씁니다.
- 모든 출력은 한국어. 이모지 금지. 데이터에 없는 수치는 지어내지 말고 [확인]으로 비웁니다.
- 특정 종목 매수·매도 권유, 수익 보장, 매수 시점 암시 표현을 쓰지 않습니다.
- title 은 한국 팔로워용 제목(정보가 담긴 문장, 30자 안팎), summary 는 원 게시물이 무슨 내용인지 한 줄,
  local_angle 은 한국 팔로워에게 맞게 바꾸는 방법, structure 는 3~5단계 구성(형식에 맞게), caution 은 들여올 때 주의할 점 한 줄."""


def load_context(db):
    report = json.loads((OUTPUT_DIR / "report.json").read_text(encoding="utf-8"))
    fo = report.get("foreign") or {}
    conn = connect(db)
    since = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat(timespec="seconds")
    news = []
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "press_news" in tables:
        news += [r[0] for r in conn.execute("SELECT title FROM press_news WHERE region='KR' AND published>=? ORDER BY published DESC LIMIT 250", (since,))]
    if "google_news" in tables:
        news += [r[0] for r in conn.execute("SELECT title FROM google_news WHERE region='KR' AND published>=? ORDER BY published DESC LIMIT 150", (since,))]
    return fo.get("hot") or [], fo.get("kr_lines") or [], news


def build_prompt(hot, kr_lines, news):
    items = [{"no": h["rank"], "account": h["username"], "x": h["outlier"], "format": h["format"], "topics": h["topics"],
              "caption": h.get("full") or h["caption"]} for h in hot[:25]]
    return (f"해외 게시물 (평소 대비 반응 배수 x):\n{json.dumps(items, ensure_ascii=False, indent=1)}\n\n"
            f"같은 기간 한국 경제 인스타 계정 게시물 첫 줄 {len(kr_lines)}개:\n" + "\n".join(f"- {l}" for l in kr_lines) +
            f"\n\n같은 기간 한국 경제 뉴스 제목 {len(news)}개:\n" + "\n".join(f"- {t}" for t in news))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    args = ap.parse_args()
    load_env()
    hot, kr_lines, news = load_context(args.db)
    if not hot:
        print("해외 상위 게시물이 없어 건너뛰어요.")
        return
    prompt = build_prompt(hot, kr_lines, news)
    from feedback import feedback_prompt
    prompt += feedback_prompt(["해외 인스타"])   # 사이트에서 남긴 후기
    if args.dry_run:
        print(SYSTEM, "\n\n", prompt[:3000], "\n…")
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY 가 없어 해외 아이디어 찾기를 건너뛰어요 — 지난 결과를 유지해요.")
        return

    import anthropic
    from pydantic import BaseModel

    class Idea(BaseModel):
        source: int
        title: str
        summary: str
        why_new: str
        local_angle: str
        format: str
        hook: str
        structure: List[str]
        caution: str

    class Ideas(BaseModel):
        ideas: List[Idea]

    client = anthropic.Anthropic()
    try:
        response = client.messages.parse(model=MODEL, max_tokens=16000, system=SYSTEM, output_config={"effort": "low"},   # 비용 절약
                                        
                                         messages=[{"role": "user", "content": prompt}], output_format=Ideas)
    except anthropic.APIStatusError as e:
        print(f"⚠️ Claude API 오류({e.status_code}): {e.message} — 지난 결과를 유지해요.")
        return
    except anthropic.APIConnectionError:
        print("⚠️ Claude API 연결 실패 — 지난 결과를 유지해요.")
        return
    if response.stop_reason != "end_turn" or response.parsed_output is None:
        print(f"⚠️ 결과를 받지 못했어요(stop_reason={response.stop_reason}) — 지난 결과를 유지해요.")
        return
    by_rank = {h["rank"]: h for h in hot}
    rows = []
    for i, idea in enumerate(response.parsed_output.ideas, 1):
        src = by_rank.get(idea.source)
        if not src:  # 목록에 없는 번호는 버린다 (지어낸 출처 방지)
            continue
        rows.append({"n": i, **idea.model_dump(), "account": src["username"], "x": src["outlier"],
                     "src_format": src["format"], "src_caption": src["caption"], "permalink": src["permalink"],
                     "date": src["date"], "kr_checked": len(kr_lines), "news_checked": len(news)})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    u = response.usage
    print(f"✅ 한국 미출시 해외 아이디어 {len(rows)}개 (입력 {u.input_tokens:,} / 출력 {u.output_tokens:,} 토큰)")


if __name__ == "__main__":
    sys.exit(main())
