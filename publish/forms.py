"""핫코노미 카드뉴스 디자인 폼 (벤치마크 45개 캐러셀 2026-10-28, 계정 16곳 50개 글 비교 2026-11-02 → publish/DESIGN_NOTES.md).

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
    "속보": ["breaking", "news", "bignum"], "급등락": ["breaking", "bignum", "bars", "news"], "이슈": ["news", "quote", "paper", "editorial"], "인물": ["quote", "news", "editorial"],
    "기업": ["news", "bignum"], "숫자": ["bignum", "bars", "news"], "실적": ["bignum", "bars", "news"], "지표": ["bignum", "bars"],
    "순위": ["list", "bars", "bignum"], "비교": ["bars", "list", "editorial"], "트렌드": ["editorial", "news"], "생활": ["editorial", "news"],
    "절약": ["editorial", "bars"], "정리": ["paper", "list", "editorial", "news"], "입문": ["editorial", "bignum"], "썰": ["editorial", "news"],
}
# 새 초안에 쓰는 8가지. 나머지(photo, scene 은 news 와 비슷, story 는 그림 도구 없음, steps 는 앱 화면을 지어내게 됨, hot)는 옛 초안을 다시 그릴 때만 쓴다.
# 최근 4개 글에 쓴 폼은 draft_card 가 뺀다. 모두 같은 규칙이라 한 폼이 연달아 나오지 않는다.
ACTIVE = ["news", "bignum", "breaking", "editorial", "list", "bars", "quote", "paper"]
# 제목 글꼴: 사람이 표지 시안을 보고 고른다 (글꼴이 내용과 맞는지는 감각의 문제라, 2026-11-05)
FONTS = {"noto": {"name": "기본"}, "black": {"name": "굵은 헤드라인", "family": "HBlack"}, "dohyeon": {"name": "친근한 고딕", "family": "HDohyeon"},
         "myeongjo": {"name": "신문 명조", "family": "HMyeongjo"}, "gowun": {"name": "잡지 명조", "family": "HGowun"}, "plex": {"name": "또렷한 고딕", "family": "HPlex"}}
# 폼마다 어울리는 글꼴 3개 (표지 시안을 이 조합으로 그림)
FORM_FONTS = {"breaking": ["noto", "black", "dohyeon"], "news": ["noto", "black", "myeongjo"], "editorial": ["noto", "gowun", "plex"], "bignum": ["noto", "black", "dohyeon"],
              "list": ["noto", "black", "plex"], "bars": ["noto", "plex", "dohyeon"], "paper": ["noto", "myeongjo", "gowun"], "quote": ["noto", "myeongjo", "gowun"]}
# 사진을 위키미디어에서 찾아 채우는 폼
PHOTO_FORMS = {"scene", "news", "editorial"}
FORM_NAMES = {"breaking": "속보형", "bignum": "숫자 한 방형", "bars": "막대 비교형", "list": "TOP N 리스트형",
              "photo": "사진+한 줄 자막형", "story": "캐릭터 썰형", "editorial": "밝은 에디토리얼형", "paper": "아침 경제신문형",
              "steps": "단계별 따라하기형", "quote": "다크 인사이트형", "hot": "핫코노미 기본형", "scene": "배경 사진형", "news": "사진 뉴스형"}
# 왜 이 폼을 쓰나: 지켜보는 계정 글을 같은 계정 안에서 비교한 근거 (DESIGN_NOTES.md, 좋아요 기준, 주제 영향이 섞여 있음)
FORM_WHY = {
    "news": "같은 계정 비교: 한경미디어 얼굴 사진+큰 제목 4,568 좋아요, 글자만 있는 '이슈 한 입' 10. 크립토데일리 51,302. 매일경제, 머니투데이도 같은 구성이 계정 중앙값의 18~24배.",
    "editorial": "friendsthatinvest 47,989 좋아요(계정 중앙값의 10배): 밝은 바탕, 큰 세리프 제목, 내용을 보여 주는 사진 한 장, 설명은 한두 줄.",
    "bignum": "크립토데일리 '$1,045,000,000,000' 표지처럼 숫자를 크게 보여 주는 구성 (계정 중앙값의 32배). 숫자 하나가 곧 훅.",
    "breaking": "속보 소재를 빨간 띠로 바로 알아보게. 다양성을 위해 넣었고 아직 @hotconomy 성적이 없음 (card_learn 이 쌓아서 판단)",
    "list": "여러 사실을 값과 함께 줄 세워 저장하기 좋게. 다양성을 위해 넣었고 아직 @hotconomy 성적이 없음 (card_learn 이 쌓아서 판단)",
    "quote": "실제 발언 한마디가 사건일 때. 다양성을 위해 넣었고 아직 @hotconomy 성적이 없음 (card_learn 이 쌓아서 판단)",
    "paper": "신문 1면처럼 사실 3개를 한 장에. 다양성을 위해 넣었고 아직 @hotconomy 성적이 없음 (card_learn 이 쌓아서 판단)",
    "bars": "personalfinanceclub 'Elon's Trillion' 309,394 좋아요(계정 중앙값의 80배): 막대로 규모 차이를 눈으로 보여 줌.",
}


def pick_form(kind, recent=()):
    cands = KINDS.get(kind) or ["news", "editorial"]
    for f in cands:
        if f not in list(recent)[-4:]:
            return f
    return next((f for f in ACTIVE if f not in list(recent)[-4:]), cands[0])


def fit(text, width=936, top=110, low=60, ratio=.97):
    """가장 긴 줄이 폭에 꽉 차는 글자 크기 — 짧은 제목일수록 크게."""
    lines = re.sub(r"\*\*", "", text or "").split("\n")
    return max(low, min(top, int(width / (max(map(len, lines), default=1) * ratio or 1))))


# ── 글자 도우미 ──
def md(s):
    """줄바꿈 → <br>, **강조** → <b class=hl>."""
    s = html.escape(s or "")
    return re.sub(r"\*\*(.+?)\*\*", r'<b class="hl">\1</b>', s, flags=re.S).replace("\n", "<br>")


LOGO = asset_uri("brand/hotconomy_logo.png")
# 계정별 카드 (2026-11-09 임의 셋팅, 근거는 브랜드기준/*.md). 핫코노미 외 계정은 로고 없이 이름만 넣는다.
BRANDS = {
    "hot": {"name": "핫코노미", "handle": "@hotconomy", "tag": "#핫코노미", "tone": ""},
    "asset": {"name": "자산백배", "handle": "@100x.asset", "tag": "#자산백배", "tone": "뉴스를 내 돈 관리로 옮겨 주는 생활 경제 계정. 친근한 해요체. 독자는 돈 관리를 배우는 20~40대."},
    "bull": {"name": "황소개미", "handle": "@bullant_economy", "tag": "#황소개미", "tone": "시장 뉴스가 말하지 않은 빈칸 하나를 숫자로 짚는 해설 계정. 담담한 존댓말. 독자는 주식 시장을 매일 보는 개인 투자자. 생활 재테크 팁은 쓰지 않는다."},
    "chart": {"name": "차트덕후", "handle": "", "tag": "#차트덕후", "tone": "차트 용어와 읽는 법을 쉽게 풀어 주는 공부 계정. 해요체. 특정 종목의 매수·매도 판단은 쓰지 않는다."},
    "malhee": {"name": "말희아빠", "handle": "@oh_neworld", "tag": "#말희아빠", "tone": "차트와 수급으로 시장 흐름을 짚는 해설 계정. 해요체. 특정 종목의 매수·매도 판단은 쓰지 않는다."},
}
BRAND = BRANDS["hot"]


def set_brand(key):
    global BRAND, LOGO
    BRAND = BRANDS[key]
    if key != "hot":
        LOGO = ""

# 4:5 그대로 올리는 기준으로 꽉 채운다. 폰 업로드에서 ⤢ 를 눌러 4:5로 바꿔야 한다(그대로 1:1이면 위아래 135px가 잘림).
# 프로필 격자는 3:4로 보여 좌우 34px씩 잘리니, 글은 x 44~1036 안에 둔다.
# 쪽 번호는 인스타가 보여 주니 새 폼에는 넣지 않는다. 가장자리 여백은 layout_check 가 safe 로 검사.
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
.b-l{font-size:54px;font-weight:500;line-height:1.5}
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
.row .nm{font-size:54px;font-weight:800;line-height:1.25}
.row .sm{font-size:36px;color:var(--sub);margin-top:6px;line-height:1.35}
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
.pp{position:absolute;left:96px;right:96px;top:96px;bottom:130px;display:flex;flex-direction:column;gap:30px}
.heads{flex:1;display:flex;flex-direction:column;justify-content:space-evenly}
.news{font-size:62px;font-weight:800;line-height:1.3;display:flex;gap:24px;padding-top:26px;border-top:2px solid #222}
.nno{font-family:HSerif,'Noto Serif CJK KR',serif;font-weight:900;color:#d8262b;flex:none}
.news u{text-decoration:none;box-shadow:inset 0 -14px 0 #d8262b55}
.term{font-size:48px;line-height:1.45;padding-top:24px;border-top:2px solid #222}
.term b{color:#1f5fbf}
/* 단계 */
.ui{position:absolute;left:110px;right:110px;background:#f3f4f7;border-radius:36px;padding:44px;box-shadow:0 10px 40px #0001}
.ui .r{background:#fff;border-radius:18px;padding:22px 28px;font-size:36px;margin-bottom:18px;display:flex;gap:18px;align-items:center}
.ui .r.on{outline:5px solid var(--ac);font-weight:800}
.dot{width:46px;height:46px;border-radius:50%;background:var(--ac);color:#fff;font-weight:900;font-size:28px;display:flex;align-items:center;justify-content:center;flex:none}
/* 인사이트 */
.qm{font-size:130px;line-height:1.3;color:#e3262b}
.glow{position:absolute;inset:0;background:radial-gradient(circle at 50% 42%,#3a1416 0,#0b0b0d 60%)}
/* 기본형 */
.hotbg{position:absolute;inset:0;background:radial-gradient(circle at 92% 8%,#7a1418 0,#0b0b0d00 48%),radial-gradient(circle at 5% 100%,#5a2a0a 0,#0b0b0d00 40%)}
.point{position:absolute;left:72px;right:72px;background:#2a0e10;border:3px solid var(--ac);border-radius:28px;padding:30px 40px}
.point .k{font-size:30px;font-weight:800;color:#ff7a1a;margin-bottom:10px}
.point .v{font-size:46px;font-weight:800;line-height:1.35}
/* 배경 사진형: 장마다 글 내용에 맞는 사진을 전체 배경으로 */
.bgph{position:absolute;left:0;top:0;width:1080px;height:1350px;object-fit:cover}
.nophoto{position:absolute;inset:0;background:linear-gradient(160deg,#1c2a44,#0b0b0d)}
.shade{position:absolute;inset:0;background:linear-gradient(180deg,#000000d0 0,#000000b0 26%,#00000050 42%,#00000070 58%,#000000e6 78%,#000000f0 100%)}
.shade.cv{background:linear-gradient(180deg,#00000040 0,#00000000 35%,#000000b0 62%,#000000f0 100%)}
.scene-t{text-shadow:0 2px 14px #000c}
/* 글 길이에 맞춰 아래로 밀리는 묶음 (고정 위치면 제목이 길 때 겹침) */
.stack{position:absolute;left:72px;right:72px;display:flex;flex-direction:column;gap:36px}
.stack .ui{position:relative;left:auto;right:auto;margin:0 38px;top:auto}
.endbox{position:absolute;left:72px;right:72px;top:90px;bottom:170px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:40px}
.endlogo{width:180px;height:180px;border-radius:50%;flex:none}
.endchecks{font-size:48px;font-weight:600;line-height:1.4;display:flex;flex-direction:column;gap:18px;max-width:880px}
.endchecks div{padding-left:58px;text-indent:-58px}
.endkw{font-size:40px;font-weight:700;text-align:center}
.endbox .btns{position:static;align-self:stretch;margin:0 18px;flex:none}
/* 사진 뉴스형: 표지는 사진 전체 + 아래 큰 제목, 본문은 위 사진 + 아래 큰 글 */
.nw-sh{position:absolute;inset:0;background:linear-gradient(180deg,#00000000 0,#00000000 38%,#000000c8 60%,#000000f5 76%,#000 100%)}
.nw-ph{position:absolute;left:0;top:0;width:1080px;height:830px;object-fit:cover;object-position:center 22%}
.nw-fd{position:absolute;left:0;right:0;top:520px;height:320px;background:linear-gradient(180deg,#0b0b0d00,#0b0b0d)}
.nw-box{position:absolute;left:64px;right:64px;bottom:128px;display:flex;flex-direction:column;gap:26px}
.nw-tag{font-size:40px;font-weight:800;color:var(--hl)}
.nw-t{font-weight:900;line-height:1.16;letter-spacing:-2px;text-shadow:0 2px 16px #000a}
.nw-b{font-size:48px;font-weight:600;line-height:1.42;color:#e9e9ee}
.nw-k{font-size:66px;font-weight:800;line-height:1.25;letter-spacing:-1px}
.nw-h{font-weight:900;line-height:1.05;letter-spacing:-4px;color:var(--hl);white-space:nowrap}
/* 세리프 에디토리얼: 제목 + 내용 사진 + 짧은 설명으로 꽉 채움 */
.ed{position:absolute;left:72px;right:72px;top:96px;bottom:124px;display:flex;flex-direction:column;gap:34px;align-items:center;text-align:center}
.ed img{flex:1;min-height:0;width:100%;object-fit:cover;object-position:center 25%;border-radius:18px}
.ed-t{font-family:HSerif,'Noto Serif CJK KR',serif;font-weight:700;line-height:1.2;letter-spacing:-1.5px}
.ed-c{font-size:44px;line-height:1.45;font-weight:500}
/* 글이 짧아도 아래가 비지 않게 가운데로 */
.vc{position:absolute;left:72px;right:72px;top:80px;bottom:130px;display:flex;flex-direction:column;justify-content:center;gap:44px}
/* 마지막 */
.btns{position:absolute;left:90px;right:90px;display:flex;gap:30px}
.btn{flex:1;height:112px;border-radius:60px;display:flex;align-items:center;justify-content:center;font-size:40px;font-weight:800}
.btn.o{border:4px solid var(--fg)}
.btn.f{background:var(--ac);color:#fff}
.disc{position:absolute;left:0;right:0;bottom:110px;text-align:center;font-size:24px;color:var(--sub)}
"""


