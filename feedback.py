"""사이트 '후기·기록'에서 남긴 피드백(data/feedback.json)을 Claude 프롬프트용 글로 정리한다.

    from feedback import feedback_prompt
    prompt += feedback_prompt(["쓰레드", "해외 쓰레드"])   # 그 종류 후기만 (없으면 전체)
"""
import json

from common import DATA_DIR

PATH = DATA_DIR / "feedback.json"


def load():
    if not PATH.exists():
        return {"items": {}, "contents": []}
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"items": {}, "contents": []}


def feedback_prompt(types=None, limit=12):
    d = load()
    items = sorted(d.get("items", {}).values(), key=lambda i: i.get("at", ""), reverse=True)
    if types:
        items = [i for i in items if i.get("type") in types] or items
    good = [i for i in items if i.get("verdict") == "helpful"][:limit]
    bad = [i for i in items if i.get("verdict") == "not_helpful"][:limit]
    notes = [i for i in items if i.get("note") and not i.get("verdict")][:limit]
    made = d.get("contents", [])[:limit]
    if not (good or bad or notes or made):
        return ""
    line = lambda i: f"- [{i.get('type', '')}] {(i.get('title') or '')[:80]}" + (f" — 메모: {i['note'][:120]}" if i.get("note") else "")
    out = ["\n\n대표가 사이트에서 남긴 피드백 (이걸 꼭 반영하세요: 도움 된 것과 비슷한 소재·형식은 더, 도움 안 된 것과 비슷한 건 덜 추천):"]
    if good:
        out += ["[도움 됨]"] + [line(i) for i in good]
    if bad:
        out += ["[도움 안 됨]"] + [line(i) for i in bad]
    if notes:
        out += ["[메모]"] + [line(i) for i in notes]
    if made:
        out += ["[대표가 실제로 만든 콘텐츠와 후기]"] + [
            f"- {c.get('channel', '')}: {c.get('title', '')[:60]}" + (f" (참고: {c['based_on_title'][:50]})" if c.get("based_on_title") else "")
            + (f" — 후기: {c['note'][:120]}" if c.get("note") else "") for c in made]
    return "\n".join(out)
