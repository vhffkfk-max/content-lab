"""카드뉴스 텍스트 추천안: 1시간마다 주제 3개 + 표지 문구 3개씩 + 표지 시안(폼 × 글꼴) 그림.

    python -m publish.card_ideas              # 만들어서 큐에 넣고, 시안을 card-previews 가지로 올리고, 텔레그램으로 알림
    python -m publish.card_ideas --no-send    # 알림·올리기 없이 (시험용)

흐름: 추천안(여기) → 사이트에서 주제·표지 문구·시안 선택 → draft_card --pick 이 고른 것만 완성한다.
- 완성 카드를 매번 만들면 Max 사용량을 많이 써서, 여기서는 글 한 번(주제 3개)만 쓰고 시안은 코드가 그린다.
- 추천안은 data/publish_queue.json 의 ideas 칸. 사이트가 이미 읽는 파일이라 중간 서버를 고치지 않아도 된다.
"""
import argparse
import json
import pathlib
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone

from common import OUTPUT_DIR, load_env
import viral_rules
from publish import card_preview, draft_card as dc, forms, notify

KST = timezone(timedelta(hours=9))
KEEP_IDEAS = 45
SITE = OUTPUT_DIR / "site"
PREVIEW_W = 360
PREVIEW_Q = 68
MODEL = "claude-sonnet-5-5"   # 1시간마다 도는 추천안은 가볍게, 완성 글은 draft_card 의 모델로

SYSTEM = """당신은 한국 경제 인스타그램 @hotconomy(핫코노미)의 편집자입니다. 주어진 재료에서 오늘 카드뉴스로 만들 만한 주제를 고릅니다.
규칙:
- 숫자와 사실은 재료에 있는 것만 씁니다. 없는 수치, 전망, 발언을 지어내지 않습니다. 뉴스 내용은 보도로 다룹니다.
- 특정 종목 매수, 매도를 권하지 않습니다. 수익 보장, '무조건', '지금 사야' 같은 표현을 쓰지 않습니다.
- 이미 다룬 주제와 겹치면 고르지 않습니다. 서로 다른 사건 3개를 고릅니다.
- 표지 문구는 주제 요약이 아니라 사건입니다. 누가, 얼마나, 무슨 반전인지 구체적으로 씁니다. 2~3줄, 줄당 7~13자, 줄바꿈은 \\n, 강조는 핵심 단어 한 곳만 **이렇게**.
- 표지 문구 3개는 서로 다른 각도로 씁니다: 숫자형, 질문형, 반전형. 재료에 숫자가 없으면 숫자형 대신 사건형으로 씁니다.
- 가운뎃점(·) 대신 쉼표를 씁니다. 과한 이모지와 AI 티 나는 표현을 쓰지 않습니다.

출력: 설명 없이 JSON 하나만.
{"ideas": [{"title": "주제(관리용, 30자 안쪽)", "concept": "어떤 각도로 풀지 한 줄", "why_now": "왜 지금인지 한두 문장", "tag": "짧은 분류",
 "sources": ["재료에 있는 링크"], "bg": "표지 사진 영어 검색어 2~4단어, 핵심 인물 이름이나 고유한 제품, 건물", "bg_alt": "인물 사진이 없을 때 쓸 제품, 건물 검색어",
 "hooks": [{"type": "숫자형", "title": "표지 문구", "number": "표지에 크게 쓸 숫자 하나(예: 44조원, -5.2%). 재료에 없으면 빈칸", "label": "숫자 위 짧은 설명", "sub": "숫자 아래 한 줄"}],
 "forms": ["이 소재를 가장 잘 살리는 폼 2개"], "extra": {"폼 키": {"그 폼 표지에 더 필요한 칸"}}}]}

고를 수 있는 폼과 extra:
- breaking 속보형: 빠른 사건. extra 없음.
- news 사진 뉴스형: 인물, 기업, 이슈. extra 없음.
- editorial 에디토리얼: 일상, 소비, 트렌드처럼 내 얘기인 소재. extra 없음.
- bignum 숫자 한 방형: 숫자 하나가 사건일 때. hooks 의 number 를 채웁니다.
- list 순위 목록형: 사실 여러 개. extra {"list": {"sub": "한 줄", "count": 항목 수}}
- bars 막대 비교형: 수치 비교. extra {"bars": {"sub": "기준 설명", "bars": [{"label": "이름", "value": 숫자, "hi": 강조면 true}]}} 재료에 있는 숫자로만, 2~4개.
- paper 신문 1면형: 사실 3개를 한 번에. extra {"paper": {"date": "11/05", "headlines": ["사실 3개, 한 줄 20자 안쪽"]}}
- quote 다크 인사이트형: 재료에 그대로 나온 실제 발언이 사건일 때만. extra {"quote": {"label": "짧은 분류", "quote": "발언 그대로", "by": "말한 사람"}}"""