def foot(n, total, theme_logo=True, page_no=True):
    logo = f'<img src="{LOGO}">' if LOGO and theme_logo else ""
    pn = f'<div class="pn">{n}</div>' if page_no else ""
    return f'<div class="foot">{logo}{BRAND["name"]}<span style="font-weight:500;opacity:.75">{BRAND["handle"]}</span></div>{pn}'


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


def bars_html(items, maxw=430, unit=""):
    """items: [{"label","value","text"(표시값),"hi":bool}]"""
    top = max(abs(i["value"]) for i in items) or 1   # 등락률은 음수도 많다. 길이는 크기로
    rows = []
    for it in items:
        bw = max(8, abs(it["value"]) / top * maxw)
        col = "#ff4d4f" if it.get("hi") else "#5ec4b6"
        rows.append(f'<div style="display:flex;align-items:center;margin-bottom:44px"><div style="width:230px;font-size:42px;'
                    f'font-weight:{800 if it.get("hi") else 500};text-align:right;padding-right:22px">{html.escape(it["label"])}</div>'
                    f'<div style="flex:none;height:92px;width:{bw:.0f}px;background:{col};border-radius:0 8px 8px 0"></div>'
                    f'<div style="font-size:46px;font-weight:900;padding-left:20px;white-space:nowrap;color:{col}">{html.escape(it.get("text", str(it["value"]) + unit))}</div></div>')
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
    """표지 c: title(한 줄 10자 안쪽 2~3줄), chart{"ticker"}(이 사건과 직접 관련된 시세가 있을 때만, 없으면 chart 를 빼면 큰 제목만 나옴). 본문 s: tag, title, text, chart(선택)."""
    tick = "BREAKING NEWS&nbsp;&nbsp;&nbsp;" * 4
    if s is None:
        if not c.get("chart", {}).get("candles"):
            return (f'<div class="glow" style="background:radial-gradient(circle at 50% 48%,#5a1014 0,#0b0b0d 68%)"></div><div class="ticker">{tick}</div><div class="vc center" style="top:120px"><div class="t-xl" '
                    f'style="font-size:{fit(c["title"], top=150, low=70)}px">{md(c["title"])}</div></div>')
        svg, py, px_ = candles_svg(c["chart"]["candles"], 900, 680)
        price = f'<div class="pricebox" style="left:{min(px_ + 60, 820):.0f}px;top:{py + 96 - 30:.0f}px">{html.escape(c.get("price", ""))}</div>' if c.get("price") else ""
        return (f'<div class="ticker">{tick}</div><div style="position:absolute;top:110px;left:20px">{svg}</div>{price}'
                f'<div class="pad center t-xl" style="top:880px;font-size:94px">{md(c["title"])}</div>')
    chart = ""
    if s.get("chart") and len(s.get("text", "")) < 70:   # 글이 길면 차트를 빼서 겹치지 않게
        chart = f'<div style="position:absolute;left:0;top:880px;opacity:.9">{line_svg(s["chart"]["line"], 1080, 330, "#ff2e4d")}</div>'
    head = f'<div class="ticker" style="height:70px;line-height:70px;font-size:38px">{tick}</div>'
    chip = f'<div><span class="chip">{html.escape(s.get("tag", "무슨 일?"))}</span></div>'
    if not chart:   # 차트가 없으면 글을 키워 가운데로 (아래가 비지 않게)
        return (head + f'<div class="vc" style="top:90px;gap:44px">{chip}<div class="t-l" style="font-size:{fit(s["title"], top=108, low=72)}px">{md(s["title"])}</div>'
                f'<div class="b-l" style="font-size:54px;line-height:1.5">{md(s.get("text", ""))}</div></div>')
    return (head + f'<div class="stack" style="top:150px">{chip}'
            f'<div class="t-l">{md(s["title"])}</div><div class="b-l">{md(s.get("text", ""))}</div></div>{chart}')


