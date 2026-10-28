"""핫코노미 카드뉴스 디자인 폼 11개 (벤치마크 45개 캐러셀 분석, 2026-10-28).

    from publish.forms import make, pick_form
    form = pick_form("속보", recent=["list", "bars"])     # 소재 종류 → 폼 (최근 3개에 쓴 폼은 피함)
    files = make({"form": form, "cover": {...}, "slides": [...], "end": {...}}, out_dir, "name")
    python -m publish.forms --demo                         # 11개 폼 예시를 output/cardnews/forms/ 에 그림

공통 규칙 (벤치마크에서 따옴)
  - 브랜드는 맨 아래 가운데 작게 (불스토리·월부), 페이지 번호는 오른쪽 아래 (불스토리)
  - 제목 2줄·줄당 10~16자, 숫자/% 크게, 핵심 단어만 강조색 (**단어**)
  - 본문은 한 장에 한 메시지 (이끼·크립토데일리) — 긴 문단은 반응이 낮았음 (스노우볼)
  - 마지막 장: 저장·팔로우 + 댓글 유도 (댓글이 알고리즘에 가장 강함)
  - 면책 문구는 마지막 장에만 작게 (캡션에도 넣음)
글 내용 스키마: 각 폼 함수의 docstring 참고. 줄바꿈은 \\n, 강조는 **...**.
"""
import html
import math
import random
import re
import sys

from common import ROOT
from publish.render import W, H, asset_uri, render

DISCLAIMER = "정보 제공용이며 투자 권유가 아닙니다"

# 소재 종류 → 어울리는 폼 (앞쪽일수록 우선)
KINDS = {
    "속보": ["breaking", "photo", "bignum"], "급등락": ["breaking", "bignum", "photo"],
    "숫자": ["bignum", "bars", "breaking"], "실적": ["bignum", "bars", "photo"], "지표": ["bignum", "paper", "bars"],
    "순위": ["bars", "list", "bignum"], "비교": ["bars", "list", "editorial"],
    "정리": ["list", "hot", "paper"], "절약": ["list", "editorial", "steps"], "N가지": ["list", "steps", "hot"],
    "이슈": ["photo", "breaking", "editorial"], "기업": ["photo", "bignum", "editorial"], "인물": ["photo", "quote", "story"],
    "썰": ["story", "editorial", "quote"], "입문": ["story", "hot", "steps"], "기초": ["hot", "story", "list"],
    "트렌드": ["editorial", "photo", "bars"], "생활": ["editorial", "list", "steps"],
    "브리핑": ["paper", "breaking", "list"], "방법": ["steps", "list", "hot"], "격언": ["quote", "editorial", "story"],
}
FORM_NAMES = {"breaking": "속보형", "bignum": "숫자 한 방형", "bars": "막대 비교형", "list": "TOP N 리스트형",
              "photo": "사진+한 줄 자막형", "story": "캐릭터 썰형", "editorial": "밝은 에디토리얼형", "paper": "아침 경제신문형",
              "steps": "단계별 따라하기형", "quote": "다크 인사이트형", "hot": "핫코노미 기본형"}


def pick_form(kind, recent=()):
    cands = KINDS.get(kind) or ["hot", "list", "photo"]
    for f in cands:
        if f not in list(recent)[-3:]:
            return f
    return cands[0]


# ── 글자 도우미 ──
def md(s):
    """줄바꿈 → <br>, **강조** → <b class=hl>."""
    s = html.escape(s or "")
    return re.sub(r"\*\*(.+?)\*\*", r'<b class="hl">\1</b>', s, flags=re.S).replace("\n", "<br>")


LOGO = asset_uri("brand/hotconomy_logo.png")

