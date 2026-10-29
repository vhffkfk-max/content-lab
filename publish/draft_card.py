"""추천 주제 하나 → 실제 뉴스·시세로 카드뉴스 초안(이미지 + 캡션)을 만든다 (작업지시서 Phase 4).

    python -m publish.draft_card                    # 추천 1위(오늘 이미 만든 주제는 건너뜀)
    python -m publish.draft_card --topic 테슬라      # 주제 지정
    python -m publish.draft_card --dry-run          # Claude 호출 없이 프롬프트만 출력
    python -m publish.draft_card --no-send          # 텔레그램으로 안 보냄
    python -m publish.draft_card --no-canva         # 캔바 사본 안 만듦

숫자 원칙: 시세 숫자는 코드가 야후 차트에서 가져와 넣고, 사실은 모아 둔 뉴스 제목에 있는 것만 쓴다.
  Claude 는 폼을 고르고 글만 쓴다. 차트 자리는 {"ticker": "TSLA"} 로 남기면 코드가 실제 시세로 채운다.
폼 돌려쓰기: 큐(data/publish_queue.json)에서 최근 3개 게시물에 쓴 폼은 후보에서 뺀다.
결과: output/cardnews/drafts/<id>/ 에 JPG, 큐에 status=drafted 로 저장, 텔레그램 봇으로 앨범 + 캡션.
  + 캔바 '핫코노미 · 발행 대기' 폴더에 고칠 수 있는 사본(publish/canva_copy.py), 편집 링크는 큐 canva.edit_url·텔레그램으로.
"""
import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

from common import OUTPUT_DIR, ROOT, load_env
from generate_drafts import NOT_MINE, risky_phrases
from publish import forms, notify

MODEL = "claude-opus-5-5"
KST = timezone(timedelta(hours=9))
SITE = OUTPUT_DIR / "site"
QUEUE = ROOT / "data" / "publish_queue.json"
OUT = OUTPUT_DIR / "cardnews" / "drafts"
BRAND_TAG = "#핫코노미"
MAX_SLIDES = 10

# 초안에 쓸 수 있는 시세 (야후 차트, 키 필요 없음)
TICKERS = {"^KS11": "코스피", "^KQ11": "코스닥", "005930.KS": "삼성전자", "000660.KS": "SK하이닉스", "KRW=X": "원/달러 환율",
           "^GSPC": "S&P500", "^IXIC": "나스닥", "NVDA": "엔비디아", "TSLA": "테슬라", "AAPL": "애플", "MSFT": "마이크로소프트",
           "^TNX": "미국 10년물 금리", "BTC-USD": "비트코인", "GC=F": "금 선물"}


# ── 재료 모으기 ──
def market():
    """{ticker: {name, date, close, d1, d5, m1, ohlc[(o,h,l,c)]}} — 못 가져온 건 뺀다."""
    out = {}
    for t, name in TICKERS.items():
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(t)}?range=2mo&interval=1d"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            r = json.load(urllib.request.urlopen(req, timeout=20))["chart"]["result"][0]
        except Exception as e:
            print("⚠️ 시세 못 가져옴:", t, e)
            continue
        q = r["indicators"]["quote"][0]
        rows = [(o, h, l, c, ts) for o, h, l, c, ts in zip(q["open"], q["high"], q["low"], q["close"], r["timestamp"])
                if None not in (o, h, l, c)]
        if len(rows) < 22:
            continue
        cl = [x[3] for x in rows]
        pct = lambda k: round((cl[-1] / cl[-1 - k] - 1) * 100, 2)
        out[t] = {"name": name, "date": datetime.fromtimestamp(rows[-1][4], KST).strftime("%m/%d"), "close": round(cl[-1], 2),
                  "d1": pct(1), "d5": pct(5), "m1": pct(21), "ohlc": [x[:4] for x in rows[-40:]]}
    return out


def headlines(topic, n=25):
    rows = []
    for f in ("press_headlines.json", "google_headlines.json"):
        p = SITE / f
        if p.exists():
            rows += json.loads(p.read_text(encoding="utf-8"))
    mine = [r for r in rows if topic in (r.get("topics") or r.get("topic") or "")]
    seen, out = set(), []
    for r in mine + [r for r in rows if r.get("popular")]:
        if r["title"] not in seen:
            seen.add(r["title"])
            out.append(r)
    return out[:n]