def f_bignum(c, s, n, t):
    """표지 c: label, number, sub, line(선택). 본문 s: number, title, text."""
    grad = "background:linear-gradient(180deg,#ffd24a,#ff6a1a);-webkit-background-clip:text;color:transparent"
    if s is None:
        line = f'<div style="margin:0 -72px">{line_svg(c["line"], 1080, 280)}</div>' if c.get("line") else ""
        return (f'<div class="vc center"><div class="t-m" style="color:#fff">{md(c.get("label", ""))}</div>'
                f'<div style="font-size:{fit(c["number"], top=240, low=110, ratio=.68)}px;font-weight:900;letter-spacing:-5px;line-height:1.08;{grad}">{html.escape(c["number"])}</div>'
                f'<div class="t-l" style="font-size:{fit(c.get("sub", ""), top=84, low=58)}px">{md(c.get("sub", ""))}</div>{line}</div>')
    return (f'<div class="vc"><div style="font-size:{fit(s["number"], top=210, low=110, ratio=.68)}px;font-weight:900;letter-spacing:-4px;line-height:1.1;{grad}">{html.escape(s["number"])}</div>'
            f'<div class="t-l" style="font-size:{fit(s["title"], top=80, low=60)}px">{md(s["title"])}</div><div class="b-l">{md(s.get("text", ""))}</div></div>')