CSS = """
.s{position:relative;width:1080px;height:1350px;overflow:hidden;font-family:HSans,'Noto Sans CJK KR',sans-serif;--bg:#0b0b0d;--fg:#fff;--sub:#a9a9b2;--ac:#e3262b;--hl:#ffc23a;background:var(--bg);color:var(--fg);word-break:keep-all}
.light{--bg:#f4efe7;--fg:#1d1a17;--sub:#6e665e;--ac:#d8262b;--hl:#d8262b}
.white{--bg:#ffffff;--fg:#141414;--sub:#6b6b6b;--ac:#e3262b;--hl:#e3262b}
.paper{--bg:#ececea;--fg:#151515;--sub:#555;--ac:#d8262b;--hl:#d8262b}
.brk{--hl:#ff3344}
.navy{--bg:#0f1b2d;--fg:#fff;--sub:#9fb0c6;--ac:#ff4d4f;--hl:#ffc23a}
.hl{color:var(--hl)}
.foot{position:absolute;left:0;right:0;bottom:44px;display:flex;justify-content:center;align-items:center;gap:12px;font-size:28px;font-weight:700;color:var(--fg);opacity:.9}
.foot img{width:46px;height:46px;border-radius:50%}
.pn{position:absolute;right:56px;bottom:50px;font-size:26px;color:var(--sub);font-weight:500}
.demo{position:absolute;left:24px;top:20px;font-size:20px;color:#fff;background:#0008;padding:4px 10px;border-radius:6px;z-index:9}
.pad{position:absolute;left:72px;right:72px}
.t-xl{font-size:100px;font-weight:900;line-height:1.16;letter-spacing:-2px}
.t-l{font-size:80px;font-weight:900;line-height:1.18;letter-spacing:-1.5px}
.t-m{font-size:62px;font-weight:800;line-height:1.25;letter-spacing:-1px}
.b-l{font-size:48px;font-weight:500;line-height:1.55}
.b-m{font-size:40px;font-weight:500;line-height:1.55;color:var(--sub)}
.chip{display:inline-block;background:var(--ac);color:#fff;font-weight:800;font-size:32px;padding:10px 26px;border-radius:40px}
.center{text-align:center}
.serif{font-family:HSerif,'Noto Serif CJK KR',serif}
/* 속보 */
.ticker{position:absolute;top:0;left:0;right:0;height:96px;background:linear-gradient(90deg,#ff1f4b,#e3262b);color:#fff;font-weight:900;font-size:54px;white-space:nowrap;line-height:96px;letter-spacing:1px;overflow:hidden}
.pricebox{position:absolute;background:#fff;color:#1565c0;font-weight:700;font-size:40px;padding:10px 20px;border-radius:4px}
/* 리스트 */
.row{display:flex;align-items:center;gap:30px;margin-bottom:46px}
.ico{width:130px;height:130px;border-radius:50%;background:#ffffff14;display:flex;align-items:center;justify-content:center;font-size:70px;flex:none}
.row .nm{font-size:46px;font-weight:800;line-height:1.3}
.row .sm{font-size:32px;color:var(--sub);margin-top:4px}
.row .val{margin-left:auto;font-size:46px;font-weight:900;color:var(--hl);text-align:right;white-space:nowrap}
/* 사진 */
.ph{position:absolute;left:0;top:0;width:1080px;height:1010px;object-fit:cover}
.fade{position:absolute;left:0;right:0;top:700px;height:330px;background:linear-gradient(180deg,#0b0b0d00,#0b0b0d)}
/* 썰 */
.nar{display:inline-block;border:3px solid #222;padding:14px 22px;font-size:38px;font-weight:600;background:#fff}
.bub{position:absolute;background:#fff;border:4px solid #111;border-radius:48px;padding:30px 40px;font-size:48px;font-weight:700;line-height:1.4}
.bub:after{content:"";position:absolute;bottom:-34px;left:120px;border:18px solid transparent;border-top:20px solid #111}
.mascot{position:absolute;border-radius:50%}
/* 신문 */
.frame{position:absolute;inset:44px;border:3px solid #222;outline:1px solid #222;outline-offset:8px}
.mast{display:inline-block;border:3px solid #222;padding:10px 40px;font-family:HSerif,'Noto Serif CJK KR',serif;font-weight:900;font-size:62px}
.news{font-size:54px;font-weight:800;line-height:1.35;margin-bottom:34px}
.news u{text-decoration:none;box-shadow:inset 0 -14px 0 #d8262b55}
.term{font-size:40px;line-height:1.55;margin-bottom:26px}
.term b{color:#1f5fbf}
/* 단계 */
.ui{position:absolute;left:110px;right:110px;background:#f3f4f7;border-radius:36px;padding:44px;box-shadow:0 10px 40px #0001}
.ui .r{background:#fff;border-radius:18px;padding:22px 28px;font-size:36px;margin-bottom:18px;display:flex;gap:18px;align-items:center}
.ui .r.on{outline:5px solid var(--ac);font-weight:800}
.dot{width:46px;height:46px;border-radius:50%;background:var(--ac);color:#fff;font-weight:900;font-size:28px;display:flex;align-items:center;justify-content:center;flex:none}
/* 인사이트 */
.glow{position:absolute;inset:0;background:radial-gradient(circle at 50% 42%,#3a1416 0,#0b0b0d 60%)}
/* 기본형 */
.hotbg{position:absolute;inset:0;background:radial-gradient(circle at 92% 8%,#7a1418 0,#0b0b0d00 48%),radial-gradient(circle at 5% 100%,#5a2a0a 0,#0b0b0d00 40%)}
.point{position:absolute;left:72px;right:72px;background:#2a0e10;border:3px solid var(--ac);border-radius:28px;padding:30px 40px}
.point .k{font-size:30px;font-weight:800;color:#ff7a1a;margin-bottom:10px}
.point .v{font-size:46px;font-weight:800;line-height:1.35}
/* 마지막 */
.btns{position:absolute;left:90px;right:90px;display:flex;gap:30px}
.btn{flex:1;height:112px;border-radius:60px;display:flex;align-items:center;justify-content:center;font-size:40px;font-weight:800}
.btn.o{border:4px solid var(--fg)}
.btn.f{background:var(--ac);color:#fff}
.disc{position:absolute;left:0;right:0;bottom:110px;text-align:center;font-size:24px;color:var(--sub)}
"""


