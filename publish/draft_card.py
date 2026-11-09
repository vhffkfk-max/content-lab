"""추천 주제 하나 → 실제 뉴스·시세로 카드뉴스 초안(이미지 + 캡션)을 만든다 (작업지시서 Phase 4).

    python -m publish.draft_card                    # 추천 1위(오늘 이미 만든 주제는 건너뜀)
    python -m publish.draft_card --topic 테슬라      # 주제 지정
    python -m publish.draft_card --dry-run          # Claude 호출 없이 프롬프트만 출력
    python -m publish.draft_card --no-send          # 텔레그램으로 안 보냄
    python -m publish.draft_card --no-canva         # 캔바 사본 안 만듦

숫자 원칙: 시세 숫자는 코드가 야후 차트에서 가져와 넣고, 사실은 모아 둔 뉴스 제목에 있는 것만 쓴다.
  Claude 는 폼을 고르고 글만 쓴다. 차트 자리는 {"ticker": "TSLA"} 로 남기면 코드가 실제 시세로 채운다.
폼 돌려쓰기: forms.ACTIVE 8가지 중 최근 4개 게시물에 쓴 폼은 뺀다 (예외 없음. 사진 뉴스형만 예외로 뒀더니 하루 8개가 전부 같은 모양이 됨, 2026-11-04). 왜 이 폼인지는 큐 design_why 에 남긴다.
학습(publish/card_learn.py): 대표가 캔바에서 고친 습관 규칙과 폼별 48시간 성적이 프롬프트에 들어가고, 성적이 계속 나쁜 폼은 후보에서 빠진다.
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
import viral_rules
from publish import caption_check, card_learn, forms, notify

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


def chart_facts(topic):
    """차트덕후 메인 컨텐츠(output/site/chart_daily.json)에서 고른 종목이면 그 글의 문장만 재료로 쓴다."""
    p = SITE / "chart_daily.json"
    if not p.exists():
        return []
    d = json.loads(p.read_text(encoding="utf-8"))
    item = next((i for i in d.get("items", []) if i.get("topic") == topic), None)
    if not item:
        return []
    src = "; ".join(s["url"] for s in item.get("sources", []))
    return [{"source": "차트덕후 메인", "published": d.get("date", ""), "title": line.strip(), "link": src}
            for post in item.get("posts", []) for line in post["text"].splitlines()
            if line.strip() and not line.startswith(("이유는", "제가 그리는", "경로와 시간"))]


def headlines(topic, n=25):
    if facts := chart_facts(topic):
        return facts
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


def pick_hot(queue):
    """속보형(--short) 재료: 30분마다 바뀌는 '지금 발행할 거리'(hot_now) 중 오늘 아직 안 만든 것. 인스타 칸을 먼저."""
    try:
        h = json.loads((SITE / "hot_now.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    today = datetime.now(KST).strftime("%Y-%m-%d")
    done = {i.get("hot_title") for i in queue["items"] if i.get("created_at", "").startswith(today)}
    picks = [p for run in h[:6] for p in run.get("picks", []) if p.get("title") not in done]
    picks.sort(key=lambda p: 0 if "인스타" in p.get("channel", "") else 1)
    return picks[0] if picks else None


def hot_by_title(title):
    """사이트 '지금 쓸 거리' 카드에서 누른 제목 → 그 글감 (지난 것까지 찾음)."""
    norm = lambda s: " ".join(str(s or "").split())[:60].strip()
    try:
        h = json.loads((SITE / "hot_now.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return next((p for run in h for p in run.get("picks", []) if norm(p.get("title")) == norm(title)), None)


SHORT = """