def f_bars(c, s, n, t):
    """표지 c: title, sub, bars[...]. 본문 s: title, bars 또는 text. 막대가 주인공이라 본문은 2~3장, 막대 없는 장은 1장까지."""
    d = c if s is None else s
    sub = f'<div class="b-m">{md(d["sub"])}</div>' if d.get("sub") else ""
    body = f'<div style="margin-top:24px">{bars_html(d["bars"])}</div>' if d.get("bars") else f'<div class="b-l" style="margin-top:24px">{md(d.get("text", ""))}</div>'
    return f'<div class="vc"><div class="t-l" style="font-size:{fit(d["title"], top=96, low=66)}px">{md(d["title"])}</div>{sub}{body}</div>'


def f_list(c, s, n, t):
    """사실 여러 개를 값과 함께 줄 세울 때. 표지 c: title, sub, count(항목 수 숫자). 본문 s: title, items[{name,sub,value}]. 한 장에 항목을 꼭 2~3개 넣어 본문은 2~3장으로 쓴다(한 장에 1개면 비어 보임). value 는 숫자나 짧은 값, 항목과 값은 재료에 있는 것만 쓴다."""
    if s is None:
        return (f'<div class="vc"><div class="b-m" style="font-size:48px">{md(c.get("sub", ""))}</div>'
                f'<div style="font-size:280px;font-weight:900;color:#e3262b;line-height:1.35;letter-spacing:-8px">{html.escape(str(c.get("count", "")))}</div>'
                f'<div class="t-xl" style="font-size:{fit(c["title"], top=124, low=84)}px">{md(c["title"])}</div></div>')
    rows = "".join(f'<div class="row"><div class="ico">{it.get("icon") or i}</div><div><div class="nm">{md(it["name"])}</div>'
                   f'<div class="sm">{md(it.get("sub", ""))}</div></div><div class="val">{html.escape(it.get("value", ""))}</div></div>' for i, it in enumerate(s["items"][:3], 1))
    return f'<div class="vc" style="gap:70px"><div class="t-l" style="font-size:{fit(s["title"], top=88, low=62)}px">{md(s["title"])}</div><div>{rows}</div></div>'