def foot(n, total, theme_logo=True):
    logo = f'<img src="{LOGO}">' if LOGO and theme_logo else ""
    return f'<div class="foot">{logo}핫코노미</div><div class="pn">{n}</div>'


# ── 차트 (SVG) ──
def candles_svg(series, w=1080, h=700, up="#ff2e4d", down="#2196f3", grid=True):
    """series: [(o,h,l,c)] — 한국식 색 (오르면 빨강, 내리면 파랑)."""
    lo, hi = min(s[2] for s in series), max(s[1] for s in series)
    y = lambda v: 40 + (hi - v) / (hi - lo or 1) * (h - 80)
    step = w / len(series)
    parts = [f'<svg width="{w}" height="{h}" xmlns="http://www.w3.org/2000/svg">']
    if grid:
        parts += [f'<line x1="0" x2="{w}" y1="{g}" y2="{g}" stroke="#ffffff12" stroke-width="2"/>' for g in range(60, h, 110)]
    for i, (o, hh, ll, c) in enumerate(series):
        x, col = i * step + step / 2, up if c >= o else down
        parts.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{y(hh):.1f}" y2="{y(ll):.1f}" stroke="{col}" stroke-width="3"/>')
        top, bot = y(max(o, c)), y(min(o, c))
        parts.append(f'<rect x="{x - step * .32:.1f}" y="{top:.1f}" width="{step * .64:.1f}" height="{max(bot - top, 3):.1f}" fill="{col}"/>')
    parts.append("</svg>")
    return "".join(parts), y(series[-1][3]), (len(series) - .5) * step


def line_svg(values, w=1080, h=300, color="#ff4d2e", fill=True):
    lo, hi = min(values), max(values)
    pts = [(i * w / (len(values) - 1), 20 + (hi - v) / (hi - lo or 1) * (h - 40)) for i, v in enumerate(values)]
    d = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = f'<polygon points="0,{h} {d} {w},{h}" fill="{color}" opacity=".14"/>' if fill else ""
    return f'<svg width="{w}" height="{h}" xmlns="http://www.w3.org/2000/svg">{area}<polyline points="{d}" fill="none" stroke="{color}" stroke-width="8" stroke-linejoin="round"/></svg>'


def bars_html(items, maxw=600, unit=""):
    """items: [{"label","value","text"(표시값),"hi":bool}]"""
    top = max(i["value"] for i in items) or 1
    rows = []
    for it in items:
        bw = max(8, it["value"] / top * maxw)
        col = "#ff4d4f" if it.get("hi") else "#5ec4b6"
        rows.append(f'<div style="display:flex;align-items:center;margin-bottom:26px"><div style="width:250px;font-size:34px;'
                    f'font-weight:{800 if it.get("hi") else 500};text-align:right;padding-right:22px">{html.escape(it["label"])}</div>'
                    f'<div style="height:54px;width:{bw:.0f}px;background:{col};border-radius:0 8px 8px 0"></div>'
                    f'<div style="font-size:36px;font-weight:800;padding-left:18px;color:{col}">{html.escape(it.get("text", str(it["value"]) + unit))}</div></div>')
    return "".join(rows)


def img_or_chart(spec, h=1010):
    """사진 주소(assets 기준 또는 file uri) 또는 {"line":[...]}/{"candles":[...]} → HTML."""
    if isinstance(spec, dict) and spec.get("candles"):
        svg, _, _ = candles_svg(spec["candles"], 1080, h)
        return f'<div style="position:absolute;left:0;top:0">{svg}</div>'
    if isinstance(spec, dict) and spec.get("line"):
        return f'<div style="position:absolute;left:0;top:{h - 520}px">{line_svg(spec["line"], 1080, 460)}</div>'
    if isinstance(spec, str) and spec:
        src = spec if "://" in spec else asset_uri(spec)
        return f'<img class="ph" src="{src}" style="height:{h}px">'
    return ""


