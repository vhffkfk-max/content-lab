"""트레이더가 쓴 차트 분석을 차트덕후 쓰레드 글(본문+답글 3개)로 바꾼다. 내 PC(local_ai.py)가 Max 구독으로 처리.
    python chart_trader.py --rid <ai_requests.json 의 id>
결과: output/site/trader_posts.json (최근 20건). 사진은 저장소에 올리지 않고 입력한 브라우저에만 둔다.
원문에 없는 숫자는 check 칸에 적어 화면에서 사람이 보게 한다."""
import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import llm as anthropic

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output" / "site" / "trader_posts.json"
REQ = ROOT / "data" / "ai_requests.json"
MODEL = "claude-opus-5-5"
LIMIT = 500
SYSTEM = """너는 차트덕후 쓰레드 계정의 편집자다. 회사 트레이더가 쓴 차트 분석을 쓰레드 글로 옮긴다.
판단과 가격, 사례는 트레이더 원문만 쓴다. 새 분석이나 새 숫자, 기사 내용을 만들지 않는다.

구성은 4칸이다.
- 본문: 첫 줄은 사건이나 핵심 비교로 시작하는 훅. 어려운 차트 용어로 시작하지 않는다.
- 답글 1: 이유. 번호로 정리. 과거 사례가 있으면 여기서 비교.
- 답글 2: "다만"으로 시작. 저항, 회복 조건 등 판단의 한계.
- 답글 3: "제가 보는 시나리오입니다."로 시작. 시나리오 A(원문에서 더 무게를 둔 쪽)와 시나리오 B를 각각 경로와 이유로 쓰고, A와 B를 가르는 가격을 적는다. 맨 끝 줄은 정확히 "경로와 시간은 예시이고 매매 추천 아닙니다."

규칙
- 각 칸은 500자 이내. 짧은 줄로 끊고 이모지와 구분선은 쓰지 않는다.
- 중학생도 읽을 수 있는 쉬운 말과 객관적인 존댓말.
- 판단은 "저는 ~로 봅니다"로 쓴다. "권합니다", "사세요", "파세요", "오른다", "간다" 같은 권유·단정은 쓰지 않는다.
- 표본이 적은 경향은 "이번엔 더 약합니다"처럼 그 사례 비교로만 쓴다.
- 확률 숫자는 원문에 있을 때만 쓴다. 만들지 않는다.
- 매매 경험을 지어내지 않는다.

사진은 입력된 순서대로 1번부터 번호가 있다. 각 칸에 어울리는 사진 번호를 image에 적고, 없으면 0으로 한다.

JSON만 출력한다. 형식: {"title":"짧은 제목","posts":[{"label":"본문","text":"...","image":3},{"label":"답글 1","text":"...","image":1},{"label":"답글 2","text":"...","image":0},{"label":"답글 3","text":"...","image":0}]}"""


def numbers(text):
    return {n.replace(",", "").rstrip(".") for n in re.findall(r"\d[\d,.]*\d|\d", text)}


def review(source, posts):
    src = numbers(source)
    notes = []
    for p in posts:
        extra = sorted(n for n in numbers(p["text"]) if n not in src and len(n.replace(".", "")) >= 2)
        if extra:
            notes.append(f"{p['label']}: 원문에 그대로 없는 숫자 {', '.join(extra)}")
        if len(p["text"]) > LIMIT:
            notes.append(f"{p['label']}: {len(p['text'])}자, 쓰레드 한도 {LIMIT}자 초과")
        if re.search(r"권합니다|추천합니다|사세요|파세요", p["text"].replace("매매 추천 아닙니다", "")):
            notes.append(f"{p['label']}: 권유로 읽힐 수 있는 표현")
    return notes


def convert(text, photos):
    msg = f"사진 수: {photos}장\n\n트레이더 원문:\n{text}"
    r = anthropic.Anthropic().messages.create(model=MODEL, max_tokens=4000, system=SYSTEM, output_config={"effort": "medium"}, messages=[{"role": "user", "content": msg}])
    raw = r.content[0].text.strip()
    data = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    posts = data["posts"]
    if [p["label"] for p in posts] != ["본문", "답글 1", "답글 2", "답글 3"]:
        raise ValueError("글 칸이 양식과 다릅니다")
    for p in posts:
        p["image"] = p["image"] if isinstance(p.get("image"), int) and 0 <= p["image"] <= photos else 0
    return data["title"], posts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rid", required=True)
    rid = ap.parse_args().rid
    req = next((r for r in json.loads(REQ.read_text(encoding="utf-8")) if r["id"] == rid), None)
    if not req:
        raise SystemExit("요청을 찾지 못했습니다")
    a = req["args"]
    text, photos, client = a.get("text", ""), int(a.get("photos") or 0), a.get("rid", rid)
    rows = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else []
    item = dict(rid=client, at=datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="minutes"), photos=photos)
    try:
        title, posts = convert(text, photos)
        item.update(status="done", title=title, posts=posts, check=review(text, posts))
    except Exception as e:
        item.update(status="error", error=f"{type(e).__name__}: {e}"[:200])
    rows = [item] + [x for x in rows if x.get("rid") != client]
    OUT.write_text(json.dumps(rows[:20], ensure_ascii=False, indent=1), encoding="utf-8")
    print(item["status"], item.get("title", item.get("error", "")))


if __name__ == "__main__":
    main()