def material(queue):
    """지금 발행할 거리 + 인기 뉴스 + 시세 → 프롬프트 재료. 없으면 빈 문자열."""
    done = {i.get("title") for i in queue.get("ideas", [])[-KEEP_IDEAS:]} | {i.get("hot_title") for i in queue["items"][-30:]} | {i.get("title") for i in queue["items"][-30:]}
    picks = []
    try:
        for run in json.loads((SITE / "hot_now.json").read_text(encoding="utf-8"))[:6]:
            picks += [p for p in run.get("picks", []) if p.get("title") not in done]
    except (OSError, ValueError):
        pass
    seen, hot = set(), []
    for p in picks:
        if p.get("title") not in seen:
            seen.add(p.get("title"))
            hot.append(p)
    hot.sort(key=lambda p: 0 if "인스타" in p.get("channel", "") else 1)
    hot_txt = "\n\n".join(f"- 제목: {p['title']}\n  왜 지금: {p.get('why_now', '')}\n  내용: {p.get('draft', '')[:400]}\n  근거: {', '.join(p.get('sources', [])[:3])}" for p in hot[:8])
    news = dc.headlines("", 25)
    news_txt = "\n".join(f"- [{r.get('source', '')} {r.get('published', '')}] {r['title']} ({r.get('link', '')})" for r in news)
    if not hot_txt and not news_txt:
        return ""
    mk = dc.market()
    mk_txt = "\n".join(f"- {v['name']}: {v['date']} {v['close']:,} / 전일 {v['d1']:+}% / 1달 {v['m1']:+}%" for v in mk.values())
    used = "\n".join(f"- {t}" for t in list(filter(None, done))[-40:]) or "- (없음)"
    return (f"오늘: {datetime.now(KST):%Y-%m-%d (%a) %H시}\n\n[지금 발행할 거리]\n{hot_txt or '- (없음)'}\n\n[뉴스]\n{news_txt or '- (없음)'}\n\n[시세]\n{mk_txt or '- (없음)'}\n\n[이미 다룬 주제]\n{used}\n")


def _str(v):
    return str(v or "").strip()


def clean_idea(raw):
    """AI 답 정리. 쓸 수 없는 폼·문구는 빼고, 표지 문구가 없으면 None."""
    hooks = []
    for h in (raw.get("hooks") or [])[:3]:
        if isinstance(h, dict) and _str(h.get("title")):
            hooks.append({"type": _str(h.get("type")) or "사건형", "title": _str(h["title"]), "number": _str(h.get("number")), "label": _str(h.get("label")), "sub": _str(h.get("sub"))})
    if not hooks or not _str(raw.get("title")):
        return None
    extra = raw.get("extra") if isinstance(raw.get("extra"), dict) else {}
    wanted = [f for f in (raw.get("forms") or []) if f in forms.FORM_FONTS][:2]
    for f in ("breaking", "news"):   # 사진이 없거나 폼이 하나뿐이어도 시안이 남게
        if len(wanted) < 2 and f not in wanted:
            wanted.append(f)
    return {"title": _str(raw["title"]), "concept": _str(raw.get("concept")), "why_now": _str(raw.get("why_now")), "tag": _str(raw.get("tag")),
            "sources": [s for s in (raw.get("sources") or []) if isinstance(s, str) and s.startswith("http")][:3],
            "bg": _str(raw.get("bg")), "bg_alt": _str(raw.get("bg_alt")), "hooks": hooks, "forms": wanted,
            "extra": {k: v for k, v in extra.items() if k in wanted and isinstance(v, dict)}}


def cover_for(idea, hook, form):
    """고른 표지 문구 + 폼 → 그 폼의 표지 칸. 이 폼으로 표지를 만들 수 없으면 None."""
    extra = idea.get("extra", {}).get(form, {})
    title = hook["title"]
    if form == "breaking":
        return {"title": title}
    if form == "news":
        return {"tag": idea.get("tag", ""), "title": title, "bg": idea.get("bg", ""), "bg_alt": idea.get("bg_alt", "")}
    if form == "editorial":
        return {"kicker": "HOTCONOMY", "title": title, "caption": hook.get("sub", ""), "bg": idea.get("bg", ""), "bg_alt": idea.get("bg_alt", "")}
    if form == "bignum":
        return {"label": hook.get("label", ""), "number": hook["number"], "sub": hook.get("sub") or re.sub(r"\s*\n\s*", " ", title)} if hook.get("number") else None
    if form == "list":
        return {"title": title, "sub": _str(extra.get("sub")), "count": extra.get("count", "")} if extra.get("count") else None
    if form == "bars":
        bars = [b for b in (extra.get("bars") or []) if isinstance(b, dict) and isinstance(b.get("value"), (int, float))]
        return {"title": title, "sub": _str(extra.get("sub")), "bars": bars} if len(bars) >= 2 else None
    if form == "paper":
        heads = [h for h in (extra.get("headlines") or []) if _str(h)]
        return {"date": _str(extra.get("date")), "headlines": heads} if len(heads) >= 2 else None
    if form == "quote":
        return {"label": _str(extra.get("label")), "quote": _str(extra.get("quote")), "by": _str(extra.get("by"))} if _str(extra.get("quote")) else None
    return None


