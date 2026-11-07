"""차트 위 '포인트' (오뉴월드 방식): 차트 일부를 잘라 확대하고 빨간 동그라미·화살표·숫자 라벨·별을 얹는다.

사용자 결정(2026-11-06): 오뉴월드처럼 잘라서 표시한다. 차트 파일 자체는 바꾸지 않고, 자르기와 표시는 그 위에 얹는 층이다.
- 카드 JPG·릴스: 화면에 그려서 굽는다
- 캔바 PPTX: 차트는 원본 그림 + 자르기 설정, 표시는 캔바에서 고칠 수 있는 도형·글상자

표시 위치는 Claude 가 칸 번호를 그린 사본을 보고 정한다. 결과는 재료 폴더의 차트표시.json 에 남아 사람이 고칠 수 있다.
"""
import json
import pathlib
import re
import tempfile
from typing import Literal

from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel

from studio import facts
from studio.paths import CONFIG

RED, BLUE, BLACK = "#E5131B", "#1D5FD1", "#111111"
COLORS = {"red": RED, "blue": BLUE, "black": BLACK}


class Mark(BaseModel):
    kind: Literal["circle", "arrow", "label", "star", "xmark"]
    x: float                  # 원본 차트 기준 0~1 (왼쪽→오른쪽)
    y: float                  # 0~1 (위→아래)
    x2: float = 0             # arrow: 화살촉 끝
    y2: float = 0
    r: float = 0.06           # circle: 반지름 (차트 폭 기준)
    text: str = ""            # label: 짧은 글 ("-70%", "중요 자리")
    color: Literal["red", "blue", "black"] = "red"


class Plan(BaseModel):
    x0: float = 0             # 자를 곳 (0~1). 오뉴월드는 중요한 구간을 잘라 확대한다
    y0: float = 0
    x1: float = 1
    y1: float = 1
    marks: list[Mark] = []
    why: str = ""


PROMPT = """오뉴월드(@oh_neworld) 카드뉴스 디자이너입니다. 블로그 차트 위에 '포인트'를 얹습니다.
그림에는 위치를 재기 쉽게 빨간 칸(0~10)이 그려져 있습니다. 좌표는 0~1 (칸 번호 ÷ 10) 로 씁니다. 원본 차트에는 칸이 없습니다.

할 일:
1. 자를 곳(x0,y0,x1,y1): 이 장면에서 보여 줄 구간을 넉넉히 남기고 자릅니다. 위쪽 도구 막대와 아래 거래량 막대가 필요 없으면 뺍니다. 폭은 전체의 50% 이상.
2. 표시(marks) 2~4개. 자를 곳 안에만 둡니다.
   - circle: 가장 중요한 자리(급락 지점, 지지 구간 접촉 등)에 빨간 동그라미 1개
   - arrow: 동그라미 쪽을 가리키는 빨간 화살표 (x,y 시작 → x2,y2 끝)
   - label: 비스듬한 굵은 짧은 글 1개 (8자 이내). 숫자는 [자료]에 있는 것만
   - star: 강조 별 (선택)
   - xmark: 막힌 자리 X 표시 (선택)
3. 원작자가 이미 그린 선·글은 가리지 않습니다. 캔들 위를 정확히 가리킵니다.

[장면 설명]
{context}

[자료 숫자]
{nums}

마지막에 JSON 하나만 씁니다:
{{"x0":..,"y0":..,"x1":..,"y1":..,"marks":[{{"kind":"circle","x":..,"y":..,"r":..,"color":"red"}}, {{"kind":"arrow","x":..,"y":..,"x2":..,"y2":..,"color":"red"}}, {{"kind":"label","x":..,"y":..,"text":"..","color":"red"}}],"why":"한 줄"}}"""


def grid_copy(src, out):
    """칸 번호를 그린 사본 (Claude 가 위치를 재는 용도, 원본은 그대로)."""
    im = Image.open(src).convert("RGB")
    w, h = im.size
    d = ImageDraw.Draw(im)
    try:
        f = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", max(14, w // 50))
    except OSError:
        f = ImageFont.load_default()
    for i in range(11):
        x, y = round(i * (w - 1) / 10), round(i * (h - 1) / 10)
        d.line([(x, 0), (x, h)], fill=(255, 0, 0), width=1)
        d.line([(0, y), (w, y)], fill=(255, 0, 0), width=1)
        d.text((x + 3, 3), str(i), fill=(255, 0, 0), font=f)
        d.text((3, y + 3), str(i), fill=(255, 0, 0), font=f)
    im.save(out)
    return out


