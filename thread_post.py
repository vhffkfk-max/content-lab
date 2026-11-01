"""쓰레드 콘텐츠 만들기 — '지금 쓸 거리'(hot_now.json) 하나를 황소개미(@bullant_economy) 쓰레드에 바로 올릴 글로 쓴다.

    python thread_post.py --idx 0 --styles ABC            # 최신 '지금 쓸 거리' 1번으로 A·B·C 세 개
    python thread_post.py --idx 2 --styles B --slot "11/01 17:10" --rid abc123   # 사이트 버튼 (local_ai.py 가 부름)
    python thread_post.py --idx 0 --styles A --dry-run    # Claude 에게 넘길 글만 보기

- 말투·형식: config/threads_abc.md (Claude.ai 에서 쓰는 지침으로 바꿔 넣으면 그대로 따름) + 황소개미 최근 글(thm_posts.json)
- 마케팅 코치 원칙: 글마다 '황소개미 해석 한 줄', AI 티(반전 문구 '~가 아니라 ~다', 번호·기호 나열) 금지 — 걸리면 한 번 다시 쓰게 함
- 글 쓰기: Claude Sonnet — 내 PC Claude Code(Max 구독, llm.py)라 API 요금 없음
→ output/site/thread_posts.json (최근 60개). 사이트 '지금 쓸 거리' 카드 밑에 뜨고, 활용 체크(usage_audit.py)가 실제 올린 글과 맞춰 봄.
"""
import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import List

from pydantic import BaseModel

import llm as anthropic
from common import OUTPUT_DIR, ROOT

KST = timezone(timedelta(hours=9))
SITE = OUTPUT_DIR / "site"
OUT = SITE / "thread_posts.json"
GUIDE = ROOT / "config" / "threads_abc.md"
MODEL = "claude-sonnet-5-5"
KEEP = 60

# AI 티 — 마케팅 코치(growth_plan)·황소개미 진단(thm_ai)에서 걸린 것들
TELLS = [
    (re.compile(r"(?:이|가|은|는)?\s*아니라[,\s]|라기보다"), "반전 문구 '~가 아니라·~라기보다 ~다'"),
    (re.compile(r"기사\s*\d+\s*건|\d+건의 기사|\d{1,2}:\d{2}에?\s*(?:보도|기사)"), "기사 건수·보도 시각"),
    (re.compile(r"^\s*\d+\s*[.)]\s", re.M), "번호 목록"),
    (re.compile(r"^\s*[-•·▪︎✔️✅]\s", re.M), "기호 목록"),
    (re.compile(r"결론적으로|따라서|또한[,\s]"), "'결론적으로·따라서·또한'"),
    (re.compile(r"늦지\s*말고|꼭\s*보세요"), "재촉 문구"),
    (re.compile(r"#\S"), "해시태그"),
]


class Post(BaseModel):
    style: str          # A / B / C
    text: str           # 쓰레드에 그대로 붙일 글 ('ㅤ' 빈 줄 포함)
    take: str           # 글 속 황소개미 해석 한 줄 (그대로 옮김)
    check: List[str]    # 올리기 전 확인할 숫자·사실 (없으면 빈 목록)


class Result(BaseModel):
    posts: List[Post]


def styles_from_guide(guide):
    """'## A · 이름' 줄 → {'A': '이름'}."""
    return {m[1]: m[2].strip() for m in re.finditer(r"^##\s*([ABC])\s*[·:\-]\s*(.+)$", guide, re.M)}


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def find_pick(idx, slot):
    hist = load(SITE / "hot_now.json", [])
    run = next((h for h in hist if h.get("time") == slot), None) if slot else None
    run = run or (hist[0] if hist else None)
    if not run or idx >= len(run.get("picks", [])):
        return None, None
    return run, run["picks"][idx]