[이번 글은 속보형 짧은 카드]
- 표지 + 본문 1~3장 + 마지막 장, 모두 합쳐 3~5장. slides 는 1~3개만.
- 아래 [지금 발행할 거리]의 사건 하나만 다룹니다. 표지에 가장 큰 숫자 하나, 본문은 '무슨 일 → 왜 중요 → 다음에 볼 것'.
- 폼은 news·bignum 처럼 짧게 읽히는 것을 우선합니다."""


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
- 표지 + 본문 + 마지막 장을 합쳐 6~8장(최대 10장). slides 는 본문 장만 넣습니다(표지·마지막 장 제외, 4~6개). 폼 설명에 장수가 따로 있으면 그걸 따릅니다.
- 재료가 모자라면 장을 채우려고 지어내거나 같은 말을 반복하지 말고 5장까지 줄입니다.

디자인 규칙 (같은 계정의 잘 된 글과 안 된 글을 비교한 결과):
- 표지 제목은 주제 요약이 아니라 사건입니다. 누가, 얼마나, 무슨 반전인지 구체적으로 씁니다. '수출 전망 정리' (X) → '수출 1조 달러, 세계 4번째 눈앞' (O)
- [쓸 수 있는 폼] 안에서 이 소재를 가장 잘 살리는 폼을 고릅니다. 사진 뉴스형이 없으면 없는 대로, 다른 폼으로 사건이 살아나게 씁니다. 빠른 사건은 속보형, 숫자가 훅이면 숫자형, 사실 여러 개는 리스트형이나 신문형, 실제 발언이 있으면 인사이트형입니다.
- 어떤 폼이든 재료에 없는 사실, 수치, 발언을 채우려고 지어내지 않습니다.
- 2번째 장은 표지를 안 본 사람에게 먼저 보일 수 있습니다. 앞 장 없이도 무슨 일인지 알게 씁니다.
- 본문 한 장에 사실 하나만, 큰 글씨로 읽히게 짧게 씁니다. 긴 문단을 쓰지 않습니다.
- 모든 장이 표지의 사건 하나를 따라갑니다. 그 사건과 직접 이어지지 않는 다른 종목의 등락이나 그날 시황으로 새지 않습니다.
- design_note 에 이번 글에 왜 이 폼과 이 표지를 골랐는지 한두 문장으로 적습니다(예: '주인공이 분명한 사건이라 얼굴 표지로, 숫자 28%를 제목에 넣어 멈추게 함').

폼 규칙:
- [쓸 수 있는 폼] 중 소재에 가장 맞는 것 하나를 고르고, 그 폼의 필드 설명대로 cover/slides 를 채웁니다.
- 사진 뉴스형(news), 에디토리얼(editorial)은 장마다 빠짐없이 bg(영어 사진 검색어)를 넣습니다. 글 내용과 바로 연결되는 인물, 사물, 장소로 씁니다. 사진 뉴스형에서 주가 움직임을 말하는 장 하나만 bg 대신 chart 를 씁니다(한 글에 1장까지). 표지에는 bg_alt 도 넣습니다: 인물 사진이 없을 때 대신 쓸, 사진이 많은 회사 제품이나 건물의 영어 검색어(예: 'Korean Air Boeing'). 한국 경영인은 무료 사진이 거의 없습니다.
- 차트·이미지 자리(chart, image, line)에는 {"ticker": "시세 코드"} 만 넣습니다. 코드가 실제 시세로 그립니다. 사진 경로는 쓰지 않습니다.
- 막대(bars)는 [시세]의 등락률로만 만듭니다: {"label","value"(숫자),"text"(표시값),"hi"(강조 여부)}.
- end.keyword 는 댓글로 받을 짧은 단어 하나(예: '환율').

캡션 규칙:
- 첫 줄 훅(40자 이내) → 핵심 3줄 → 행동 유도 하나(댓글 키워드) → 빈 줄 → '(정보 제공용이며 투자 권유가 아닙니다)'.
- '~요'체로 통일하고 문장 길이를 섞습니다. 사람들이 검색할 말(종목, 주제어)을 문장 안에 자연스럽게 넣습니다. 본문에 주소를 넣지 않습니다. 행동 유도는 end.keyword 를 쓴 것 하나만 둡니다.
- 해시태그 3~5개(인스타 공식 상한 5개): #핫코노미 1개 + 주제 태그 + 대형 태그 1개. 다른 계정, 매체, 회사 이름 태그 금지.
- youtube: 쇼츠용 제목(40자 이내)과 설명(2~3줄 + 면책 문구).

BGM 추천(bgm): 사람이 인스타 앱에서 곡을 찾아 듣고 고를 때 쓰는 힌트입니다.
- mood: 이 글 내용에 맞는 분위기 한 줄(예: '긴장감 있는 낮은 비트, 빠르지 않게').
- search: 앱 음악 검색에 넣을 분위기, 장르 검색어 2~3개. 특정 곡명과 가수 이름은 쓰지 않습니다(지어낸 곡이 나올 수 있고 앱에 없을 수 있음).
- avoid: 이 글에 안 맞는 분위기 한 줄(예: 폭락, 사고, 피해 소식이면 '밝고 신나는 곡').

출력: 설명 없이 JSON 하나만.
{"form": "폼 키", "kind": "소재 종류", "title": "게시물 제목(관리용)", "design_note": "이 폼을 고른 이유", "cover": {...}, "slides": [{...}], "end": {"title","checks":[3개],"keyword"},
 "caption": "...", "hashtags": ["#..."], "youtube": {"title","description"}, "bgm": {"mood","search":["..."],"avoid"}, "sources": ["쓴 뉴스 링크"]}"""


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
            f"[연구소 기획안] (방향 참고용, [확인] 칸은 위 재료로 채울 수 있을 때만)\n{plan_txt}\n\n[쓸 수 있는 폼] (최근 게시물에 쓴 폼은 빠져 있음)\n{form_specs(allowed)}"
            + (f"\n\n{learned}" if (learned := card_learn.prompt_notes(allowed)) else "")
            + (f"\n\n{viral}" if (viral := viral_rules.prompt_notes("카드뉴스")) else ""))   # 뜬 글 공식 (viral_analyze.py, 매일 갱신)


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
    return sorted(used)