# ── 폼별 표지·본문 ──
def f_breaking(c, s, n, t):
    """표지 c: title, chart{candles}, price(가격 라벨). 본문 s: tag, title, text, chart(선택)."""
    tick = "BREAKING NEWS&nbsp;&nbsp;&nbsp;" * 4
    if s is None:
        svg, py, px_ = candles_svg(c["chart"]["candles"], 900, 680)
        price = f'<div class="pricebox" style="left:{min(px_ + 60, 820):.0f}px;top:{py + 96 - 30:.0f}px">{html.escape(c.get("price", ""))}</div>' if c.get("price") else ""
        return (f'<div class="ticker">{tick}</div><div style="position:absolute;top:110px;left:20px">{svg}</div>{price}'
                f'<div class="pad center t-xl" style="top:880px;font-size:94px">{md(c["title"])}</div>')
    chart = ""
    if s.get("chart"):
        chart = f'<div style="position:absolute;left:0;top:800px;opacity:.9">{line_svg(s["chart"]["line"], 1080, 330, "#ff2e4d")}</div>'
    return (f'<div class="ticker" style="height:70px;line-height:70px;font-size:38px">{tick}</div>'
            f'<div class="pad" style="top:170px"><span class="chip">{html.escape(s.get("tag", "무슨 일?"))}</span></div>'
            f'<div class="pad t-l" style="top:280px">{md(s["title"])}</div>'
            f'<div class="pad b-l" style="top:{560 if len(s["title"]) < 14 else 660}px">{md(s.get("text", ""))}</div>{chart}')


def f_bignum(c, s, n, t):
    """표지 c: label, number, sub, line(선택). 본문 s: number, title, text."""
    grad = "background:linear-gradient(180deg,#ffd24a,#ff6a1a);-webkit-background-clip:text;color:transparent"
    if s is None:
        line = f'<div style="position:absolute;left:0;top:960px;opacity:.55">{line_svg(c["line"], 1080, 260)}</div>' if c.get("line") else ""
        return (f'{line}<div class="pad center b-m" style="top:250px;font-size:46px;color:#fff;font-weight:700">{md(c.get("label", ""))}</div>'
                f'<div class="pad center" style="top:360px;font-size:{170 if len(c["number"]) < 9 else 120}px;font-weight:900;letter-spacing:-4px;line-height:1.1;{grad}">{html.escape(c["number"])}</div>'
                f'<div class="pad center t-m" style="top:640px">{md(c.get("sub", ""))}</div>')
    return (f'<div class="pad" style="top:200px;font-size:140px;font-weight:900;letter-spacing:-3px;{grad}">{html.escape(s["number"])}</div>'
            f'<div class="pad t-m" style="top:420px">{md(s["title"])}</div><div class="pad b-l" style="top:640px">{md(s.get("text", ""))}</div>')


def f_bars(c, s, n, t):
    """표지 c: title, sub, bars[...]. 본문 s: title, bars(선택) 또는 text."""
    d = c if s is None else s
    head = (f'<div class="pad t-l" style="top:110px;font-size:{86 if s is None else 66}px">{md(d["title"])}</div>'
            f'<div class="pad b-m" style="top:{330 if s is None else 290}px">{md(d.get("sub", ""))}</div>')
    body = f'<div class="pad" style="top:470px">{bars_html(d["bars"])}</div>' if d.get("bars") else f'<div class="pad b-l" style="top:470px">{md(d.get("text", ""))}</div>'
    return head + body


def f_list(c, s, n, t):
    """표지 c: title, sub, count(숫자). 본문 s: title, items[{icon,name,sub,value}] (최대 3개)."""
    if s is None:
        return (f'<div class="pad b-m" style="top:230px;font-size:44px">{md(c.get("sub", ""))}</div>'
                f'<div class="pad t-xl" style="top:320px">{md(c["title"])}</div>'
                f'<div style="position:absolute;right:60px;top:760px;font-size:360px;font-weight:900;color:#e3262b;opacity:.9;line-height:1">{html.escape(str(c.get("count", "")))}</div>')
    rows = "".join(f'<div class="row"><div class="ico">{it.get("icon", "•")}</div><div><div class="nm">{md(it["name"])}</div>'
                   f'<div class="sm">{md(it.get("sub", ""))}</div></div><div class="val">{html.escape(it.get("value", ""))}</div></div>' for it in s["items"][:3])
    return f'<div class="pad t-m" style="top:150px">{md(s["title"])}</div><div class="pad" style="top:420px">{rows}</div>'


def f_photo(c, s, n, t):
    """표지 c: image(사진 경로 또는 {"line"/"candles"}), title. 본문 s: image, text(한두 줄)."""
    d = c if s is None else s
    size = 90 if s is None else 64
    return (f'{img_or_chart(d.get("image"))}<div class="fade"></div>'
            f'<div class="pad center" style="top:{1020 if s is None else 1050}px;font-size:{size}px;font-weight:900;line-height:1.22;letter-spacing:-1px">{md(d.get("title") or d.get("text", ""))}</div>')