def f_photo(c, s, n, t):
    """표지 c: image(사진 경로 또는 {"line"/"candles"}), title. 본문 s: image, text(한두 줄)."""
    d = c if s is None else s
    words = d.get("title") or d.get("text", "")
    size = (90 if len(words) < 24 else 68) if s is None else (64 if len(words) < 34 else 46)
    return (f'{img_or_chart(d.get("image"))}<div class="fade"></div>'
            f'<div class="pad center" style="bottom:120px;font-size:{size}px;font-weight:900;line-height:1.22;letter-spacing:-1px">{md(d.get("title") or d.get("text", ""))}</div>')


def f_scene(c, s, n, t):
    """표지 c: tag, title, bg. 본문 s: title, text, bg. 차트 칸 없음. 사진이 주인공이라 글은 짧게: title 20자 안쪽, text 60자 안쪽 한 메시지, 끝 문장은 다음 장이 궁금하게.
    bg = 그 장 내용과 맞는 사진 영어 검색어 2~4단어, 글에 나온 고유한 제품, 회사, 장소 이름으로 (예: 'Tesla Model 3', 'Riga old town', 'silicon wafer'). 'city at night', 'car steering wheel' 같은 일반어는 엉뚱한 사진이 나오니 쓰지 않는다. 코드가 위키미디어에서 실제 사진을 찾아 넣는다. 인물 이름은 그 사람 이야기일 때만, 글자가 많을 만한 것(포스터, 도표, 발표 자료)은 피한다."""
    d = c if s is None else s
    bg = f'<img class="bgph" src="{html.escape(d["photo"])}">' if d.get("photo") else '<div class="nophoto"></div>'
    if s is None:
        tag = f'<div class="pad" style="top:90px"><span class="chip">{html.escape(c.get("tag", ""))}</span></div>' if c.get("tag") else ""
        return f'{bg}<div class="shade cv"></div>{tag}<div class="pad t-xl scene-t" style="bottom:190px;font-size:92px">{md(c["title"])}</div>'
    return (f'{bg}<div class="shade"></div><div class="pad t-m scene-t" style="top:120px;font-size:68px">{md(s["title"])}</div>'
            f'<div class="pad b-l scene-t" style="bottom:190px;font-weight:600">{md(s.get("text", ""))}</div>')


def f_story(c, s, n, t):
    """표지 c: label, title. 본문 s: narration(상자), say(말풍선)."""
    m = f'<img class="mascot" src="{LOGO}" style="width:460px;height:460px;left:310px;top:760px">' if LOGO else ""
    if s is None:
        return (f'<div class="pad" style="top:120px;font-size:30px;color:#888">{md(c.get("label", "핫코노미 썰"))}</div>'
                f'<div class="pad t-l" style="top:180px;color:#111">{md(c["title"])}</div>{m}')
    nar = f'<div class="pad" style="top:110px"><span class="nar">{md(s.get("narration", ""))}</span></div>' if s.get("narration") else ""
    return nar + f'<div class="bub" style="left:110px;right:110px;top:380px">{md(s.get("say", ""))}</div>{m}'


def f_editorial(c, s, n, t):
    """표지 c: kicker, title, bg, caption(한 줄). 본문 s: title, bg, caption(한두 줄, 50자 안쪽). 일상, 소비, 트렌드처럼 '내 얘기'인 소재.
    제목은 한 문장의 관찰('평범한 것들이 사치가 됐다'), bg 는 글 내용을 그대로 보여 주는 사물, 장소, 인물. 고유명사 영어 검색어 2~4단어, 일반어는 엉뚱한 사진이 나오니 쓰지 않는다."""
    d = c if s is None else s
    kick = f'<div style="font-size:30px;letter-spacing:8px;color:var(--sub)">{html.escape(c.get("kicker", "HOTCONOMY"))}</div>' if s is None and c.get("kicker") else ""
    v = d.get("image") if isinstance(d.get("image"), dict) else {}   # 옛 초안: 시세 선 차트
    line = d.get("line") or v.get("line") or [round(x[3], 2) for x in v.get("candles", [])]
    if d.get("photo"):
        pic = f'<img src="{html.escape(d["photo"])}">'
    elif isinstance(d.get("image"), str) and d.get("image"):
        pic = f'<img src="{d["image"] if "://" in d["image"] else asset_uri(d["image"])}">'
    elif line:
        pic = f'<div style="flex:1;display:flex;align-items:center">{line_svg(line, 936, 460, "#d8262b")}</div>'
    else:
        pic = ""
    size = fit(d["title"], top=104 if s is None else 88, low=62)
    if not pic:   # 사진을 못 찾은 장: 아래가 비지 않게 가운데로
        return (f'<div class="ed" style="justify-content:center;gap:64px">{kick}<div class="ed-t" style="font-size:{min(size + 14, 118)}px">{md(d["title"])}</div>'
                + (f'<div class="ed-c" style="font-size:50px">{md(d.get("caption", ""))}</div>' if d.get("caption") else "") + "</div>")
    cap = f'<div class="ed-c">{md(d.get("caption", ""))}</div>' if d.get("caption") else ""
    return f'<div class="ed">{kick}<div class="ed-t" style="font-size:{size}px">{md(d["title"])}</div>{pic}{cap}</div>'