def fill_photos(post):
    """배경 사진형: 장마다 bg 검색어로 실제 사진을 찾아 넣는다. 못 찾으면 표지 검색어, 그다음 bg_alt, 그래도 없으면 사진 없는 화면.
    표지는 비면 안 돼서 bg_alt 검색 1순위, 본문 사진, bg 검색 1순위 순으로 채운다. → 출처 목록."""
    if post["form"] not in forms.PHOTO_FORMS:
        return []
    from publish.photos import find
    used, credits = set(), []
    plain = lambda d: re.sub(r"\*\*|\n", " ", f'{d.get("title", "")} {d.get("text", "")}')
    cover = post["cover"]
    main_q, alt_q, has_chart = cover.get("bg", ""), cover.pop("bg_alt", ""), False
    for d in [post["cover"], *post.get("slides", [])]:
        q = d.pop("bg", "")
        if d.get("chart") and post["form"] == "news":   # 주가 장은 실제 시세가 그림 자리를 채움 (한 글에 1장만)
            if not has_chart:
                has_chart = True
                continue
            d.pop("chart")
        p = find(q, used, about=plain(d)) if q else None
        if not p and main_q and d is not cover:
            p = find(main_q, used, about=plain(cover))
        if not p and alt_q:
            p = find(alt_q, used, about=plain(cover))
        if p:
            used.add(p["url"])
            d["photo"], d["credit"] = p["uri"], p["credit"]
            credits.append(f"{p['credit']} {p['page']}".strip())
        else:
            print("⚠️ 사진 못 찾음 (그라데이션 배경):", q)
    if not cover.get("photo"):
        lent = next((s for s in post.get("slides", []) if s.get("photo")), None)
        if p := find(alt_q, used) if alt_q else None:
            cover["photo"], cover["credit"] = p["uri"], p["credit"]
            credits.append(f"{p['credit']} {p['page']}".strip())
        elif lent:
            cover["photo"], cover["credit"] = lent["photo"], lent["credit"]
        elif p := find(main_q, used) if main_q else None:
            cover["photo"], cover["credit"] = p["uri"], p["credit"]
            credits.append(f"{p['credit']} {p['page']}".strip())
    return credits


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
    if post["form"] in forms.PHOTO_FORMS and not post["cover"].get("photo"):
        warns.append("표지 사진을 못 찾았어요")
    if "투자 권유가 아닙니다" not in post["caption"]:
        post["caption"] = post["caption"].rstrip() + "\n\n(정보 제공용이며 투자 권유가 아닙니다)"
    return warns


def photo_credit_lines(post):
    """CC 사진은 출처 표시가 조건이다. 카드 위에는 안 쓰고 캡션 끝에 모아 적는다."""
    return "\n".join(dict.fromkeys(d["credit"] for d in [post["cover"], *post.get("slides", [])] if d.get("credit")))


