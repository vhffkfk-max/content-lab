"""뜬 글 공식(output/site/viral.json)을 제작기 프롬프트에 넣을 글로 바꾼다.

    from viral_rules import prompt_notes
    prompt_notes("카드뉴스")   # publish/draft_card.py
    prompt_notes("릴스")       # reels/make_reel.py

viral_daily.py 가 매일 아침 viral.json 을 새로 만들고 저장소에 올린다 → 이 파일만 있으면 어느 폴더(PC 개발 폴더·content-lab-ai)에서도 같은 공식을 쓴다.
핫코노미에 '안 맞음'인 공식은 넣지 않는다. 오래된 결과(STALE_DAYS 지남)거나 파일이 없으면 빈 글자 → 제작기는 예전처럼 동작.
공식은 시험할 가설이라 사실 규칙보다 아래에 둔다. 어떤 공식을 썼는지 design_note 에 이름을 남기게 해서 나중에 성적과 맞춰 본다.
"""
import json
from datetime import datetime, timedelta, timezone

from common import OUTPUT_DIR

FILE = OUTPUT_DIR / "site" / "viral.json"
STALE_DAYS = 10
MAX_RULES = 6
KST = timezone(timedelta(hours=9))


def load():
    try:
        d = json.loads(FILE.read_text(encoding="utf-8"))
        made = datetime.fromisoformat(d["made_at"])
    except (OSError, ValueError, KeyError):
        return None
    if datetime.now(KST) - made > timedelta(days=STALE_DAYS):
        return None
    return d


def rules(kind):
    """kind('카드뉴스'·'릴스')에 쓸 공식. 잘 맞음 먼저, 근거 많은 순."""
    d = load()
    if not d:
        return []
    picked = [f for f in d.get("formulas", []) if f.get("fit") in ("잘 맞음", "조건부") and f.get("kind") in (kind, "공통")]
    picked.sort(key=lambda f: (f["fit"] != "잘 맞음", -(len(f.get("evidence", [])) - len(f.get("counter", [])))))
    return picked[:MAX_RULES]


def prompt_notes(kind, record=True):
    """record=False 면 design_note 에 공식 이름 남기라는 줄을 뺀다 (그 칸이 없는 릴스 대본용)."""
    rs = rules(kind)
    if not rs:
        return ""
    lines = [f"[뜬 글 공식] (경제 계정들의 뜬 글과 평범한 글을 비교해 매일 갱신. 원인이 증명된 것이 아닌 가설이므로 위 사실 규칙이 항상 우선)",
             "- 이 소재에 실제로 맞는 공식만 골라 쓰고, 안 맞으면 쓰지 않습니다. 공식을 맞추려고 사실, 숫자, 발언, 반전을 지어내지 않습니다.",
             *(["- design_note 끝에 '공식: 이름' 으로 쓴 공식 이름을 적습니다(안 썼으면 '공식: 없음')."] if record else [])]
    for f in rs:
        tag = "" if f["fit"] == "잘 맞음" else " (조건부: " + f.get("fit_why", "")[:80] + ")"
        lines.append(f"- {f['name']}{tag}: {f['what']} 쓰는 법: {f['how']} (근거 {len(f.get('evidence', []))}개, 예외 {len(f.get('counter', []))}개)")
    return "\n".join(lines)


def used_formula(note):
    """design_note 에서 '공식: 이름' 을 꺼낸다 (성적 맞춰 보기용)."""
    if not note or "공식:" not in note:
        return ""
    name = note.rsplit("공식:", 1)[1].strip().strip(".'\" ")
    return "" if name in ("없음", "") else name[:40]


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    for k in ("카드뉴스", "릴스"):
        print(f"== {k}\n{prompt_notes(k) or '(없음)'}\n")
