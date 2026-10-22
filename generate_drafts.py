"""추천 결과(output/report.json)를 읽고 Claude API로 추천마다 콘텐츠 기획안을 써서 output/site/drafts.json 에 저장한다.

    python generate_drafts.py            # ANTHROPIC_API_KEY 필요
    python generate_drafts.py --dry-run  # API 호출 없이 프롬프트만 출력

API 호출이 실패하거나 거절되면 기존 drafts.json 을 그대로 둔다 (사이트는 지난 기획안을 계속 보여준다).
"""
import argparse
import collections
import json
import os
import re
import sys
from typing import List

from common import DEFAULT_DB, OUTPUT_DIR, connect, load_env

MODEL = "claude-opus-5-5"
DRAFTS = OUTPUT_DIR / "site" / "drafts.json"

BRAND_TAG = os.environ.get("BRAND_TAG", "#핫코노미")

SYSTEM = f"""당신은 한국 경제 인플루언서 @hotconomy(인스타그램)의 콘텐츠 기획자입니다.
주어진 데이터(추천 주제, 추천 근거, 반응이 컸던 참고 게시물, 한국 계정들의 캡션·해시태그 패턴)를 바탕으로 추천마다 바로 제작할 수 있는 기획안을 씁니다.

규칙:
- 모두 한국어로, @hotconomy 팔로워에게 말하듯 쉽고 짧게 씁니다. 참고 게시물의 화자나 대상(예: 커플, 신혼부부)을 그대로 따라 하지 않습니다.
- 기획안 하나는 주제 하나만 다룹니다. 다른 주제의 뉴스를 섞지 않습니다.
- 추천 근거에 나온 분석 수치(배수, 게시물 수 증가 등)는 게시물 본문·캡션에 쓰지 않습니다. 팔로워에게는 의미 없는 정보입니다.
- 데이터에 없는 수치(가격, 금리, 실적, 퍼센트 등)는 절대 지어내지 말고 [ ] 로 비워 두거나 [확인] 이라고 적습니다.
- 제목에 검증할 수 없는 과장, 매수 시점 암시("지금 들어가도", "사야 할", "무조건"), 수익 보장 표현을 쓰지 않습니다. 클릭 유도용 자극적 질문 대신 정보가 담긴 문장을 씁니다.
- 특정 종목 매수·매도를 권하지 않습니다. 주식·코인·부동산·대출·연금 기획안의 캡션 끝에는 투자 권유가 아니라는 한 줄을 넣습니다.
- 이모지는 쓰지 않습니다.
- 제목 후보 3개는 추천된 첫 문장 스타일을 참고하되 서로 다른 각도로 씁니다.
- 구성(structure)은 추천 형식에 맞춥니다.
  릴스: '0~3초', '3~10초' 같은 시간 구간 4~5개. 0~3초 칸에는 "자막: …" 과 "대사: …" 를 나눠 쓰고, 첫 대사는 20자 안쪽.
  캐러셀(카드뉴스): '1장'~'6장'. 1장(표지)은 15자 안쪽 문구 하나, 마지막 장은 저장하고 싶어지는 요약표나 체크리스트.
  단일 이미지: '이미지 한 장' 1개 + '다른 형식으로 바꾼다면' 1개.
- 캡션 구조: 첫 줄(훅, 40자 이내) → 핵심 3줄 → 행동 유도 하나(댓글 질문 또는 저장 중 하나만) → 주의 문구. 캡션 길이·행동 유도는 제공된 한국 계정 패턴을 참고합니다.
- 해시태그는 5~7개: 브랜드 태그 {BRAND_TAG} 1개 + 주제 태그 3~4개 + 대형 태그 1~2개. 다른 계정·매체·채널·회사 이름 태그(예: #조선비즈, #부읽남, #업비트)는 넣지 않습니다.
- checks 에는 반드시 "수치 출처와 기준일 확인"과 "광고·협찬이면 첫 줄에 광고 표기"를 넣고, 그 외 1개까지 더합니다.
- differ 에는 참고 게시물과 다르게 할 점을 한 줄로 씁니다(베끼기 방지).
- 참고 게시물이 주제와 무관해 보이면(분류 오류) 무시하고 주제 자체로 기획합니다."""