def clamp(p):
    p.x0, p.y0 = max(0, min(p.x0, .9)), max(0, min(p.y0, .9))
    p.x1, p.y1 = max(p.x0 + .1, min(p.x1, 1)), max(p.y0 + .1, min(p.y1, 1))
    if p.x1 - p.x0 < .5:
        p.x0, p.x1 = max(0, (p.x0 + p.x1) / 2 - .25), min(1, (p.x0 + p.x1) / 2 + .25)
    keep = []
    for m in p.marks:
        if p.x0 <= m.x <= p.x1 and p.y0 <= m.y <= p.y1:
            keep.append(m)
    p.marks = keep[:5]
    return p


def plan(chart, context, source_nums):
    import llm
    with tempfile.TemporaryDirectory() as tmp:
        g = grid_copy(chart, pathlib.Path(tmp) / "grid.png")
        text = llm.look(CONFIG["model"], PROMPT.format(context=context, nums=", ".join(sorted(source_nums))[:600]), str(g))
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("차트 표시 답에서 JSON 을 찾지 못함")
    p = clamp(Plan.model_validate_json(m.group(0)))
    for mk in p.marks:   # 라벨 숫자도 자료에 있어야 한다
        if mk.kind == "label" and facts.unknown_numbers(mk.text, source_nums):
            mk.text = ""
    p.marks = [mk for mk in p.marks if not (mk.kind == "label" and not mk.text)]
    return p


