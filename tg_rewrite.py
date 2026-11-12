"""시황맨(@shmstory) 아침·마감 시황을 '말희아빠 아침시황/마감시황' 극요약 형식으로 다시 써서 output/site/tg_rewrites.json 에 저장하고,
핫코노미 봇(TELEGRAM_BOT_TOKEN)으로 '그대로 붙여넣을 본문' 1통 + '올리기 전 확인' 1통을 보낸다 (2026-11-12 대표 요청).

    python tg_rewrite.py            # 내 PC Claude Code(Max) 필요 (텔레그램 워크플로가 갱신 때마다 부름)
    python tg_rewrite.py --dry-run  # 무엇을 변환할지만 출력
    python tg_rewrite.py --redo     # 가장 최근 아침·마감 시황 하나를 지금 형식으로 다시 만들어 봇으로 보내기
원문(output/site/tg_source.json)은 내 PC의 tg_live.py 가 새 시황이 올라오는 즉시 올린다.
이미 변환한 글은 다시 부르지 않는다. 형식 예시는 tg_style_malhee.txt (대표가 올린 11/11 마감시황 극요약본).
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common import OUTPUT_DIR, ROOT, load_env

MODEL = "claude-opus-5-5"   # 실제로 올리는 글이라 Opus (대표 결정)
SITE = OUTPUT_DIR / "site"
SRC, OUT = SITE / "tg_source.json", SITE / "tg_rewrites.json"
KST = timezone(timedelta(hours=9))
KEEP = 20

SYSTEM = """당신은 텔레그램 채널 '차트보는 말희아빠'의 시황 에디터입니다.
다른 채널의 시황 글(원문)을 받아, 같은 사실과 숫자로 '말희아빠 {kind}시황'을 극요약 형식으로 새로 씁니다.
독자 피드백: 예전 시황은 길어서 한번에 보기 힘들었다 → 핵심만 짧게.

형식 ([말희아빠 예시]와 똑같은 모양):
- 첫 줄 '🐱 {date} 말희아빠 {kind}시황'
- 빈 줄 뒤 두 줄짜리 제목(오늘을 한 문장씩, 마침표 없이)
- 빈 줄 뒤 오늘 시장을 숫자로 요약한 1~2문장
- 1️⃣ 2️⃣ … 번호 소제목 3~5개. 소제목 아래는 '• ' 짧은 줄(숫자 중심, 문장 대신 명사형), 결론은 '→ ' 한 줄
- 좋은 숫자·근거를 나열할 땐 한 문장(예: '자금 조달 우려에도 답했습니다.') 바로 아래 '✅ ' 줄을 붙여 씀 (이 묶음은 인용 서식으로 나감), 그 뒤 '→ ' 결론, 국내 증시 칸에는 '• 상승:' '• 하락:' 업종·종목과 '수급' (외국인·기관)
- 이어서 앞으로 볼 것 '✔️ ' 줄 4~6개와 한두 문장 정리
- 마지막 번호 소제목 '오늘의 시장 한줄 평' + 한 줄 평 + 한 문장 대응 방향
- {flow}
- 이모지는 예시에 나온 것만. 단락 사이는 빈 줄 한 줄. 전체 길이는 예시와 비슷하게(원문보다 길게 쓰지 않음).