# 금융 광고·유사투자자문 규제에 걸릴 수 있는 표현 (법률 자문 아님, 올리기 전 사람이 판단)
RISKY = [r"수익\s*보장", r"원금\s*보장", r"무조건", r"확정\s*수익", r"\d+\s*배\s*(간다|오른다|상승)", r"목표\s*가",
         r"리딩방", r"오픈\s*채팅", r"지금\s*(사야|사세요|매수|들어가)", r"(꼭|반드시)\s*(사세요|매수)", r"급등\s*(확정|예정)"]


def risky_phrases(text):
    return sorted({m.group(0) for pat in RISKY for m in re.finditer(pat, text)})


# 남의 브랜드·매체·정치인·텔레그램(리딩방 연상) 태그는 내 계정 성장에 도움이 안 돼서 후보에서 뺀다
NOT_MINE = ["토스", "업비트", "빗썸", "코인원", "급등일보", "부읽남", "슈카", "월부", "월급쟁이", "뉴닉", "조선비즈", "서울경제",
            "한국경제", "대신", "데일리랩업", "dailywrapup", "upbit", "bithumb", "event", "이벤트", "텔레그램", "안정감프로젝트",
            "안정식당", "findyoursafezone", "수요시장", "한국투자연구소", "뉴스클립", "이재명", "추미애", "윤석열", "민주당", "국민의힘"]


def top_hashtags(db_path, n=30):
    conn = connect(db_path)
    blocked = NOT_MINE + [(r[0] or "").lower() for r in conn.execute("SELECT username FROM accounts")]
    cnt = collections.Counter()
    for (cap,) in conn.execute("SELECT caption FROM posts p JOIN accounts a USING(username) WHERE a.region='KR'"):
        cnt.update(t.lower() for t in re.findall(r"#([\w가-힣]+)", cap or ""))
    tags = [t for t, _ in cnt.most_common(200) if not any(b and b in t for b in blocked)]
    return [f"#{t}" for t in tags[:n]]


def pattern_lines(report):
    out = []
    for key, label in (("ctas", "행동 유도"), ("lengths", "캡션 길이"), ("tagcounts", "해시태그 개수")):
        rows = [r for r in report[key]["한국"] if r["n"] >= 5]
        out.append(f"{label}: " + ", ".join(f"{r['key']} {r['avg']}배({r['n']}개)" for r in rows))
    return "\n".join(out)


def build_prompt(report, tags):
    recs = [{
        "topic": r["topic"], "kind": r["kind"], "format": r["format"], "hook": r["hook"], "slot": r["slot"],
        "confidence": r["confidence"], "reasons": r["reasons"],
        "examples": [{"account": e["username"], "region": e["region"], "x": e["outlier"],
                      "format": e["format"], "caption": e["caption"]} for e in r["examples"]],
    } for r in report["recommendations"]]
    return ("아래 추천 각각에 대해 기획안을 하나씩, 같은 순서로 써주세요. topic 값은 그대로 옮겨 적으세요.\n\n"
            f"추천 목록:\n{json.dumps(recs, ensure_ascii=False, indent=1)}\n\n"
            f"한국 경제 계정들의 캡션 패턴(평소 대비 반응):\n{pattern_lines(report)}\n\n"
            f"한국 경제 계정들이 많이 쓰는 해시태그(회사·매체 이름은 빼고 고를 것): {' '.join(tags)}")


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
        add("differ", 0, "참고 게시물과 다르게", p.differ)
        flagged = risky_phrases(" ".join([*p.titles, p.caption, *(x.text for x in p.structure)]))
        if flagged:
            add("warning", 0, "규제 주의 표현", "다음 표현은 금융 광고·투자 권유로 보일 수 있어요: " + ", ".join(flagged))
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

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY 가 없어 기획안 작성을 건너뛰어요 — 지난 기획안을 유지해요.")
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
        differ: str

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