def load_or_make(folder, charts, contexts, source_nums, log=print):
    """재료 폴더의 차트표시.json 을 쓰고, 없는 차트만 새로 정한다."""
    f = pathlib.Path(folder) / "차트표시.json"
    saved = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    out = {}
    for name, path in charts.items():
        if name in saved:
            out[name] = Plan.model_validate(saved[name])
            continue
        try:
            out[name] = plan(path, contexts.get(name, ""), source_nums)
            log(f"차트 표시 정함: {name} ({out[name].why})")
        except Exception as e:   # 표시는 덤이라 실패해도 원본 전체로 간다
            log(f"차트 표시 실패, 원본 전체로: {name} ({type(e).__name__})")
            out[name] = Plan()
    f.write_text(json.dumps({k: v.model_dump() for k, v in out.items()}, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


# ── 그리기 ──
def box_size(img_size, p, max_w, max_h):
    """잘라 낸 부분을 비율 그대로 칸에 맞춘 크기."""
    iw, ih = img_size
    cw, ch = (p.x1 - p.x0) * iw, (p.y1 - p.y0) * ih
    s = min(max_w / cw, max_h / ch)
    return round(cw * s), round(ch * s)


def _xy(p, x, y, w, h):
    return (x - p.x0) / (p.x1 - p.x0) * w, (y - p.y0) / (p.y1 - p.y0) * h


def html(path, img_size, p, w, h, anim=False):
    """잘라서 확대한 차트 + SVG 표시. data-keep/data-crop 은 PPTX 용."""
    iw, ih = img_size
    sx, sy = w / ((p.x1 - p.x0) * iw), h / ((p.y1 - p.y0) * ih)
    img = (f'<img src="{pathlib.Path(path).as_uri()}" style="position:absolute;left:{-p.x0 * iw * sx:.1f}px;top:{-p.y0 * ih * sy:.1f}px;'
           f'width:{iw * sx:.1f}px;height:{ih * sy:.1f}px;max-width:none">')
    return (f'<div class="cwrap" data-keep="{path}" data-crop="{p.x0},{p.y0},{p.x1},{p.y1}" style="position:relative;overflow:visible;width:{w}px;height:{h}px;flex:none">'
            f'<div style="position:absolute;inset:0;overflow:hidden;background:#fff;box-shadow:0 2px 12px rgba(0,0,0,.14)">{img}</div>{svg(p, w, h, anim)}</div>')


def svg(p, w, h, anim=False):
    parts = []
    for i, m in enumerate(p.marks):
        c = COLORS[m.color]
        x, y = _xy(p, m.x, m.y, w, h)
        cls = f' class="mk" data-i="{i}" pathLength="1"' if anim else ""
        if m.kind == "circle":
            r = max(26, m.r / (p.x1 - p.x0) * w)
            parts.append(f'<ellipse{cls} cx="{x:.0f}" cy="{y:.0f}" rx="{r * 1.08:.0f}" ry="{r * .92:.0f}" transform="rotate(-8 {x:.0f} {y:.0f})" fill="none" stroke="{c}" stroke-width="9" stroke-linecap="round"/>')
        elif m.kind == "arrow":
            x2, y2 = _xy(p, m.x2, m.y2, w, h)
            mx, my = (x + x2) / 2 + (y2 - y) * .25, (y + y2) / 2 - (x2 - x) * .25
            parts.append(f'<path{cls} d="M{x:.0f},{y:.0f} Q{mx:.0f},{my:.0f} {x2:.0f},{y2:.0f}" fill="none" stroke="{c}" stroke-width="9" stroke-linecap="round" marker-end="url(#ah{m.color})"/>')
        elif m.kind == "label":
            half = max(46, w // 13) * len(m.text) * .32   # 칸 밖으로 잘리지 않게
            x = min(max(x, half + 10), w - half - 10)
            parts.append(f'<text{" class=mkt" if anim else ""} data-i="{i}" x="{x:.0f}" y="{y:.0f}" transform="rotate(-8 {x:.0f} {y:.0f})" font-family="Hand" font-size="{max(46, w // 13)}" font-weight="700" letter-spacing="-3" fill="{c}" stroke="{c}" stroke-width="2" text-anchor="middle" dominant-baseline="middle">{facts_escape(m.text)}</text>')
        elif m.kind == "star":
            s = max(22, w // 30)
            pts = " ".join(f"{x + s * (1 if k % 2 == 0 else .45) * __import__('math').sin(k * 3.14159 / 5):.0f},{y - s * (1 if k % 2 == 0 else .45) * __import__('math').cos(k * 3.14159 / 5):.0f}" for k in range(10))
            parts.append(f'<polygon{" class=mkt" if anim else ""} data-i="{i}" points="{pts}" fill="#FFD23A" stroke="{RED}" stroke-width="4"/>')
        elif m.kind == "xmark":
            s = max(18, w // 40)
            parts.append(f'<path{cls} d="M{x - s:.0f},{y - s:.0f} L{x + s:.0f},{y + s:.0f} M{x + s:.0f},{y - s:.0f} L{x - s:.0f},{y + s:.0f}" stroke="{c}" stroke-width="8" stroke-linecap="round"/>')
    defs = "".join(f'<marker id="ah{k}" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="4" markerHeight="4" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="{v}"/></marker>' for k, v in COLORS.items())
    return f'<svg data-mark="1" width="{w}" height="{h}" style="position:absolute;left:0;top:0;overflow:visible"><defs>{defs}</defs>{"".join(parts)}</svg>'


def facts_escape(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── 캔바 PPTX: 고칠 수 있는 도형 ──
def pptx_marks(slide, p, left, top, w, h, px):
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
    from pptx.oxml.ns import qn
    from pptx.util import Pt
    rgb = lambda c: RGBColor.from_string(COLORS[c][1:])
    for m in p.marks:
        x, y = _xy(p, m.x, m.y, w, h)
        x, y = x + left, y + top
        if m.kind == "circle":
            r = max(26, m.r / (p.x1 - p.x0) * w)
            s = slide.shapes.add_shape(MSO_SHAPE.OVAL, px(x - r * 1.08), px(y - r * .92), px(r * 2.16), px(r * 1.84))
            s.fill.background()
            s.line.color.rgb, s.line.width = rgb(m.color), Pt(5)
            s.rotation = -8
        elif m.kind in ("arrow", "xmark"):
            if m.kind == "arrow":
                x2, y2 = _xy(p, m.x2, m.y2, w, h)
                lines = [(x, y, x2 + left, y2 + top)]
            else:
                s_ = max(18, w // 40)
                lines = [(x - s_, y - s_, x + s_, y + s_), (x + s_, y - s_, x - s_, y + s_)]
            for a, b, c, d in lines:
                cn = slide.shapes.add_connector(MSO_CONNECTOR.CURVE if m.kind == "arrow" else MSO_CONNECTOR.STRAIGHT, px(a), px(b), px(c), px(d))
                cn.line.color.rgb, cn.line.width = rgb(m.color), Pt(5)
                if m.kind == "arrow":
                    ln = cn.line._get_or_add_ln()
                    tail = ln.makeelement(qn("a:tailEnd"), {"type": "triangle", "w": "med", "len": "med"})
                    ln.append(tail)
        elif m.kind == "label":
            size = max(46, w // 13)
            tb = slide.shapes.add_textbox(px(x - size * len(m.text) * .4), px(y - size * .7), px(size * len(m.text) * .8 + 40), px(size * 1.4))
            tb.rotation = -8
            r = tb.text_frame.paragraphs[0].add_run()
            r.text = m.text
            r.font.size, r.font.bold, r.font.name = Pt(size * .75), True, "Gaegu"
            r.font.color.rgb = rgb(m.color)
        elif m.kind == "star":
            s_ = max(22, w // 30)
            st = slide.shapes.add_shape(MSO_SHAPE.STAR_5_POINT, px(x - s_), px(y - s_), px(s_ * 2), px(s_ * 2))
            st.fill.solid()
            st.fill.fore_color.rgb = RGBColor.from_string("FFD23A")
            st.line.color.rgb = RGBColor.from_string(RED[1:])
