"""추천 결과(output/report.json)를 읽고 Claude API로 추천마다 콘텐츠 기획안을 써서 output/site/drafts.json 에 저장한다.

    python generate_drafts.py            # ANTHROPIC_API_KEY 필요
    python generate_drafts.py --dry-run  # API 호출 없이 프롬프트만 출력

API 호출이 실패하거나 거절되면 기존 drafts.json 을 그대로 둔다 (사이트는 지난 기획안을 계속 보여준다).
"""
import argparse
import collections
import json
import re
import sys
from typing import List

from common import DEFAULT_DB, OUTPUT_DIR, connect, load_env

MODEL = "claude-opus-5-5"
DRAFTS = OUTPUT_DIR / "site" / "drafts.json"

SYSTEM = """당신은 한국 경제 인플루언서(인스타그램)의 콘텐츠 기획자입니다.
주어진 데이터(추천 주제, 추천 근거, 반응이 컸던 참고 게시물, 한국 계정들이 많이 쓰는 해시태그)를 바탕으로 추천마다 바로 제작할 수 있는 기획안을 씁니다.

규칙:
- 모두 한국어로, 인스타그램 팔로워에게 말하듯 쉽고 짧게 씁니다.
- 데이터에 없는 수치(가격, 금리, 실적, 퍼센트 등)는 절대 지어내지 말고 [ ] 로 비워 두거나 [확인] 이라고 적습니다.
- 특정 종목 매수·매도를 권하지 않습니다. 주식·코인 캡션 끝에는 투자 권유가 아니라는 한 줄을 넣습니다.
- 이모지는 쓰지 않습니다.
- 제목 후보 3개는 추천된 첫 문장 스타일을 따르되 서로 다른 각도로 씁니다.
- 구성(structure)은 추천 형식에 맞춥니다: 릴스는 '0~3초', '3~10초' 같은 시간 구간 4~5개, 캐러셀(카드뉴스)은 '1장'~'6장', 단일 이미지는 '이미지 한 장' 1개 + 다른 형식으로 바꾼다면 1개.
- 해시태그는 제공된 인기 해시태그에서 주제에 맞는 것을 우선해 6~8개.
- checks 에는 올리기 전에 확인할 것(채워야 할 수치, 출처, 업로드 타이밍 등) 1~2개를 씁니다.
- 참고 게시물이 주제와 무관해 보이면(분류 오류) 무시하고 주제 자체로 기획합니다."""


def top_hashtags(db_path, n=40):
    conn = connect(db_path)
    cnt = collections.Counter()
    for (cap,) in conn.execute("SELECT caption FROM posts p JOIN accounts a USING(username) WHERE a.region='KR'"):
        cnt.update(t.lower() for t in re.findall(r"#([\w가-힣]+)", cap or ""))
    return [f"#{t}" for t, _ in cnt.most_common(n)]


def build_prompt(report, tags):
    recs = [{
        "topic": r["topic"], "kind": r["kind"], "format": r["format"], "hook": r["hook"], "slot": r["slot"],
        "confidence": r["confidence"], "reasons": r["reasons"],
        "examples": [{"account": e["username"], "region": e["region"], "x": e["outlier"],
                      "format": e["format"], "caption": e["caption"]} for e in r["examples"]],
    } for r in report["recommendations"]]
    return ("아래 추천 각각에 대해 기획안을 하나씩, 같은 순서로 써주세요. topic 값은 그대로 옮겨 적으세요.\n\n"
            f"추천 목록:\n{json.dumps(recs, ensure_ascii=False, indent=1)}\n\n"
            f"한국 경제 계정들이 많이 쓰는 해시태그: {' '.join(tags)}")


def to_rows(plans):
    rows = []
    for p in plans:
        add = lambda part, n, label, text: rows.append(
            {"topic": p.topic, "part": part, "n": n, "label": label, "text": text})
        for i, t in enumerate(p.titles):
            add("title", i, "제목 후보", t)
        for i, s in enumerate(p.structure):
            add("structure", i, s.label, s.text)
        add("caption", 0, "캡션", p.caption)
        add("hashtags", 0, "해시태그", " ".join(p.hashtags))
        for i, c in enumerate(p.checks):
            add("check", i, "올리기 전 확인", c)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    args = ap.parse_args()
    load_env()

    report = json.loads((OUTPUT_DIR / "report.json").read_text(encoding="utf-8"))
    if not report["recommendations"]:
        print("추천이 없어 기획안을 만들지 않았어요.")
        return
    prompt = build_prompt(report, top_hashtags(args.db))
    if args.dry_run:
        print(SYSTEM, "\n\n", prompt)
        return

    import anthropic
    from pydantic import BaseModel

    class Step(BaseModel):
        label: str
        text: str

    class Plan(BaseModel):
        topic: str
        titles: List[str]
        structure: List[Step]
        caption: str
        hashtags: List[str]
        checks: List[str]

    class Plans(BaseModel):
        plans: List[Plan]

    client = anthropic.Anthropic()
    try:
        response = client.messages.parse(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_format=Plans,
        )
    except anthropic.APIStatusError as e:
        print(f"⚠️ Claude API 오류({e.status_code}): {e.message} — 지난 기획안을 유지해요.")
        return
    except anthropic.APIConnectionError:
        print("⚠️ Claude API 연결 실패 — 지난 기획안을 유지해요.")
        return
    if response.stop_reason != "end_turn" or response.parsed_output is None:
        print(f"⚠️ 기획안을 받지 못했어요(stop_reason={response.stop_reason}) — 지난 기획안을 유지해요.")
        return

    rows = to_rows(response.parsed_output.plans)
    DRAFTS.parent.mkdir(parents=True, exist_ok=True)
    DRAFTS.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    u = response.usage
    print(f"✅ 기획안 {len(response.parsed_output.plans)}개 작성 (입력 {u.input_tokens:,} / 출력 {u.output_tokens:,} 토큰)")


if __name__ == "__main__":
    sys.exit(main())