def f_story(c, s, n, t):
    """표지 c: label, title. 본문 s: narration(상자), say(말풍선)."""
    m = f'<img class="mascot" src="{LOGO}" style="width:460px;height:460px;left:310px;top:760px">' if LOGO else ""
    if s is None:
        return (f'<div class="pad" style="top:120px;font-size:30px;color:#888">{md(c.get("label", "핫코노미 썰"))}</div>'
                f'<div class="pad t-l" style="top:180px;color:#111">{md(c["title"])}</div>{m}')
    nar = f'<div class="pad" style="top:110px"><span class="nar">{md(s.get("narration", ""))}</span></div>' if s.get("narration") else ""
    return nar + f'<div class="bub" style="left:110px;right:110px;top:380px">{md(s.get("say", ""))}</div>{m}'


def f_editorial(c, s, n, t):
    """표지 c: kicker, title, image(선택), caption. 본문 s: title, image(선택), caption."""
    d = c if s is None else s
    kick = f'<div class="pad center" style="top:120px;font-size:26px;letter-spacing:12px;color:var(--sub)">{html.escape(c.get("kicker", "HOTCONOMY"))}</div>' if s is None else ""
    img = ""
    if d.get("image"):
        src = d["image"] if "://" in str(d["image"]) else asset_uri(d["image"])
        img = f'<img src="{src}" style="position:absolute;left:240px;top:{620 if s is None else 520}px;width:600px;height:420px;object-fit:cover;border-radius:24px">'
    elif d.get("line"):
        img = f'<div style="position:absolute;left:140px;top:{640 if s is None else 540}px">{line_svg(d["line"], 800, 360, "#d8262b")}</div>'
    return (kick + f'<div class="pad center serif" style="top:{200 if s is None else 150}px;font-size:{88 if s is None else 70}px;font-weight:700;line-height:1.22;letter-spacing:-1px">{md(d["title"])}</div>'
            + img + f'<div class="pad center" style="top:1080px;font-size:32px;color:var(--sub);line-height:1.5">{md(d.get("caption", ""))}</div>')


def f_paper(c, s, n, t):
    """표지 c: date, headlines[3](**강조**는 밑줄). 본문 s: title, terms[{term,desc}] 또는 headlines."""
    fr = '<div class="frame"></div>'
    if s is None:
        heads = "".join(f'<div class="news">{i}. {md(h).replace("<b class=\"hl\">", "<u>").replace("</b>", "</u>")}</div>' for i, h in enumerate(c["headlines"][:3], 1))
        return (fr + f'<div class="pad center" style="top:110px;font-size:34px;font-weight:700">{html.escape(c.get("date", ""))}</div>'
                f'<div class="pad center" style="top:170px"><span class="mast">핫코노미 경제신문</span></div>'
                f'<div class="pad" style="top:380px;left:110px;right:110px">{heads}</div>')
    if s.get("terms"):
        body = "".join(f'<div class="term">• <b>{html.escape(x["term"])}</b> : {md(x["desc"])}</div>' for x in s["terms"])
    else:
        body = "".join(f'<div class="term">• {md(h)}</div>' for h in s.get("headlines", []))
    return fr + f'<div class="pad center" style="top:130px;font-size:56px;font-weight:800">[{html.escape(s["title"])}]</div><div class="pad" style="top:300px;left:110px;right:110px">{body}</div>'


def f_steps(c, s, n, t):
    """표지 c: title, sub, steps(단계 수). 본문 s: step, title, ui[행 텍스트], on(강조할 행 번호), tip."""
    if s is None:
        dots = "".join(f'<div class="dot" style="width:90px;height:90px;font-size:44px">{i}</div>' for i in range(1, c.get("steps", 4) + 1))
        return (f'<div class="pad t-xl" style="top:230px;color:var(--fg)">{md(c["title"])}</div>'
                f'<div class="pad b-m" style="top:640px;font-size:44px">{md(c.get("sub", ""))}</div>'
                f'<div class="pad" style="top:860px;display:flex;gap:30px">{dots}</div>')
    rows = "".join(f'<div class="r{" on" if i == s.get("on") else ""}"><span class="dot">{i}</span>{md(r)}</div>' for i, r in enumerate(s.get("ui", []), 1))
    return (f'<div class="pad" style="top:110px"><span class="chip">STEP {s["step"]}</span></div>'
            f'<div class="pad t-m" style="top:220px">{md(s["title"])}</div><div class="ui" style="top:470px">{rows}</div>'
            f'<div class="pad center b-l" style="top:1060px;font-weight:700">{md(s.get("tip", ""))}</div>')