def f_news(c, s, n, t):
    """표지 c: tag(짧은 분류, 선택), title, bg. 본문 s: title, text, bg. 뉴스, 이슈, 인물, 기업 소재의 기본 폼.
    표지 title: 주제 요약이 아니라 사건 + 구체적인 사람, 금액, 반전. 2~3줄, 줄당 7~13자, 강조 **한 곳**. 예: '인텔 하루 만에\\n**시총 30% 증발**'
    본문 title: 한 장에 사실 하나, 2줄 안쪽. text: 60자 안쪽(없어도 됨), 끝 문장은 다음 장이 궁금하게.
    bg: 영어 사진 검색어 2~4단어. 표지는 그 사건의 핵심 인물 이름(예: 'Jensen Huang') 또는 고유한 제품, 회사 건물. 사람 얼굴이 있으면 가장 좋다. 일반어 금지, 글자가 많을 만한 것 금지.
    표지 bg_alt: 인물 사진이 없을 때 대신 쓸 회사 제품, 건물 검색어. 본문은 모든 장에 bg 를 넣는다. 주가 움직임을 말하는 장 하나만 bg 대신 chart: {"ticker": "시세 코드"} (한 글에 1장까지)."""
    d = c if s is None else s
    if s is None:
        bg = f'<img class="bgph" src="{html.escape(d["photo"])}" style="object-position:center 18%">' if d.get("photo") else '<div class="nophoto"></div>'
        tag = f'<div class="nw-tag">{html.escape(c["tag"])}</div>' if c.get("tag") else ""
        return (f'{bg}<div class="nw-sh"></div><div class="nw-box">{tag}'
                f'<div class="nw-t" style="font-size:{fit(c["title"], 952, 124, 72)}px">{md(c["title"])}</div></div>')
    text = f'<div class="nw-b">{md(s["text"])}</div>' if s.get("text") else ""
    line = (s.get("chart") or {}).get("line")
    if line:   # 주가 장: 사진 자리에 실제 시세 (한국식: 오르면 빨강, 내리면 파랑)
        color = "#ff2e4d" if line[-1] >= line[0] else "#3d8bff"
        return (f'<div class="nophoto"></div><div style="position:absolute;left:0;top:110px">{line_svg(line, 1080, 620, color, False)}</div><div class="nw-box">'
                f'<div class="nw-t" style="font-size:{fit(s["title"], 952, 92, 62)}px">{md(s["title"])}</div>{text}</div>')
    if not d.get("photo"):   # 사진을 끝내 못 찾은 장: 표지 사진을 어둡게 깔고 강조 단어를 아주 크게
        back = f'<img class="bgph" src="{html.escape(c["photo"])}" style="filter:blur(28px) brightness(.24);transform:scale(1.1)">' if c.get("photo") else '<div class="nophoto"></div>'
        m = re.search(r"\*\*(.+?)\*\*", s["title"], re.S)
        if not m:
            return f'{back}<div class="vc"><div class="nw-t" style="font-size:{fit(s["title"], 936, 110, 66)}px">{md(s["title"])}</div>{text.replace("nw-b", "b-l")}</div>'
        before, hero, after = (" ".join(x.split()) for x in (s["title"][:m.start()], m[1], s["title"][m.end():]))
        size = fit(hero, 936, 216, 96, .72 if hero.isascii() else .97)
        return (f'{back}<div class="vc"><div class="nw-k">{md(before)}</div><div class="nw-h" style="font-size:{size}px">{html.escape(hero)}</div>'
                + (f'<div class="nw-k">{md(after)}</div>' if after else "") + f'{text.replace("nw-b", "b-l")}</div>')
    bg = f'<img class="nw-ph" src="{html.escape(d["photo"])}">'
    return (f'{bg}<div class="nw-fd"></div><div class="nw-box">'
            f'<div class="nw-t" style="font-size:{fit(s["title"], 952, 92, 62)}px">{md(s["title"])}</div>{text}</div>')


