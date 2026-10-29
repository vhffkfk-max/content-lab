"""시황맨(@shmstory) 아침·마감 시황을 '말희아빠 아침시황/마감시황' 스타일로 다시 써서 output/site/tg_rewrites.json 에 저장한다.

    python tg_rewrite.py            # 내 PC Claude Code(Max) 필요 (텔레그램 워크플로가 갱신 때마다 부름)
    python tg_rewrite.py --dry-run  # 무엇을 변환할지만 출력
원문(output/site/tg_source.json)은 내 PC의 tg_live.py 가 새 시황이 올라오는 즉시 올린다.
이미 변환한 글은 다시 부르지 않는다. 문체 예시는 tg_style_malhee.txt.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

from common import OUTPUT_DIR, ROOT, load_env

MODEL = "claude-opus-5-5"   # 실제로 올리는 글이라 Opus (대표 결정)
SITE = OUTPUT_DIR / "site"
SRC, OUT = SITE / "tg_source.json", SITE / "tg_rewrites.json"
KST = timezone(timedelta(hours=9))
KEEP = 20

SYSTEM = """당신은 텔레그램 채널 '차트보는 말희아빠'의 시황 에디터입니다.
다른 채널의 시황 글(원문)을 받아, 같은 사실과 숫자를 바탕으로 '말희아빠 {kind}시황'을 새로 씁니다.

반드시 지킬 것:
- 문체·구성은 아래 [말희아빠 예시]를 따릅니다: 첫 줄 '🥛🥛 {date} 말희아빠 {kind}시황', 둘째 단락에 오늘의 한 줄 제목,
  짧은 단락 사이에 빈 줄 대신 '⁣'(보이지 않는 문자) 한 줄, 😵·🤑·🤒 같은 소제목 이모지, 원인→결과 화살표 흐름,
  ✔️ 체크리스트, 마지막 '🎃 오늘의 시장 한줄 평'.
- 원문 문장을 그대로 옮기지 않습니다. 사실·숫자·종목명·일정은 유지하되 문장은 모두 새로 쓰고, 순서와 소제목도 우리 식으로 재구성합니다.
- 원문에 없는 숫자·사실을 지어내지 않습니다. 확실하지 않은 건 [확인]으로 둡니다.
- 특정 종목 매수·매도 권유, 목표가, 수익 보장 표현을 쓰지 않습니다.
- 원문 채널 이름(시황맨 등)이나 서명은 넣지 않습니다.
- 마감시황이면 '오늘 장에서 무슨 일이 있었나 → 왜 → 내일 볼 것' 흐름, 아침시황이면 '밤사이 미국장 → 오늘 핵심 → 이번 주/오늘 체크' 흐름.
- text 는 그대로 복사해 올릴 완성본. check 는 올리기 전에 대표가 확인할 것(지수·숫자 등) 1~3개."""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    load_env()
    sources = json.loads(SRC.read_text(encoding="utf-8")) if SRC.exists() else []
    done = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else []
    have = {d["source_id"] for d in done}
    since = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    todo = [s for s in sources if s["kind"] in ("아침", "마감") and s["id"] not in have and s["date"] >= since]
    if not todo:
        print("새로 변환할 시황이 없어요.")
        return
    print("변환할 시황:", ", ".join(f"{s['kind']} {s['time']}" for s in todo))
    if args.dry_run:
        return
    if not __import__("llm").ready():
        print("Claude Code(Max) 가 없는 곳이라 시황 변환을 건너뛰어요.")
        return
    import llm as anthropic   # 내 PC Claude Code(Max 구독)로 실행 — API 요금 없음
    from pydantic import BaseModel

    class Rewrite(BaseModel):
        text: str
        check: list[str]

    style = (ROOT / "tg_style_malhee.txt").read_text(encoding="utf-8")
    client = anthropic.Anthropic()
    for s in todo[-2:]:   # 밀린 게 있어도 최근 2개만 (비용)
        dt = datetime.fromisoformat(s["date"]).astimezone(KST)
        date = f"{dt.month}월 {dt.day}일({'월화수목금토일'[dt.weekday()]})"
        prompt = f"[말희아빠 예시]\n{style}\n\n[오늘 원문 — {s['kind']} 시황, {s['time']}]\n{s['text']}"
        try:
            with client.messages.stream(model=MODEL, max_tokens=8000, system=SYSTEM.format(kind=s["kind"], date=date),
                                        messages=[{"role": "user", "content": prompt}], output_format=Rewrite) as stream:
                r = stream.get_final_message()
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            print(f"⚠️ Claude API 오류: {e}")
            continue
        if r.stop_reason != "end_turn" or r.parsed_output is None:
            print(f"⚠️ 변환 결과를 받지 못했어요({r.stop_reason})")
            continue
        done.append({"source_id": s["id"], "kind": s["kind"], "source_time": s["time"], "source_link": s["link"],
                     "made_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "text": r.parsed_output.text, "check": r.parsed_output.check})
        print(f"✅ {s['kind']}시황 변환 ({s['time']}, 입력 {r.usage.input_tokens:,} / 출력 {r.usage.output_tokens:,} 토큰)")
    OUT.write_text(json.dumps(done[-KEEP:], ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