def f_quote(c, s, n, t):
    """표지 c: label, quote, by. 본문 s: quote, by(선택)."""
    d = c if s is None else s
    lab = f'<div class="pad center" style="top:150px;font-size:30px;color:var(--sub);letter-spacing:6px">{html.escape(c.get("label", "INSIGHT"))}</div>' if s is None else ""
    return ('<div class="glow"></div>' + lab +
            f'<div class="pad center serif" style="top:{380 if s is None else 420}px;font-size:{72 if s is None else 58}px;font-weight:700;line-height:1.45">{md(d["quote"])}</div>'
            f'<div class="pad center" style="top:1010px;font-size:34px;color:var(--sub)">{html.escape(d.get("by", ""))}</div>')


def f_hot(c, s, n, t):
    """표지 c: tag, title, sub. 본문 s: title, text, point."""
    bg = '<div class="hotbg"></div>'
    if s is None:
        line = f'<div style="position:absolute;left:0;top:930px;opacity:.9">{line_svg([3, 4, 3.6, 5, 4.6, 6.4, 6, 8.2], 1080, 300, "#ff3b2e", False)}</div>'
        return (bg + line + f'<div class="pad" style="top:200px"><span class="chip">{html.escape(c.get("tag", "경제 기초"))}</span></div>'
                f'<div class="pad t-xl" style="top:300px;font-size:112px">{md(c["title"])}</div>'
                f'<div class="pad b-m" style="top:770px;font-size:44px">{md(c.get("sub", ""))}</div>')
    pt = f'<div class="point" style="top:930px"><div class="k">🔥 핵심</div><div class="v">{md(s["point"])}</div></div>' if s.get("point") else ""
    return (bg + f'<div class="pad" style="top:150px;font-size:150px;font-weight:900;color:#ff7a1a;line-height:1">{n - 1:02d}</div>'
            f'<div class="pad t-l" style="top:340px">{md(s["title"])}</div>'
            f'<div class="pad b-l" style="top:560px;font-size:52px">{md(s.get("text", ""))}</div>{pt}')


FORMS = {"breaking": (f_breaking, "brk"), "bignum": (f_bignum, ""), "bars": (f_bars, "navy"), "list": (f_list, ""),
         "photo": (f_photo, ""), "story": (f_story, "white"), "editorial": (f_editorial, "light"), "paper": (f_paper, "paper"),
         "steps": (f_steps, "white"), "quote": (f_quote, ""), "hot": (f_hot, "")}


def end_slide(e, n, theme):
    """마지막 장 e: title, checks[...], keyword(댓글 유도 단어, 선택)."""
    logo = f'<img src="{LOGO}" style="position:absolute;left:430px;top:140px;width:220px;height:220px;border-radius:50%">' if LOGO else ""
    checks = "<br>".join(f"✓&nbsp; {md(x)}" for x in e.get("checks", []))
    kw = (f'<div class="pad center" style="top:880px;font-size:38px;font-weight:700">💬 궁금한 점은 댓글에 <b class="hl">\'{html.escape(e["keyword"])}\'</b> 남겨 주세요</div>'
          if e.get("keyword") else "")
    return (logo + f'<div class="pad center t-m" style="top:400px">{md(e.get("title", "정리하면"))}</div>'
            f'<div class="pad b-l" style="top:540px;left:170px;font-size:44px;line-height:1.7">{checks}</div>{kw}'
            f'<div class="btns" style="top:980px"><div class="btn o">🔖 저장해두기</div><div class="btn f">팔로우 하기</div></div>'
            f'<div class="disc">{DISCLAIMER}</div><div class="pn">{n}</div>')


def make(post, out_dir, name, demo=False):
    fn, theme = FORMS[post["form"]]
    total = 1 + len(post.get("slides", [])) + 1
    tag = '<div class="demo">예시 · 발행 금지</div>' if demo else ""
    slides = [f'<div class="s {theme}">{tag}{fn(post["cover"], None, 1, total)}{foot(1, total)}</div>']
    for i, s in enumerate(post.get("slides", []), 2):
        slides.append(f'<div class="s {theme}">{tag}{fn(post["cover"], s, i, total)}{foot(i, total)}</div>')
    slides.append(f'<div class="s {theme}">{tag}{end_slide(post.get("end", {}), total, theme)}</div>')
    return render(slides, out_dir, name, CSS)


# ── 예시 (발행 금지 표시가 붙음 — 숫자는 모양 확인용) ──
def _walk(n, seed, drop=None):
    rnd, p, out = random.Random(seed), 100.0, []
    for i in range(n):
        o = p
        p = p * (1 + rnd.uniform(-.012, .016))
        if drop and i == n - 2:
            p *= drop
        out.append((o, max(o, p) * (1 + rnd.uniform(0, .006)), min(o, p) * (1 - rnd.uniform(0, .006)), p))
    return out