def bgm_tip(post):
    """AI가 준 BGM 추천을 정리. 없거나 모양이 틀리면 빈 값(추천일 뿐이라 초안을 막지 않는다)."""
    b = post.get("bgm")
    if not isinstance(b, dict):
        return {}
    search = b.get("search")
    search = [str(x).strip() for x in search if str(x).strip()][:3] if isinstance(search, list) else []
    mood, avoid = str(b.get("mood") or "").strip(), str(b.get("avoid") or "").strip()
    return {"mood": mood, "search": search, "avoid": avoid} if mood or search else {}


def bgm_line(tip):
    parts = [tip.get("mood", ""), "검색어: " + ", ".join(tip["search"]) if tip.get("search") else "", "피하기: " + tip["avoid"] if tip.get("avoid") else ""]
    return " / ".join(p for p in parts if p)


def pick_of(queue, pick):
    """'추천안id|표지번호|폼|글꼴|short' → 고른 내용. 형식이 틀리거나 추천안이 없으면 멈춘다(요청은 사이트에서 오므로 믿지 않는다)."""
    from publish.card_ideas import cover_for
    m = re.fullmatch(r"([0-9a-z-]{8,30})\|(\d)\|([a-z]+)\|([a-z]+)\|(short|long)", pick or "")
    if not m:
        raise SystemExit(f"⚠️ 고른 내용 형식이 달라요: {pick}")
    idea = next((i for i in queue.get("ideas", []) if i["id"] == m[1]), None)
    if not idea or int(m[2]) >= len(idea["hooks"]) or m[3] not in forms.FORM_FONTS or m[4] not in forms.FORM_FONTS[m[3]]:
        raise SystemExit(f"⚠️ 고른 추천안을 찾을 수 없어요: {pick}")
    hook = idea["hooks"][int(m[2])]
    cover = cover_for(idea, hook, m[3])
    if cover is None:
        raise SystemExit(f"⚠️ 이 폼으로는 표지를 만들 수 없어요: {pick}")
    return {"idea": idea, "hook": hook, "form": m[3], "font": m[4], "cover": cover, "short": m[5] == "short"}


def picked_note(c):
    i = c["idea"]
    return (f"\n\n[대표가 고른 것] 반드시 따릅니다.\n주제: {i['title']}\n컨셉: {i.get('concept', '')}\n왜 지금: {i.get('why_now', '')}\n"
            f"폼: {c['form']} (이 폼의 칸대로 씁니다)\n표지 문구: {c['hook']['title']} (표지는 이 문구 그대로, 본문은 이 문구가 말한 사건을 따라갑니다)\n"
            f"근거 링크: {', '.join(i.get('sources', []))}\n")


def hashtags(tags):
    tags = [t if t.startswith("#") else f"#{t}" for t in tags]
    tags = [t for t in tags if not any(b in t.lower() for b in NOT_MINE)]
    if BRAND_TAG not in tags:
        tags.insert(0, BRAND_TAG)
    return list(dict.fromkeys(tags))[:5]   # 인스타 해시태그 상한 5개


def ask_claude(prompt, system=None, model=None):
    import llm as anthropic   # 내 PC Claude Code(Max 구독)로 실행 — API 요금 없음
    client = anthropic.Anthropic()
    msgs = [{"role": "user", "content": prompt}]
    for _ in range(2):
        r = client.messages.create(model=model or MODEL, max_tokens=8000, system=system or SYSTEM, messages=msgs)
        text = "".join(b.text for b in r.content if b.type == "text")
        print(f"   (입력 {r.usage.input_tokens:,} / 출력 {r.usage.output_tokens:,} 토큰)")
        m = re.search(r"\{.*\}", text, re.S)
        try:
            return json.loads(m.group(0))
        except (AttributeError, json.JSONDecodeError):
            msgs += [{"role": "assistant", "content": text}, {"role": "user", "content": "JSON 형식이 깨졌어요. JSON 하나만 다시 주세요."}]
    raise RuntimeError("Claude 가 JSON 을 주지 않았어요.")