def examples(n=6):
    """황소개미 최근 글 — 반응(좋아요·조회) 좋은 순 절반 + 최신 순 절반."""
    posts = [p for p in load(SITE / "thm_posts.json", []) if (p.get("text") or "").strip()]
    best = sorted(posts, key=lambda p: -((p.get("likes") or 0) * 50 + (p.get("views") or 0)))[: n // 2]
    out = best + [p for p in posts if p not in best][: n - len(best)]
    return [f"--- ({p.get('time', '')} · 좋아요 {p.get('likes') or 0}{' · 조회 ' + str(p['views']) if p.get('views') else ''})\n{p['text'].strip()}" for p in out]


def tells(text):
    return [name for rx, name in TELLS if rx.search(text)]


def write(pick, styles, names, guide):
    G = load(SITE / "growth_plan.json", {})
    G = G[0] if isinstance(G, list) and G else G
    system = "\n".join([
        "너는 경제 쓰레드 계정 황소개미(@bullant_economy)의 글을 대신 쓴다. 결과는 사용자가 고치지 않고 그대로 붙여 넣는다.",
        "아래 지침과 이 계정의 실제 글 말투를 따른다. 자료에 없는 숫자·사실은 지어내지 않는다.",
        "check 에는 올리기 전 원문에서 확인할 숫자·사실만 짧게 적는다 (최대 3개, 각 30자 안팎, 지침 얘기는 쓰지 않음).",
        "글마다 '황소개미 해석 한 줄'(1인칭 입장)을 꼭 넣고 take 에 그대로 옮긴다.", "", guide])
    prompt = "\n".join([
        "## 이 계정 포지셔닝 (마케팅 코치)", (G or {}).get("positioning", "") or "-", "",
        "## 황소개미 최근 글 (말투·줄 길이·'ㅤ' 쓰는 법만 참고. 번호 목록·반전 문구는 따라 하지 말 것)", *examples(), "",
        "## 쓸 거리", f"주제: {pick.get('topic', '')}", f"제목: {pick.get('title', '')}", f"왜 지금: {pick.get('why_now', '')}",
        f"편집장 초안({pick.get('channel', '')}용):\n{pick.get('draft', '')}", f"근거 링크: {' '.join(pick.get('sources') or []) or '없음'}", "",
        f"위 쓸 거리로 {', '.join(f'{s}({names.get(s, s)})' for s in styles)} 글을 하나씩 써 줘. style 에는 A·B·C 글자만."])
    msgs = [{"role": "user", "content": prompt}]
    client = anthropic.Anthropic()
    for attempt in range(2):
        r = client.messages.parse(model=MODEL, max_tokens=6000, system=system, output_config={"effort": "low"},
                                  messages=msgs, output_format=Result)
        if r.parsed_output is None:
            return None
        posts = {p.style.strip()[:1].upper(): p for p in r.parsed_output.posts}
        bad = {s: tells(p.text) for s, p in posts.items() if tells(p.text)}
        if attempt or not bad:
            return posts
        msgs = [{"role": "user", "content": prompt}, {"role": "assistant", "content": json.dumps(r.parsed_output.model_dump(), ensure_ascii=False)},
                {"role": "user", "content": "AI 티가 남았어요. 다음 글을 고쳐서 전체를 다시 주세요: "
                 + "; ".join(f"{s}: {', '.join(v)}" for s, v in bad.items()) + ". 나머지 글은 그대로."}]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--idx", type=int, default=0)
    ap.add_argument("--styles", default="ABC")
    ap.add_argument("--slot", default="")
    ap.add_argument("--rid", default="")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    run, pick = find_pick(a.idx, a.slot)
    if not pick:
        return print(f"⚠️ '지금 쓸 거리' {a.idx + 1}번을 못 찾았어요")
    guide = GUIDE.read_text(encoding="utf-8")
    names = styles_from_guide(guide)
    styles = [s for s in dict.fromkeys(a.styles.upper()) if s in "ABC"] or ["A"]
    if a.dry_run:
        return print(f"{pick['title']} → {styles} · 예시 글 {len(examples())}개 · 지침 {len(guide)}자")
    if not anthropic.ready():
        return print("⚠️ Claude Code 가 없어요 — 건너뜀")
    posts = write(pick, styles, names, guide)
    if not posts:
        return print("⚠️ 결과를 못 받았어요 — 다시 눌러 주세요")
    now = datetime.now(KST)
    new = [{"rid": a.rid, "at": now.isoformat(timespec="seconds"), "time": now.strftime("%m/%d %H:%M"), "slot": run["time"],
            "idx": a.idx, "pick": pick["title"], "style": s, "label": names.get(s, s), "text": p.text.strip(), "take": p.take,
            "check": p.check, "tells": tells(p.text)} for s in styles if (p := posts.get(s))]
    OUT.write_text(json.dumps(new + load(OUT, [])[: KEEP - len(new)], ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ 쓰레드 글 {len(new)}개 ({''.join(x['style'] for x in new)}) · {pick['title'][:30]}"
          + "".join(f" · {x['style']} AI 티 남음: {', '.join(x['tells'])}" for x in new if x["tells"]))


if __name__ == "__main__":
    main()