DEMO = {
    "breaking": {"cover": {"title": "○○ ETF, 발표 하나로\n**20% 가까이 급락**", "chart": {"candles": _walk(40, 3, .8)}, "price": "-18.05%"},
                 "slides": [{"tag": "무슨 일?", "title": "**정책 발표** 직후\n매도 폭탄", "text": "발표 30분 만에 거래량이 평소의\n10배로 늘었어요.", "chart": {"line": [9, 9.2, 9.1, 9.4, 9.3, 7.2, 7.4]}},
                            {"tag": "앞으로는?", "title": "반등 신호는\n**거래량**부터", "text": "급락 뒤 거래량이 줄면서\n가격이 버티는지 먼저 보세요."}],
                 "end": {"title": "오늘 체크", "checks": ["발표 전후 거래량", "환율 방향", "다음 일정"], "keyword": "ETF"}},
    "bignum": {"cover": {"label": "하루 만에 사라진 시가총액", "number": "$1조 450억", "sub": "미국 증시 **최악의 하루**", "line": [9, 8.8, 9.1, 8.6, 8.9, 7.1, 6.8]},
               "slides": [{"number": "-3.2%", "title": "나스닥 하루 낙폭", "text": "올해 들어 가장 크게 빠졌어요."},
                          {"number": "4,100억", "title": "빅테크 7곳 합계", "text": "AI 기대가 꺾이며\n**대형주**부터 흔들렸어요."}],
               "end": {"title": "기억할 숫자", "checks": ["-3.2% 나스닥", "$1조 시총", "VIX 급등"], "keyword": "나스닥"}},
    "bars": {"cover": {"title": "머스크 재산,\n**어느 정도**일까?", "sub": "한국 대기업 시가총액과 비교 (예시)",
                       "bars": [{"label": "A사", "value": 40, "text": "40조"}, {"label": "B사", "value": 95, "text": "95조"},
                                {"label": "C사", "value": 160, "text": "160조"}, {"label": "D사", "value": 420, "text": "420조"},
                                {"label": "머스크", "value": 600, "text": "600조", "hi": True}]},
             "slides": [{"title": "삼성전자 시총과\n**비슷한 수준**", "text": "한 사람의 재산이 한 나라 대표 기업과\n맞먹는다는 뜻이에요."}],
             "end": {"title": "한 줄 요약", "checks": ["개인 재산 1위", "대부분 주식 평가액", "주가 따라 크게 출렁"], "keyword": "머스크"}},
    "list": {"cover": {"sub": "직장인 대부분이 잘 모르는", "title": "일상 속\n**소비 착시**", "count": 6},
             "slides": [{"title": "매일 쓰는 돈이\n1년이면 이만큼", "items": [{"icon": "☕", "name": "매일 커피", "sub": "4,700원 × 365일", "value": "171만원"},
                                                                     {"icon": "🚕", "name": "주 1회 택시", "sub": "25,000원 × 52주", "value": "130만원"},
                                                                     {"icon": "🍪", "name": "편의점 간식", "sub": "4,500원 × 주 3회", "value": "70만원"}]},
                        {"title": "매달 나가는\n**구독료**도", "items": [{"icon": "📺", "name": "OTT 3개", "sub": "월 4만원", "value": "48만원"},
                                                                    {"icon": "📱", "name": "안 쓰는 앱 구독", "sub": "월 1.5만원", "value": "18만원"},
                                                                    {"icon": "💅", "name": "매달 네일", "sub": "월 5만원", "value": "60만원"}]}],
             "end": {"title": "합치면 1년에", "checks": ["약 **497만원**", "줄일 것 1개만 골라도", "적금 하나 생겨요"], "keyword": "절약"}},
    "photo": {"cover": {"image": {"candles": _walk(36, 9)}, "title": "엔비디아 실적 발표,\n**시장이 놀란 3가지**"},
              "slides": [{"image": {"line": [3, 3.4, 3.2, 4.1, 4.6, 5.2, 6.4]}, "text": "① 데이터센터 매출\n**예상보다 20% 많았어요**"},
                         {"image": {"candles": _walk(36, 13)}, "text": "② 다음 분기 전망도\n**더 높게** 잡았어요"}],
              "end": {"title": "정리하면", "checks": ["매출 서프라이즈", "전망 상향", "다음은 공급망 체크"], "keyword": "엔비디아"}},
    "story": {"cover": {"label": "핫코노미 썰 · 1화", "title": "결혼자금 3억을\n**전부 주식**에\n넣었습니다"},
              "slides": [{"narration": "나 결혼 준비하던 공무원이었거든.", "say": "여친이랑 돈도\n**꾸준히** 모으고 있었지."},
                         {"narration": "그런데 계좌를 열었는데,", "say": "…어?\n이게 **왜 반토막**이야?"}],
              "end": {"title": "이 썰의 교훈", "checks": ["목돈은 나눠서", "기한 있는 돈은 안전하게", "몰빵 금지"], "keyword": "2화"}},
    "editorial": {"cover": {"kicker": "MONEY · LIFE", "title": "요즘은\n평범한 것들이\n**사치**가 됐다", "line": [2, 2.3, 2.6, 3.1, 3.5, 4.2], "caption": "콘서트·반려동물·외식 물가 5년 변화 (예시)"},
                  "slides": [{"title": "콘서트 한 번이\n**사치**인 시대", "line": [5, 5.4, 6.1, 6.9, 7.8], "caption": "티켓값 5년 새 50% 넘게 올랐어요"}],
                  "end": {"title": "내 지갑 지키기", "checks": ["고정비 먼저 점검", "할인 시즌 활용", "비교 후 결제"], "keyword": "물가"}},
    "paper": {"cover": {"date": "10월 28일 (화)", "headlines": ["코스피 2,600선 **다시 회복**", "환율 1,380원… **수출주 웃었다**", "비트코인 **사상 최고가** 근접"]},
              "slides": [{"title": "오늘의 경제 용어", "terms": [{"term": "원금", "desc": "빌리거나 맡긴 돈 그 자체"}, {"term": "환율", "desc": "우리 돈과 외국 돈을 바꾸는 비율"},
                                                            {"term": "시가총액", "desc": "주가 × 주식 수, 회사의 몸값"}]}],
              "end": {"title": "내일 볼 일정", "checks": ["미국 소비자물가", "삼성전자 실적", "FOMC 의사록"], "keyword": "브리핑"}},
    "steps": {"cover": {"title": "ISA 계좌\n**5분 만에**\n만드는 법", "sub": "증권 앱 하나면 끝 (예시 화면)", "steps": 3},
              "slides": [{"step": 1, "title": "앱에서 **계좌 개설**\n메뉴 누르기", "ui": ["홈", "계좌 개설", "이벤트", "고객센터"], "on": 2, "tip": "로그인 후 맨 위 메뉴에 있어요"},
                         {"step": 2, "title": "**중개형 ISA**\n선택하기", "ui": ["일반 위탁 계좌", "중개형 ISA", "연금저축"], "on": 2, "tip": "주식·ETF를 직접 고를 수 있어요"}],
              "end": {"title": "다 됐어요!", "checks": ["신분증 준비", "중개형 ISA 선택", "비대면 인증"], "keyword": "ISA"}},
    "quote": {"cover": {"label": "투자 인사이트", "quote": "남들이 욕심낼 때\n두려워하고,\n**남들이 두려워할 때\n욕심내라**", "by": "— 워런 버핏"},
              "slides": [{"quote": "시장이 무너질 때\n**현금**은 가장 강한 무기가 된다."}],
              "end": {"title": "오늘의 질문", "checks": ["지금 내 현금 비중은?", "공포 때 살 목록은?", "분할 매수 계획은?"], "keyword": "버핏"}},
    "hot": {"cover": {"tag": "경제 기초", "title": "금리가 내리면\n내 돈은\n**어떻게 될까?**", "sub": "예금·대출·주식, 딱 3가지만"},
            "slides": [{"title": "예금·적금", "text": "새로 드는 예금 이자는\n낮아져요.", "point": "이미 든 고정금리 예금은 그대로!"},
                       {"title": "대출", "text": "변동금리 대출은\n이자 부담이 줄어요.", "point": "갈아타기 전 중도상환수수료 확인"}],
            "end": {"title": "정리하면", "checks": ["예금은 미리 묶어 두기", "대출은 조건부터 확인", "주식은 내린 이유 보기"], "keyword": "금리"}},
}


def demo():
    from PIL import Image, ImageDraw, ImageFont
    out = ROOT / "output" / "cardnews" / "forms"
    sheet_rows = []
    for form, post in DEMO.items():
        files = make({"form": form, **post}, out, form, demo=True)
        sheet_rows.append((form, files))
        print(f"✅ {FORM_NAMES[form]} ({form}) {len(files)}장")
    f = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 22)
    tw, th = 216, 270
    for k in range(0, len(sheet_rows), 4):
        rows = sheet_rows[k:k + 4]
        sh = Image.new("RGB", (tw * 5 + 40, (th + 34) * len(rows)), "white")
        d = ImageDraw.Draw(sh)
        for r, (form, files) in enumerate(rows):
            y = r * (th + 34)
            d.text((4, y + 4), f"{FORM_NAMES[form]} ({form})", fill="black", font=f)
            for ci, p in enumerate(files[:5]):
                sh.paste(Image.open(p).resize((tw - 6, th - 6)), (ci * (tw + 8), y + 32))
        sh.save(out / f"_sheet{k // 4 + 1}.jpg", quality=85)


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