def f_paper(c, s, n, t):
    """신문 1면처럼 사실 3개를 한 번에. 표지 c: date, headlines[3](재료의 사실 3개, 한 줄 20자 안쪽, **강조**는 밑줄). 본문 s: title, terms[{term,desc}](용어 풀이) 또는 headlines. 한 장에 꼭 2~3개 넣는다(1개면 비어 보임)."""
    fr = '<div class="frame"></div>'
    if s is None:
        heads = "".join(f'<div class="news"><span class="nno">{i}</span><span>{md(h).replace("<b class=\"hl\">", "<u>").replace("</b>", "</u>")}</span></div>' for i, h in enumerate(c["headlines"][:3], 1))
        return (fr + f'<div class="pp"><div class="center" style="font-size:38px;font-weight:700">{html.escape(c.get("date", ""))}</div>'
                f'<div class="center"><span class="mast">{BRAND["name"]} 경제신문</span></div><div class="heads">{heads}</div></div>')
    if s.get("terms"):
        body = "".join(f'<div class="term"><b>{html.escape(x["term"])}</b><br>{md(x["desc"])}</div>' for x in s["terms"])
    else:
        body = "".join(f'<div class="term">{md(h)}</div>' for h in s.get("headlines", []))
    return fr + f'<div class="pp"><div class="center" style="font-size:{fit(s["title"], 860, 72, 52)}px;font-weight:800">[{md(s["title"])}]</div><div class="heads">{body}</div></div>'


def f_steps(c, s, n, t):
    """표지 c: title, sub, steps(단계 수). 본문 s: step, title, ui[행 텍스트], on(강조할 행 번호), tip."""
    if s is None:
        dots = "".join(f'<div class="dot" style="width:90px;height:90px;font-size:44px">{i}</div>' for i in range(1, c.get("steps", 4) + 1))
        return (f'<div class="pad t-xl" style="top:230px;color:var(--fg)">{md(c["title"])}</div>'
                f'<div class="pad b-m" style="top:640px;font-size:44px">{md(c.get("sub", ""))}</div>'
                f'<div class="pad" style="top:860px;display:flex;gap:30px">{dots}</div>')
    rows = "".join(f'<div class="r{" on" if i == s.get("on") else ""}"><span class="dot">{i}</span>{md(r)}</div>' for i, r in enumerate(s.get("ui", []), 1))
    return (f'<div class="stack" style="top:100px"><div><span class="chip">STEP {s["step"]}</span></div>'
            f'<div class="t-m">{md(s["title"])}</div><div class="ui">{rows}</div>'
            f'<div class="center" style="font-size:{48 if len(s.get("tip", "")) < 40 else 38}px;font-weight:700;line-height:1.45">{md(s.get("tip", ""))}</div></div>')


def f_quote(c, s, n, t):
    """누군가의 한마디가 사건일 때. 표지 c: label, quote, by. 본문 s: quote, by(선택), text(선택, 왜 중요한지 60자 안쪽). quote 는 재료에 그대로 나온 실제 발언(누가 한 말의 문장)만 쓴다. 지어내거나 고쳐 쓰면 안 되고, 수치나 기사 제목은 발언이 아니며, 장마다 다른 발언을 쓴다. 발언이 없거나 하나뿐이면 이 폼을 고르지 않는다."""
    d = c if s is None else s
    lab = f'<div class="center" style="font-size:34px;color:var(--sub);letter-spacing:6px">{html.escape(c.get("label", "INSIGHT"))}</div>' if s is None else ""
    by = f'<div class="center" style="font-size:42px;color:var(--sub)">{html.escape(d.get("by", ""))}</div>' if d.get("by") else ""
    text = f'<div class="center b-l" style="color:var(--fg)">{md(s.get("text", ""))}</div>' if s and s.get("text") else ""
    words = len(re.sub(r"\*\*", "", d["quote"]))
    size = (92 if words < 34 else 76) if s is None else (76 if words < 34 else 62)
    return ('<div class="glow"></div><div class="vc" style="gap:44px">' + lab + '<div class="center serif qm">“</div>'
            f'<div class="center serif" style="font-size:{size}px;font-weight:700;line-height:1.4">{md(d["quote"])}</div>{by}{text}</div>')


def f_hot(c, s, n, t):
    """표지 c: tag, title, sub. 본문 s: title, text, point."""
    bg = '<div class="hotbg"></div>'
    if s is None:
        line = f'<div style="position:absolute;left:0;top:930px;opacity:.9">{line_svg([3, 4, 3.6, 5, 4.6, 6.4, 6, 8.2], 1080, 300, "#ff3b2e", False)}</div>'
        return (bg + line + f'<div class="stack" style="top:150px"><div><span class="chip">{html.escape(c.get("tag", "경제 기초"))}</span></div>'
                f'<div class="t-xl" style="font-size:{112 if len(c["title"]) < 18 else 88}px">{md(c["title"])}</div>'
                f'<div class="b-m" style="font-size:{44 if len(c.get("sub", "")) < 40 else 38}px">{md(c.get("sub", ""))}</div></div>')
    pt = f'<div class="point" style="top:930px"><div class="k">🔥 핵심</div><div class="v">{md(s["point"])}</div></div>' if s.get("point") else ""
    return (bg + f'<div class="stack" style="top:130px"><div style="font-size:130px;font-weight:900;color:#ff7a1a;line-height:1">{n - 1:02d}</div>'
            f'<div class="t-l">{md(s["title"])}</div>'
            f'<div class="b-l" style="font-size:{52 if len(s.get("text", "")) < 50 else 44}px">{md(s.get("text", ""))}</div></div>{pt}')


FORMS = {"breaking": (f_breaking, "brk"), "bignum": (f_bignum, ""), "bars": (f_bars, "navy"), "list": (f_list, ""),
         "photo": (f_photo, ""), "story": (f_story, "white"), "editorial": (f_editorial, "light"), "paper": (f_paper, "paper"),
         "steps": (f_steps, "white"), "quote": (f_quote, ""), "hot": (f_hot, ""), "scene": (f_scene, ""), "news": (f_news, "")}


