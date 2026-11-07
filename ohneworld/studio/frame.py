"""오뉴월드 릴스 틀 (한 곳에서만 정의). 오뉴월드 제작기(studio/reel.py)와 영상 연구소 '오뉴월드형'(reels/formats.py)이 같이 쓴다.

틀 (2026-11-06 실제 릴스 확인): 바탕 검정, 맨 위 빨간 띠, 오른쪽 위 날짜, 굵은 흰 제목(빨간 밑줄), 가운데 고정 칸,
아래 흰 말풍선 자막과 고정 질문. 영상 내내 칸 위치가 같다. 칸 안의 차트·사진은 자르거나 보정하지 않는다.
강조는 빨간 동그라미·화살표·손글씨(Gaegu) 라벨.

css(scope, body): scope 는 선택자 앞에 붙는 말 ("" 이면 오뉴월드 제작기 그대로, "body.fmt-ohne " 이면 연구소 형식),
body 는 body 자리 선택자.
"""
import html
import pathlib

WIN_TOP, WIN_H = 520, 830          # 가운데 칸 (화면 폭 전체)
CAP_Y = 1445                        # 말풍선 자막 가운데 높이
RED = "#E3141B"
DARK_BG = "repeating-conic-gradient(from 0deg at 50% 50%,rgba(255,170,60,.13) 0 6deg,transparent 6deg 15deg),radial-gradient(circle at 50% 50%,#3a1606 0%,#120704 55%,#050302 100%)"   # 글자 장면 바탕
HAND_FONT = pathlib.Path(__file__).resolve().parent.parent / "fonts" / "Gaegu-Bold.ttf"

_FRAME = """
{B}{{word-break:keep-all;background:#000!important}}
{S}#date{{position:absolute;right:70px;top:300px;font-size:42px;font-weight:800;color:#fff;z-index:4;letter-spacing:-1px}}
{S}#rtitle,{S}#rq{{position:absolute;left:30px;right:30px;text-align:center;z-index:4;color:#fff;font-weight:900;letter-spacing:-3px;line-height:1.1;white-space:nowrap}}
{S}#rtitle{{top:362px}}{S}#rq{{top:1515px}}
{S}#rtitle span,{S}#rq span{{display:inline-block;padding:0 14px 6px;background:linear-gradient(transparent 72%,{RED} 72%,{RED} 96%,transparent 96%);text-shadow:0 5px 0 #000,0 0 18px rgba(0,0,0,.9)}}
{S}section{{top:{WIN_TOP}px;height:{WIN_H}px;left:0;right:0;z-index:2;overflow:hidden;justify-content:center;align-items:center;gap:20px}}
{S}#cap{{top:{CAP_TOP}px;height:110px;left:60px;right:60px;z-index:4;font-size:44px;line-height:1.2}}
{S}#cap>div{{background:#fff;color:#111;padding:14px 34px;border-radius:22px;text-shadow:none;font-weight:800;border:3px solid #111}}
{S}#cap em{{color:{RED};font-style:normal}}
{S}#bar{{background:{RED};height:10px;z-index:6}}
{S}.hand{{font-family:Hand,HSans,sans-serif;color:{RED}}}
"""


def font_face():
    return f"@font-face{{font-family:Hand;src:url('{HAND_FONT.as_uri()}');font-weight:100 900}}" if HAND_FONT.exists() else ""


def css(scope="", body="body"):
    return _FRAME.format(S=scope, B=body, RED=RED, WIN_TOP=WIN_TOP, WIN_H=WIN_H, CAP_TOP=CAP_Y - 50)


def fit(word, base, width=1000):
    return min(base, int(width / max(1, sum(1 if ord(c) > 255 else .62 for c in word))))


def top_html(date, title, question, q_min=None):
    """날짜·제목·고정 질문 (자리는 css 가 정한다). 자막(#cap)·칸(section)은 각 제작기가 넣는다.
    q_min: 질문이 길 때 이 크기 밑으로 줄이지 않고 두 줄로 (오뉴월드 제작기는 짧은 질문이라 쓰지 않음)."""
    e = html.escape
    qs = fit(question or "", 92)
    wrap = ""
    if q_min and qs < q_min:
        qs, wrap = q_min, ";white-space:normal;line-height:1.25"
    return (f'<div id="date">{e(date or "")}</div>'
            f'<div id="rtitle" style="font-size:{fit(title or "", 104)}px"><span>{e(title or "")}</span></div>'
            f'<div id="rq" style="font-size:{qs}px{wrap}"><span{' style="display:inline;-webkit-box-decoration-break:clone;box-decoration-break:clone"' if wrap else ''}>{e(question or "")}</span></div>')