반드시 지킬 것:
- 원문 문장을 그대로 옮기지 않습니다. 사실·숫자·종목명·일정은 유지하되 문장은 새로 씁니다.
- 원문에 없는 숫자·사실은 쓰지 않습니다. 확실하지 않은 건 빼고 check 에 적습니다.
- 특정 종목 매수·매도 권유, 목표가, 수익 보장 표현 금지. 원문 채널 이름·서명·링크 금지.
- text 는 그대로 복사해 올릴 완성본. check 는 올리기 전에 대표가 확인할 것(지수·숫자·보도 사실) 1~3개, 각 한 문장."""
FLOW = {"마감": "흐름: 오늘 장에서 무슨 일이 → 왜 → 국내 증시·수급 → 내일 볼 것",
        "아침": "흐름: 밤사이 미국장 → 핵심 이슈 → 금리·유가 → '📊 주요 지표'(원문에 있는 지수·달러·유가·VIX·금리·야간선물 숫자를 한 줄씩) → 국내 증시 → 오늘 볼 것"}
IMG = Path.home() / ".content-lab-ai" / "malhee_sihwang.png"   # 시황에 항상 붙이는 '차트보는 말희아빠' 이미지 (PC에만, 저장소엔 안 올림)


def renumber(text):
    """번호 소제목(1️⃣ 2️⃣ …)을 빠짐없이 차례대로 다시 매긴다 (Claude 가 4️⃣를 건너뛴 적 있음, 11/12)."""
    import re
    n = iter(range(1, 11))
    return re.sub(r"^(?:10|[1-9])️⃣", lambda m: f"{next(n)}️⃣", text, flags=re.M)


def to_html(text):
    """✅ 줄 묶음(+바로 위 한 문장)과 ✔️ 볼 것 묶음을 텔레그램 인용 서식으로. 길게 눌러 복사하면 서식째 붙여넣어진다."""
    import html as H
    lines, out, i = text.split("\n"), [], 0
    while i < len(lines):
        j = i
        mark = "✅" if lines[i].startswith("✅") else "✔" if lines[i].startswith("✔") else None
        while mark and j < len(lines) and lines[j].startswith(mark):
            j += 1
        if j > i:   # i..j 가 ✅ 또는 ✔️ 묶음
            lead = []
            if mark == "✅" and out and out[-1].strip() and not out[-1].lstrip().startswith(("•", "→", "✔", "<")) and "️⃣" not in out[-1]:
                lead = [out.pop()]
            out.append("<blockquote>" + "\n".join(lead + [H.escape(x) for x in lines[i:j]]) + "</blockquote>")
            i = j
            continue
        out.append(H.escape(lines[i]))
        i += 1
    return "\n".join(out).replace("</blockquote>\n", "</blockquote>")




def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--redo", action="store_true", help="가장 최근 아침·마감 시황을 지금 형식으로 다시")
    args = ap.parse_args()
    load_env()
    sources = json.loads(SRC.read_text(encoding="utf-8")) if SRC.exists() else []
    done = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else []
    have = {d["source_id"] for d in done}
    since = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    todo = [s for s in sources if s["kind"] in ("아침", "마감") and s["id"] not in have and s["date"] >= since]
    if args.redo:
        todo = [s for s in sources if s["kind"] in ("아침", "마감")][-1:]
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
    from publish import notify
    for s in todo[-2:]:   # 밀린 게 있어도 최근 2개만 (비용)
        dt = datetime.fromisoformat(s["date"]).astimezone(KST)
        date = f"{dt.month}월 {dt.day}일({'월화수목금토일'[dt.weekday()]})"
        prompt = f"[말희아빠 예시]\n{style}\n\n[오늘 원문 — {s['kind']} 시황, {s['time']}]\n{s['text']}"
        try:
            with client.messages.stream(model=MODEL, max_tokens=8000, system=SYSTEM.format(kind=s["kind"], date=date, flow=FLOW[s["kind"]]),
                                        messages=[{"role": "user", "content": prompt}], output_format=Rewrite) as stream:
                r = stream.get_final_message()
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            print(f"⚠️ Claude API 오류: {e}")
            continue
        if r.stop_reason != "end_turn" or r.parsed_output is None:
            print(f"⚠️ 변환 결과를 받지 못했어요({r.stop_reason})")
            continue
        text = renumber(r.parsed_output.text.strip())
        if IMG.exists():   # 1통: 시황 이미지 (게시물에 첨부)
            notify.send_photos([IMG])
        ok = notify.send(to_html(text), html=True) or notify.send(text)   # 2통: 그대로 붙여넣을 본문 (✅ 묶음은 인용 서식)
        notify.send(f"☝️ 말희아빠 {s['kind']}시황 (원문 {s['time']}) — 위 이미지를 첨부하고 글을 길게 눌러 복사해 붙여넣으세요.\n\n올리기 전 확인\n"
                    + "\n".join(f"• {c}" for c in r.parsed_output.check) + f"\n\n원문: {s['link']}", silent=True)
        print("📨 핫코노미 봇 전송", "완료" if ok else "실패")
        done = [d for d in done if d["source_id"] != s["id"]]
        done.append({"source_id": s["id"], "kind": s["kind"], "source_time": s["time"], "source_link": s["link"],
                     "made_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "text": text, "check": r.parsed_output.check})
        print(f"✅ {s['kind']}시황 변환 ({s['time']}, 입력 {r.usage.input_tokens:,} / 출력 {r.usage.output_tokens:,} 토큰)")
    OUT.write_text(json.dumps(done[-KEEP:], ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