def main():
    global SYSTEM, BRAND_TAG
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-send", action="store_true")
    ap.add_argument("--no-canva", action="store_true", help="캔바 사본 안 만듦")
    ap.add_argument("--short", action="store_true", help="속보형 3~5장 (지금 발행할 거리에서 주제)")
    ap.add_argument("--auto", action="store_true", help="PC 예약이 만든 것 (하루 개수 세기용)")
    ap.add_argument("--style", help="사이트 채널에서 고른 것: 계정:폼 (예 asset:bignum). 핫코노미 외 계정은 발행 큐에 넣지 않고 텔레그램으로만 보낸다")
    ap.add_argument("--pick", help="추천안에서 고른 것: 추천안id|표지번호|폼|글꼴|short 또는 long (publish/card_ideas.py)")
    a = ap.parse_args()
    load_env()
    brand, style_form = (a.style.split(":") + [""])[:2] if a.style else ("hot", "")
    if brand not in forms.BRANDS:
        sys.exit(f"모르는 계정: {brand}")
    b = forms.BRANDS[brand]
    forms.set_brand(brand)
    if brand != "hot":
        SYSTEM = SYSTEM.replace("@hotconomy(핫코노미)", f"{b['handle']}({b['name']})".replace("()", "")).replace("#핫코노미", b["tag"]) + f"\n\n[이 계정의 기준] {b['tone']}"
        BRAND_TAG = b["tag"]
        a.no_canva = True
    queue = load_queue()
    chosen = pick_of(queue, a.pick) if a.pick else None
    if chosen:
        a.topic, a.short = chosen["idea"]["title"], chosen["short"]
    hot = pick_hot(queue) if a.short and not a.topic else None
    if a.topic and not chosen and (h := hot_by_title(a.topic)):   # 지금 쓸 거리 카드의 버튼
        hot, a.short = h, True
    if a.short and not a.topic and not hot:
        a.short = False   # 지금 발행할 거리가 없으면 보통 초안으로
    topic = hot["title"] if hot else pick_topic(queue, a.topic)
    recent = [i["form"] for i in queue["items"] if i.get("form")][-4:]
    allowed = [chosen["form"]] if chosen else [style_form] if style_form in forms.ACTIVE else card_learn.prune([k for k in forms.ACTIVE if k not in recent])   # 성적이 계속 나쁜 폼은 뺌
    now = datetime.now(KST)
    print(f"📰 주제: {topic} / 최근 폼 {recent or '없음'} 제외")
    mk, news = market(), headlines(topic)
    prompt = build_prompt(topic, news, mk, plan_rows(topic), allowed, now.strftime("%Y-%m-%d (%a)"))
    if a.short:
        prompt += SHORT + (f"\n\n[지금 발행할 거리] ({hot.get('channel', '')})\n제목: {hot['title']}\n왜 지금: {hot.get('why_now', '')}\n"
                           f"참고 초안:\n{hot.get('draft', '')}\n근거: {', '.join(hot.get('sources', [])[:3])}" if hot else "")
    if chosen:
        prompt += picked_note(chosen)
    if a.dry_run:
        print(SYSTEM, "\n\n", prompt)
        return
    post = clean(ask_claude(prompt))
    if chosen:   # 사람이 고른 폼, 표지, 글꼴은 AI가 바꾸지 못하게 덮어쓴다
        post["form"], post["font"] = chosen["form"], chosen["font"]
        post["cover"] = {**(post.get("cover") or {}), **chosen["cover"]}
    if style_form in forms.ACTIVE:   # 사이트에서 고른 스타일은 AI가 바꾸지 못하게
        post["form"] = style_form
    if post.get("form") not in forms.ACTIVE:   # 돌려쓰기를 어겨도 8가지 안이면 그대로 (글 칸이 그 폼에 맞춰 쓰였음)
        post["form"] = forms.pick_form(post.get("kind", ""), recent)
    post["slides"] = post.get("slides", [])[:3 if a.short else MAX_SLIDES - 2]
    tickers = fill_charts(post, mk)
    post["photo_credits"] = fill_photos(post)
    warns = check(post)
    if post["form"] == "quote":   # 재료에 없는 발언은 사람이 꼭 보게
        src = re.sub(r"\s", "", str(news))
        warns += [f"발언이 재료에서 그대로 안 나와요: {q}" for q in (d.get("quote", "") for d in [post["cover"], *post.get("slides", [])])
                  if q and re.sub(r"\s|\*\*", "", q) not in src]
    post["hashtags"] = hashtags(post.get("hashtags", []))
    post["caption"] = caption_check.clean(post["caption"])
    did = f"{now:%Y%m%d-%H%M}-{post['form']}"
    files = forms.make(post, OUT / did, did)
    from publish.layout_check import check as layout_check
    warns += [f"글자 겹침: {x}" for x in layout_check(*reversed(forms._styled(post)), safe=True)]   # 겹치면 경고 → 발행 거절
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
    credits = photo_credit_lines(post)
    bgm = bgm_tip(post)
    if bgm:   # 사이트에서 들어 볼 실제 곡 후보
        from publish import bgm_tracks
        bgm["tracks"] = bgm_tracks.find(bgm.get("search"))
    bad, notes = caption_check.check(post["caption"], post.get("end", {}).get("keyword", ""))
    warns += bad
    caption = post["caption"].rstrip() + (f"\n\n{credits}" if credits else "") + "\n\n" + " ".join(post["hashtags"])
    if brand != "hot":   # 핫코노미 발행 큐에 섞이면 안 된다: 초안만 텔레그램으로
        print(f"✅ {b['name']} {forms.FORM_NAMES[post['form']]} {len(files)}장 → {OUT / did}")
        if not a.no_send:
            head = f"📝 {b['name']} 카드뉴스 초안: {post.get('title', topic)}\n폼: {forms.FORM_NAMES[post['form']]} / {len(files)}장" + ("\n⚠️ " + "\n⚠️ ".join(warns) if warns else "")
            notify.send_photos(files, head[:1000])
            notify.send("캡션 초안\n\n" + caption)
        return
    queue["items"].append({"id": did, "account": "hotconomy", "type": "carousel", "topic": topic, "form": post["form"],
                           "title": post.get("title", topic), "caption": caption, "youtube": post.get("youtube", {}),
                           "files": [str(f.relative_to(ROOT)).replace("\\", "/") for f in files], "tickers": tickers,
                           "sources": post.get("sources", []), "photo_credits": post.get("photo_credits", []), "warnings": warns, "caption_notes": notes, "bgm": bgm, "status": "drafted", "risk": None,
                           "published": {}, "canva": canva, "created_at": now.isoformat(timespec="seconds"),
                           "design_why": {"form": forms.FORM_NAMES[post["form"]], "note": post.get("design_note", ""), "evidence": forms.FORM_WHY.get(post["form"], ""),
                                          "formula": viral_rules.used_formula(post.get("design_note", ""))},   # 쓴 뜬 글 공식 → 나중에 48시간 성적과 맞춰 봄
                           "series": "short" if a.short else "deep", "auto": a.auto, "font": post.get("font", ""), "idea": chosen["idea"]["id"] if chosen else "", "hot_title": hot["title"] if hot else None})
    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    QUEUE.write_text(json.dumps(queue, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ {forms.FORM_NAMES[post['form']]} {len(files)}장 → {OUT / did}")
    for w in warns:
        print("⚠️", w)
    if not a.no_send:
        head = f"📝 카드뉴스 초안: {post.get('title', topic)}\n폼: {forms.FORM_NAMES[post['form']]} / {len(files)}장\n올릴 때 첫 장에서 ⤢ 눌러 4:5로 (그대로 1:1이면 위아래가 잘려요)"
        if post.get("design_note"):
            head += f"\n왜 이렇게: {post['design_note']}"
        if warns:
            head += "\n⚠️ " + "\n⚠️ ".join(warns)
        if notes:
            head += "\n✏️ 캡션 참고: " + " / ".join(notes)
        if bgm:
            head += "\n🎵 BGM: " + bgm_line(bgm)
        notify.send_photos(files, head)
        try:   # 연구소 사이트 미리보기 (실패해도 초안은 그대로)
            from publish.card_preview import push as push_preview
            print("미리보기:", push_preview({did: files}))
        except Exception as e:
            print("⚠️ 미리보기 실패 (초안은 그대로):", e)
        if canva:   # 주소가 길어서 사진 설명(1024자 제한) 대신 따로 보냄
            notify.send("🎨 캔바에서 고치기 ('핫코노미 · 발행 대기' 폴더)\n" + canva["edit_url"])
        notify.send("캡션 초안\n\n" + caption + ("\n\n출처\n" + "\n".join(post.get("sources", [])[:5]) if post.get("sources") else ""))


if __name__ == "__main__":
    sys.exit(main())