def plan_rows(topic):
    p = SITE / "drafts.json"
    rows = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    return [r for r in rows if r["topic"] == topic]


def load_queue():
    return json.loads(QUEUE.read_text(encoding="utf-8")) if QUEUE.exists() else {"items": []}


def pick_topic(queue, wanted=None):
    if wanted:
        return wanted
    recs = json.loads((SITE / "recs.json").read_text(encoding="utf-8"))
    today = datetime.now(KST).strftime("%Y-%m-%d")
    done = {i.get("topic") for i in queue["items"] if i.get("created_at", "").startswith(today)}
    for r in sorted(recs, key=lambda r: r["rank"]):
        if r["topic"] not in done:
            return r["topic"]
    return recs[0]["topic"]


# ── 프롬프트 ──
SYSTEM = """당신은 한국 경제 인스타그램 @hotconomy(핫코노미)의 카드뉴스 에디터입니다.
주어진 재료(뉴스 제목, 시세 숫자, 연구소 기획안)만으로 오늘 올릴 카드뉴스 한 편을 씁니다.

사실 규칙 (가장 중요):
- 숫자와 사실은 [뉴스]와 [시세]에 있는 것만 씁니다. 없는 수치(실적, 목표가, 전망치 등)를 지어내지 않습니다.
- 확인할 수 없는 내용은 숫자 없이 쓰거나 아예 빼고, 빈칸([ ], [확인])을 남기지 않습니다.
- 시세는 기준일을 함께 적습니다(예: '10/27 기준'). 뉴스 내용은 '~라는 보도'처럼 출처가 뉴스임을 드러냅니다.
- 특정 종목을 사라/팔라고 하지 않고, 매수·매도 시점을 단정하지 않습니다. 수익 보장, '무조건', '지금 사야' 같은 표현 금지.

글 규칙:
- 가운뎃점(·) 대신 쉼표를 씁니다. 과한 이모지, '~해보세요!' 남발, 뻔한 마무리 같은 AI 티 나는 표현을 쓰지 않습니다.
- 한 장에 메시지 하나. 제목은 2줄 안쪽, 줄당 10~16자. 줄바꿈은 \\n, 강조할 핵심 단어(숫자, %)만 **이렇게** 감쌉니다(장마다 1곳).
- 1장(표지)은 스크롤을 멈추게 하는 훅, 가운데 장은 핵심 하나씩, 마지막 장(end)은 한 줄 요약 체크 3개와 질문형 제목.
- 표지 + 본문 + 마지막 장을 합쳐 6~8장(최대 10장). slides 는 본문 장만 넣습니다(표지·마지막 장 제외, 4~6개).

폼 규칙:
- [쓸 수 있는 폼] 중 소재에 가장 맞는 것 하나를 고르고, 그 폼의 필드 설명대로 cover/slides 를 채웁니다.
- 차트·이미지 자리(chart, image, line)에는 {"ticker": "시세 코드"} 만 넣습니다. 코드가 실제 시세로 그립니다. 사진 경로는 쓰지 않습니다.
- 막대(bars)는 [시세]의 등락률로만 만듭니다: {"label","value"(숫자),"text"(표시값),"hi"(강조 여부)}.
- end.keyword 는 댓글로 받을 짧은 단어 하나(예: '환율').

캡션 규칙:
- 첫 줄 훅(40자 이내) → 핵심 3줄 → 행동 유도 하나(댓글 키워드) → 빈 줄 → '(정보 제공용이며 투자 권유가 아닙니다)'.
- 해시태그 5~8개: #핫코노미 1개 + 주제 태그 + 대형 태그 1~2개. 다른 계정, 매체, 회사 이름 태그 금지.
- youtube: 쇼츠용 제목(40자 이내)과 설명(2~3줄 + 면책 문구).

출력: 설명 없이 JSON 하나만.
{"form": "폼 키", "kind": "소재 종류", "title": "게시물 제목(관리용)", "cover": {...}, "slides": [{...}], "end": {"title","checks":[3개],"keyword"},
 "caption": "...", "hashtags": ["#..."], "youtube": {"title","description"}, "sources": ["쓴 뉴스 링크"]}"""


def form_specs(allowed):
    lines = []
    for k in allowed:
        fn, _ = forms.FORMS[k]
        kinds = [kd for kd, fs in forms.KINDS.items() if k in fs]
        lines.append(f"- {k} ({forms.FORM_NAMES[k]}) — 어울리는 소재: {', '.join(kinds)}\n  {fn.__doc__.strip()}")
    return "\n".join(lines)