def end_slide(e, n, theme):
    """마지막 장 e: title, checks[...], keyword(댓글 유도 단어, 선택), gift[...](선택: 댓글 단 사람에게 DM으로 줄 자료 2~3개).
    gift 가 있으면 체크 대신 '드리는 것' 목록을 보여 주고, 댓글 줄도 'DM으로 보내드려요'로 바뀐다. 위에서 아래로 차례로 쌓아서 제목이 두 줄이어도 안 겹침."""
    logo = f'<img class="endlogo" src="{LOGO}">' if LOGO else ""
    gift = e.get("gift") or []
    checks = "".join(f"<div>{'🎁' if gift else '✓'}&nbsp; {md(x)}</div>" for x in (gift or e.get("checks", [])))
    kw = ""
    if e.get("keyword"):
        kw = (f'<div class="endkw">💬 댓글에 <b class="hl">\'{html.escape(e["keyword"])}\'</b> 남기면 DM으로 보내드려요</div>' if gift else
              f'<div class="endkw">💬 궁금한 점은 댓글에 <b class="hl">\'{html.escape(e["keyword"])}\'</b> 남겨 주세요</div>')
    return (f'<div class="endbox">{logo}<div class="center t-l" style="font-size:{fit(e.get("title", ""), top=80, low=58)}px">{md(e.get("title", "정리하면"))}</div>'
            f'<div class="endchecks">{checks}</div>{kw}'
            f'<div class="btns"><div class="btn o">🔖 저장해두기</div><div class="btn f">팔로우 하기</div></div></div>'
            f'<div class="disc">{BRAND["handle"] or BRAND["name"]} | {DISCLAIMER}</div>')


def make(post, out_dir, name, demo=False):
    css, slides = _styled(post, demo)
    return render(slides, out_dir, name, css)


def font_css(font):
    """제목 글꼴 바꾸기. 본문은 읽기 쉽게 기본 고딕 그대로. noto 또는 빈 값이면 폼 기본 글꼴."""
    fam = FONTS.get(font, {}).get("family")
    if not fam:
        return ""
    return (f"\n.s,.serif,.ed-t,.mast,.nno{{font-family:{fam},HSans,'Noto Sans CJK KR',sans-serif}}"
            f"\n.b-l,.b-m,.nw-b,.ed-c,.endchecks,.endkw,.btn,.disc,.foot,.chip,.nw-tag,.row .sm,.pricebox{{font-family:HSans,'Noto Sans CJK KR',sans-serif}}")


def _styled(post, demo=False):
    """대표가 캔바에서 2번 넘게 똑같이 바꾼 색은 이 폼에 그대로 적용 (publish/card_learn.py). 고른 제목 글꼴도 여기서."""
    from publish.card_learn import restyle
    css, slides = restyle(post["form"], CSS, slides_of(post, demo))
    return css + font_css(post.get("font")), slides


def make_canva(post, path):
    """캔바 수정용 사본 PPTX (publish/canva_copy.py)."""
    from publish.canva_copy import build_pptx
    css, slides = _styled(post)
    return build_pptx(slides, css, path)


def slides_of(post, demo=False):
    fn, theme = FORMS[post["form"]]
    total = 1 + len(post.get("slides", [])) + 1
    tag = '<div class="demo">예시 · 발행 금지</div>' if demo else ""
    page_no = post["form"] not in ACTIVE
    slides = [f'<div class="s {theme}">{tag}{fn(post["cover"], None, 1, total)}{foot(1, total, page_no=page_no)}</div>']
    for i, s in enumerate(post.get("slides", []), 2):
        slides.append(f'<div class="s {theme}">{tag}{fn(post["cover"], s, i, total)}{foot(i, total, page_no=page_no)}</div>')
    slides.append(f'<div class="s {theme}">{tag}{end_slide(post.get("end", {}), total, theme)}</div>')
    return slides


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
    "news": {"cover": {"tag": "속보", "title": "유럽에서 FSD 승인\n**10번째** 국가 나왔다"},
             "slides": [{"title": "발트 3국이\n**모두** 들어갔다", "text": "라트비아가 승인하면서 발트 3국이 모두 포함됐다는 소식입니다. (예시)"},
                        {"title": "테슬라 주가\n**+12.4%**", "text": "승인 소식에 오른 폭입니다. (예시)", "chart": {"line": [100, 98, 103, 101, 108, 112]}},
                        {"title": "유럽 승인 국가\n**10곳** 돌파", "text": "사진을 못 찾은 장의 화면입니다. (예시)"}],
             "end": {"title": "정리하면", "checks": ["사진 없으면 그라데이션", "글은 짧게", "장마다 다른 사진"], "keyword": "테슬라"}},
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
    "scene": {"cover": {"tag": "테슬라", "title": "유럽에서 FSD 승인\n**10번째** 국가 나왔다"},
              "slides": [{"title": "발트 3국이\n**모두** 들어갔다", "text": "라트비아가 승인하면서 발트 3국이 모두 포함됐다는 소식입니다. (예시)"}],
              "end": {"title": "정리하면", "checks": ["사진 없으면 그라데이션", "글은 짧게", "장마다 다른 사진"], "keyword": "테슬라"}},
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