def cover_photo(idea, cache):
    """사진 폼 표지 사진 (주제 하나에 한 번만 찾음)."""
    key = idea.get("bg", "")
    if key not in cache:
        from publish.photos import find
        got = None
        for q in filter(None, (idea.get("bg"), idea.get("bg_alt"))):
            try:
                got = find(q, about=idea.get("title", ""))
            except Exception as e:
                print("⚠️ 사진 찾기 실패:", q, e)
            if got:
                break
        cache[key] = got
    return cache[key]


def render_previews(idea, out):
    """주제 하나 → {올릴 경로: 그림 bytes}, 시안 목록. 그리다 실패한 조합은 뺀다."""
    from PIL import Image
    from publish.render import render
    photos, blobs, previews = {}, {}, []
    for h, hook in enumerate(idea["hooks"]):
        # 고른 폼으로 못 그리면(숫자 없음, 사진 없음) 표지 문구만으로 되는 속보형으로. 어떤 문구든 시안이 하나는 있게.
        for form in [*idea["forms"], "breaking"]:
            if form == "breaking" and any(p["h"] == h for p in previews):
                continue
            cover = cover_for(idea, hook, form)
            if cover is None:
                continue
            if form in forms.PHOTO_FORMS:
                ph = cover_photo(idea, photos)
                if not ph:
                    continue
                cover["photo"] = ph["uri"]
            for font in forms.FORM_FONTS[form]:
                name = f"{h + 1}-{form}-{font}"
                post = {"form": form, "cover": cover, "slides": [], "end": {}, "font": font}
                try:
                    css, slides = forms._styled(post)
                    f = render(slides[:1], out, name, css)[0]
                    im = Image.open(f)
                    im = im.resize((PREVIEW_W, round(im.height * PREVIEW_W / im.width)), Image.LANCZOS)
                    im.save(f, "JPEG", quality=PREVIEW_Q, optimize=True)
                except Exception as e:
                    print("⚠️ 시안 실패:", name, str(e)[:120])
                    continue
                path = f"{idea['id']}/{name}.jpg"
                blobs[path] = pathlib.Path(f).read_bytes()
                previews.append({"h": h, "form": form, "font": font, "path": path})
    return blobs, previews


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-send", action="store_true", help="알림·올리기 없이")
    a = ap.parse_args()
    load_env()
    queue = dc.load_queue()
    prompt = material(queue)
    if not prompt:
        print("재료가 없어서 건너뜀")
        return 0
    viral = viral_rules.prompt_notes("카드뉴스", record=False)   # 뜬 글 공식: 주제·표지 문구 고를 때 참고 (viral_analyze.py, 매일 갱신)
    if viral:
        prompt += "\n\n" + viral + "\n- 주제와 표지 문구를 고를 때 참고하고, concept 끝에 '(공식: 이름)' 으로 쓴 공식을 적습니다. 안 맞으면 '(공식: 없음)'."
    res = dc.ask_claude(prompt, system=SYSTEM, model=MODEL)
    now = datetime.now(KST)
    ideas, blobs = [], {}
    with tempfile.TemporaryDirectory() as tmp:
        for n, raw in enumerate(res.get("ideas", [])[:3], 1):
            idea = clean_idea(dc.clean(raw))
            if not idea:
                continue
            idea.update(id=f"{now:%Y%m%d-%H%M}-i{n}", created_at=now.isoformat(timespec="seconds"))
            got, idea["previews"] = render_previews(idea, pathlib.Path(tmp) / idea["id"])
            blobs.update(got)
            ideas.append(idea)
            print(f"✅ 추천안 {idea['id']}: {idea['title']} / 시안 {len(idea['previews'])}개")
    if not ideas:
        print("⚠️ 쓸 수 있는 추천안이 없어요")
        return 1
    queue = dc.load_queue()   # 그리는 사이 바뀌었을 수 있어 다시 읽음
    queue["ideas"] = (queue.get("ideas", []) + ideas)[-KEEP_IDEAS:]
    dc.QUEUE.write_text(json.dumps(queue, ensure_ascii=False, indent=1), encoding="utf-8")
    if not a.no_send:
        print("시안:", card_preview.push({}, blobs))
        lines = "\n\n".join(f"{i + 1}. {x['title']}\n{x['why_now']}" for i, x in enumerate(ideas))
        notify.send(f"💡 카드뉴스 추천안 {now:%H}시\n\n{lines}\n\n연구소 '카드뉴스 검수'에서 골라 주세요.", silent=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