def build_prompt(topic, news, mk, plan, allowed, today):
    news_txt = "\n".join(f"- [{r.get('source', '')} {r.get('published', '')}] {r['title']} ({r.get('link', '')})" for r in news) or "- (없음)"
    md_today = today[5:10].replace("-", "/")
    mk_txt = "\n".join(f"- {t} {v['name']}: {v['date']} {'장중' if v['date'] == md_today else '종가'} {v['close']:,} / 전일 {v['d1']:+}% / 5일 {v['d5']:+}% / 1달 {v['m1']:+}%"
                       for t, v in mk.items())
    plan_txt = "\n".join(f"- {r['label']}: {r['text']}" for r in plan if r["part"] in ("structure", "carousel", "caption"))[:3000] or "- (없음)"
    return (f"오늘: {today}\n주제: {topic}\n\n[뉴스] (최근 수집, 이 안의 사실만 사용)\n{news_txt}\n\n[시세] (코드가 가져온 실제 값)\n{mk_txt}\n\n"
            f"[연구소 기획안] (방향 참고용, [확인] 칸은 위 재료로 채울 수 있을 때만)\n{plan_txt}\n\n[쓸 수 있는 폼] (최근 게시물에 쓴 폼은 빠져 있음)\n{form_specs(allowed)}")


# ── 결과 다듬기 ──
def fill_charts(post, mk):
    """{"ticker": X} 자리를 실제 시세로 바꾸고, 속보형 가격 라벨은 코드 값으로 덮는다."""
    used = set()

    def series(spec):
        t = spec.get("ticker") if isinstance(spec, dict) else None
        return mk.get(t), t

    def walk(d, cover):
        for key in ("chart", "image", "line"):
            if isinstance(d.get(key), str):
                d.pop(key)                       # 사진 경로는 쓰지 않는다 (저작권)
            v, t = series(d.get(key))
            if key in d and isinstance(d[key], dict) and "ticker" in d[key] and not v:
                d.pop(key)                       # 없는 시세는 차트를 빼고 그린다
                continue
            if not v:
                continue
            used.add(t)
            closes = [round(x[3], 2) for x in v["ohlc"]]
            if key == "line":
                d[key] = closes
            elif key == "chart" and cover and post["form"] == "breaking":
                d[key] = {"candles": v["ohlc"]}
                d["price"] = f"{v['d1']:+.2f}%"
            elif key == "image" and d[key].get("type") != "line":
                d[key] = {"candles": v["ohlc"]}
            else:
                d[key] = {"line": closes}

    walk(post["cover"], True)
    for s in post.get("slides", []):
        walk(s, False)
    if post["form"] == "breaking" and "candles" not in post["cover"].get("chart", {}):
        t = next(iter(used), None) or next(iter(mk))
        post["cover"]["chart"], post["cover"]["price"] = {"candles": mk[t]["ohlc"]}, f"{mk[t]['d1']:+.2f}%"
    return sorted(used)


def tidy(s):
    return re.sub(r"\s*·\s*", ", ", s) if isinstance(s, str) else s


def clean(obj):
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean(v) for v in obj]
    return tidy(obj)


def check(post):
    """사람이 볼 경고 목록 (발행 전 위험 점검 Phase 3 전에 최소한만)."""
    text = json.dumps({k: post[k] for k in ("cover", "slides", "end", "caption")}, ensure_ascii=False)
    warns = [f"위험 표현: {', '.join(risky_phrases(text))}"] if risky_phrases(text) else []
    if re.search(r"\[\s*(확인)?\s*\]", text):
        warns.append("빈칸 [ ] 이 남아 있어요")
    if "투자 권유가 아닙니다" not in post["caption"]:
        post["caption"] = post["caption"].rstrip() + "\n\n(정보 제공용이며 투자 권유가 아닙니다)"
    return warns


def hashtags(tags):
    tags = [t if t.startswith("#") else f"#{t}" for t in tags]
    tags = [t for t in tags if not any(b in t.lower() for b in NOT_MINE)]
    if BRAND_TAG not in tags:
        tags.insert(0, BRAND_TAG)
    return list(dict.fromkeys(tags))[:8]


def ask_claude(prompt):
    import llm as anthropic   # 내 PC Claude Code(Max 구독)로 실행 — API 요금 없음
    client = anthropic.Anthropic()
    msgs = [{"role": "user", "content": prompt}]
    for _ in range(2):
        r = client.messages.create(model=MODEL, max_tokens=8000, system=SYSTEM, messages=msgs)
        text = "".join(b.text for b in r.content if b.type == "text")
        print(f"   (입력 {r.usage.input_tokens:,} / 출력 {r.usage.output_tokens:,} 토큰)")
        m = re.search(r"\{.*\}", text, re.S)
        try:
            return json.loads(m.group(0))
        except (AttributeError, json.JSONDecodeError):
            msgs += [{"role": "assistant", "content": text}, {"role": "user", "content": "JSON 형식이 깨졌어요. JSON 하나만 다시 주세요."}]
    raise RuntimeError("Claude 가 JSON 을 주지 않았어요.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-send", action="store_true")
    ap.add_argument("--no-canva", action="store_true", help="캔바 사본 안 만듦")
    a = ap.parse_args()
    load_env()
    queue = load_queue()
    topic = pick_topic(queue, a.topic)
    recent = [i["form"] for i in queue["items"] if i.get("form")][-3:]
    allowed = [k for k in forms.FORMS if k not in recent]
    now = datetime.now(KST)
    print(f"📰 주제: {topic} / 최근 폼 {recent or '없음'} 제외")
    mk, news = market(), headlines(topic)
    prompt = build_prompt(topic, news, mk, plan_rows(topic), allowed, now.strftime("%Y-%m-%d (%a)"))
    if a.dry_run:
        print(SYSTEM, "\n\n", prompt)
        return
    post = clean(ask_claude(prompt))
    if post.get("form") not in allowed:
        post["form"] = forms.pick_form(post.get("kind", ""), recent)
    post["slides"] = post.get("slides", [])[:MAX_SLIDES - 2]
    tickers = fill_charts(post, mk)
    warns = check(post)
    post["hashtags"] = hashtags(post.get("hashtags", []))
    did = f"{now:%Y%m%d-%H%M}-{post['form']}"
    files = forms.make(post, OUT / did, did)
    (OUT / did / "post.json").write_text(json.dumps(post, ensure_ascii=False, indent=1), encoding="utf-8")
    canva = {}
    if not a.no_canva:
        try:   # 캔바 '발행 대기' 폴더에 고칠 수 있는 사본 (실패해도 초안은 그대로 보냄)
            from publish.canva_copy import to_canva
            d = to_canva(forms.make_canva(post, OUT / did / f"{did}.pptx"), f"[초안] {post.get('title', topic)}"[:50])
            canva = {"id": d["id"], "edit_url": d["urls"]["edit_url"]}
            print("✅ 캔바 사본:", canva["edit_url"])
        except Exception as e:
            print("⚠️ 캔바 사본 실패 (초안은 그대로):", e)
    caption = post["caption"].rstrip() + "\n\n" + " ".join(post["hashtags"])
    queue["items"].append({"id": did, "account": "hotconomy", "type": "carousel", "topic": topic, "form": post["form"],
                           "title": post.get("title", topic), "caption": caption, "youtube": post.get("youtube", {}),
                           "files": [str(f.relative_to(ROOT)).replace("\\", "/") for f in files], "tickers": tickers,
                           "sources": post.get("sources", []), "warnings": warns, "status": "drafted", "risk": None,
                           "published": {}, "canva": canva, "created_at": now.isoformat(timespec="seconds")})
    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    QUEUE.write_text(json.dumps(queue, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ {forms.FORM_NAMES[post['form']]} {len(files)}장 → {OUT / did}")
    for w in warns:
        print("⚠️", w)
    if not a.no_send:
        head = f"📝 카드뉴스 초안: {post.get('title', topic)}\n폼: {forms.FORM_NAMES[post['form']]} / {len(files)}장"
        if warns:
            head += "\n⚠️ " + "\n⚠️ ".join(warns)
        notify.send_photos(files, head)
        if canva:   # 주소가 길어서 사진 설명(1024자 제한) 대신 따로 보냄
            notify.send("🎨 캔바에서 고치기 ('핫코노미 · 발행 대기' 폴더)\n" + canva["edit_url"])
        notify.send("캡션 초안\n\n" + caption + ("\n\n출처\n" + "\n".join(post.get("sources", [])[:5]) if post.get("sources") else ""))


if __name__ == "__main__":
    sys.exit(main())
