"""카드뉴스: 원고 → 1080×1350 JPG + 캔바에서 고칠 PPTX.

PPTX 구성 (연구소 publish/canva_copy.py 방식): 글자를 뺀 배경 그림 + 글상자들.
여기서는 차트를 배경에 굽지 않고 원본 파일 그대로 그림으로 넣어 캔바에서 옮기거나 바꿀 수 있게 했다. 표지 사진은 그라데이션과 함께 배경에 굽는다.
차트는 비율을 지켜 전체를 넣는다. 자르기·보정·재작도 없음.
"""
import html
import json
import pathlib
import re
import tempfile

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Pt

from studio.paths import font_css

W, H = 1080, 1350
PX = 9525
HANDLE = "@oh_neworld"
RED = "#E8141C"

CSS = """
html,body{margin:0;padding:0;width:1080px;height:1350px;overflow:hidden}
*{box-sizing:border-box}
body{font-family:HSans,'Noto Sans KR','Malgun Gothic',sans-serif;color:#111;word-break:keep-all}
.slide{position:relative;width:1080px;height:1350px;overflow:hidden}
.paper{background-color:#fbfcfe;background-image:linear-gradient(rgba(120,160,215,.16) 2px,transparent 2px),linear-gradient(90deg,rgba(120,160,215,.16) 2px,transparent 2px);background-size:54px 54px}
.tag{position:absolute;left:56px;top:48px;font-size:32px;font-weight:700;color:#444}
.pg{position:absolute;right:52px;top:42px;font-size:30px;font-weight:600;color:#667;background:#e8ebf0;border-radius:30px;padding:6px 26px}
.title{position:absolute;left:50px;right:50px;top:112px;text-align:center}
.title div{display:inline-block;font-size:62px;font-weight:900;letter-spacing:-1.5px;line-height:1.2;background-image:linear-gradient(transparent 68%,rgba(150,195,245,.6) 68%);padding:0 10px}
.main{position:absolute;left:56px;right:56px;top:212px;bottom:84px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:30px}
.handle{position:absolute;left:0;right:0;bottom:30px;text-align:center;font-size:27px;font-weight:600;color:#778}
.chart{display:block;max-width:968px;max-height:640px;width:auto;height:auto;object-fit:contain;flex:none;box-shadow:0 2px 12px rgba(0,0,0,.14);background:#fff}
.cnote{font-size:25px;font-weight:600;color:#667;margin-top:-20px;text-align:center}
.lines{text-align:center;font-size:48px;font-weight:800;line-height:1.36;letter-spacing:-1px}
.lines p,.reds p{margin:0}
.reds,.hand{text-align:center;font-family:Hand,HSans,sans-serif;font-size:64px;font-weight:700;line-height:1.22;letter-spacing:-4px;color:#E8141C;-webkit-text-stroke:2.2px #E8141C}
.hand{color:#111;-webkit-text-stroke:2.2px #111}
.hand p{margin:0}
.note{font-size:28px;font-weight:700;color:#E8141C;text-align:center}
.rbox{width:100%;border-radius:26px;padding:22px 30px;text-align:center}
.rbox:nth-child(odd){background:#fde9e9}.rbox:nth-child(even){background:#e6f0fd}
.rbox h3{margin:0 0 6px;font-size:46px;font-weight:900;color:#D0121A}.rbox:nth-child(even) h3{color:#1458B8}
.rbox p{margin:0;font-size:35px;font-weight:700;line-height:1.38}
.checks{width:100%;background:#eef3fb;border-radius:26px;padding:28px 40px}
.checks p{margin:0;font-size:40px;font-weight:800;line-height:1.75}.checks b{color:#2f6fd6;margin-right:14px}
.endname{font-size:150px;font-weight:900;color:#1D5FD1;letter-spacing:-5px;line-height:1.05;text-align:center}
.endph{width:900px;height:420px;object-fit:cover;border:8px solid #111;flex:none}
.endq{font-size:50px;font-weight:900;text-align:center;line-height:1.3}
.tiny{font-size:24px;font-weight:600;color:#778;text-align:center;line-height:1.5}
.bignum{font-size:210px;font-weight:900;letter-spacing:-6px;color:#E8141C;line-height:1.05}
.stat{width:100%;background:#fff;border:2px solid #e2e6ee;border-radius:24px;padding:22px 30px;text-align:center}
.stat.hot{background:#ffe7e7;border-color:#ffcdcd}
.stat .l{font-size:34px;font-weight:700;color:#556}
.stat .v{font-size:84px;font-weight:900;letter-spacing:-2px;line-height:1.25}
.stat.hot .v{color:#E8141C}
.box{width:100%;border-radius:26px;padding:24px 30px;text-align:center}
.box.r{background:#fde9e9}.box.b{background:#e6f0fd}
.box h3{margin:0 0 8px;font-size:46px;font-weight:900}
.box.r h3{color:#D0121A}.box.b h3{color:#1458B8}
.box p{margin:0;font-size:36px;font-weight:700;line-height:1.38}
.cover{background:#000}
.cover .ph{position:absolute;left:0;top:0;width:1080px;height:960px;object-fit:cover}
.cover .noph{position:absolute;left:0;top:0;width:1080px;height:960px;background:radial-gradient(circle at 50% 35%,#5a0d10,#120304 70%)}
.cover .fade{position:absolute;left:0;top:520px;width:1080px;height:450px;background:linear-gradient(transparent,#000)}
.cover .kw{position:absolute;left:30px;right:30px;top:905px;text-align:center;color:#F01820;font-weight:900;letter-spacing:-4px;line-height:1.1;text-shadow:0 4px 18px rgba(0,0,0,.7)}
.cover .sub{position:absolute;left:30px;right:30px;top:1168px;text-align:center;color:#fff;font-weight:800;font-size:56px;letter-spacing:-1.5px;line-height:1.28}
.cover .basis{position:absolute;right:40px;bottom:26px;color:#aaa;font-size:26px;font-weight:500}
.cover .handle{color:#999;text-align:left;left:40px;bottom:26px;font-size:26px}
"""

NO_TEXT = "*{color:transparent!important;-webkit-text-fill-color:transparent!important;text-shadow:none!important}"
NO_IMG = "[data-keep],svg[data-mark]{visibility:hidden!important}"

# 연구소 canva_copy.py 의 측정 방식: 글자가 든 가장 안쪽 덩어리의 위치·글꼴·글자 조각
MEASURE = r"""() => {
  const INL = new Set(['B','STRONG','SPAN','I','EM','U','BR','SMALL','SUP','SUB','A','MARK']);
  const out = [];
  const block = el => { let has = false;
    for (const n of el.childNodes) {
      if (n.nodeType === 3 && n.textContent.trim()) has = true;
      else if (n.nodeType === 1 && n.textContent.trim()) { if (!INL.has(n.tagName)) return false; has = true; } }
    return has; };
  const runs = (el, acc, st = {top: null}) => {
    for (const n of el.childNodes) {
      if (n.nodeType === 3) {
        const c = getComputedStyle(el).color, w = +getComputedStyle(el).fontWeight, s = n.textContent; let piece = '';
        for (const m of s.matchAll(/\S+|\s+/g)) {
          if (/^\s/.test(m[0])) { piece += ' '; continue; }
          const rg = document.createRange(); rg.setStart(n, m.index); rg.setEnd(n, m.index + m[0].length);
          const top = rg.getClientRects()[0]?.top;
          if (top != null && st.top != null && top > st.top + 4) { if (piece.trim()) acc.push({t: piece.trimEnd(), c, w}); acc.push({t: '\n'}); piece = ''; }
          if (top != null) st.top = top;
          piece += m[0];
        }
        if (piece) acc.push({t: piece, c, w});
      } else if (n.tagName === 'BR') { acc.push({t: '\n'}); st.top = null; }
      else if (n.nodeType === 1) runs(n, acc, st);
    }
    return acc; };
  for (const el of document.querySelectorAll('body *')) {
    if (el.closest('[data-mark]') || !block(el)) continue;
    if (INL.has(el.tagName) && el.parentElement && block(el.parentElement)) continue;
    let r = null; const tw = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    for (let n; (n = tw.nextNode());) { if (!n.textContent.trim()) continue;
      const rg = document.createRange(); rg.selectNodeContents(n); const q = rg.getBoundingClientRect();
      r = r ? {left: Math.min(r.left, q.left), top: Math.min(r.top, q.top), right: Math.max(r.right, q.right), bottom: Math.max(r.bottom, q.bottom)} : {left: q.left, top: q.top, right: q.right, bottom: q.bottom}; }
    if (!r) continue;
    const cs = getComputedStyle(el); if (r.right - r.left < 1) continue;
    const fs = parseFloat(cs.fontSize);
    out.push({x: r.left, y: r.top, w: r.right - r.left, h: r.bottom - r.top, fs, lh: cs.lineHeight === 'normal' ? fs * 1.3 : parseFloat(cs.lineHeight),
              ls: cs.letterSpacing === 'normal' ? 0 : parseFloat(cs.letterSpacing), align: cs.textAlign, hand: /Hand/.test(cs.fontFamily), runs: runs(el, [])});
  }
  const imgs = [...document.querySelectorAll('[data-keep]')].map(i => { const q = i.getBoundingClientRect(); return {x: q.left, y: q.top, w: q.width, h: q.height, src: i.dataset.keep, crop: i.dataset.crop || '', fit: getComputedStyle(i).objectFit}; });
  const over = []; const main = document.querySelector('.main');
  if (main && (main.scrollHeight > main.clientHeight + 2 || main.scrollWidth > main.clientWidth + 2)) over.push('본문 넘침');
  const t = document.querySelector('.title div'); if (t && t.getBoundingClientRect().bottom > 215) over.push('제목 넘침');
  for (const s of document.querySelectorAll('.kw,.sub')) { const q = s.getBoundingClientRect(); if (q.bottom > 1340 || s.scrollWidth > s.clientWidth + 2) over.push('표지 글 넘침'); }
  return {blocks: out, imgs, over};
}"""


def e(s):
    return html.escape(s or "")


def _ps(rows):
    return "".join(f"<p>{e(x)}</p>" for x in rows)


def _box(cls, b):
    return f'<div class="box {cls}"><h3>{e(b.title)}</h3>{_ps(b.lines)}</div>' if b else ""


def _img(path, cls="chart"):
    p = pathlib.Path(path)
    return f'<img class="{cls}" src="{p.as_uri()}" data-keep="{e(str(p))}">'


def fit_keyword(word):
    return min(215, int(1000 / max(1, sum(1 if ord(c) > 255 else .62 for c in word) * 1.0)))


def cover_html(s, cover):
    # 표지 사진은 그라데이션과 함께 배경에 굽는다. 투명 그림을 따로 얹으면 캔바에서 띠처럼 깨진다 (2026-11-05 확인)
    ph = f'<img class="ph" src="{pathlib.Path(cover).as_uri()}">' if cover else '<div class="noph"></div>'
    size = fit_keyword(s.keyword)
    top = 1160 - int(size * 1.12)
    return (f'<div class="slide cover">{ph}<div class="fade"></div><div class="kw" style="font-size:{size}px;top:{top}px">{e(s.keyword)}</div>'
            f'<div class="sub">{e(s.cover_sub)}</div><div class="handle">{HANDLE}</div><div class="basis">{e(s.basis)}</div></div>')


def _chart(charts, marks, name, max_w, max_h):
    """차트 칸: 표시 계획(chartmark)이 있으면 잘라서 확대하고 표시를 얹는다."""
    from studio import chartmark
    path = charts.get(name)
    if not path:
        return ""
    plan = (marks or {}).get(name) or chartmark.Plan()
    w, h = chartmark.box_size(Image.open(path).size, plan, max_w, max_h)
    return chartmark.html(path, Image.open(path).size, plan, w, h)


def slide_html(c, n, total, charts, s, note="", marks=None, cover=None):
    cnote = f'<div class="cnote">{e(note)}</div>' if c.chart in charts and note else ""
    hand = f'<div class="hand">{_ps(c.hand)}</div>' if c.hand else ""
    reds = f'<div class="reds">{_ps(c.red)}</div>' if c.red else ""
    small = f'<div class="note">{e(c.note)}</div>' if c.note else ""
    if c.form == "bignum":
        body = f'<div class="bignum">{e(c.big)}</div><div class="lines">{_ps(c.lines)}</div>{hand}{reds}'
    elif c.form == "stats":
        body = "".join(f'<div class="stat {"hot" if x.hot else ""}"><div class="l">{e(x.label)}</div><div class="v">{e(x.value)}</div></div>' for x in c.stats) + f'<div class="lines">{_ps(c.lines)}</div>{hand}{reds}'
    elif c.form == "chart":
        body = f'{_chart(charts, marks, c.chart, 968, 600)}{cnote}<div class="lines">{_ps(c.lines)}</div>{hand}{reds}'
    elif c.form == "points":
        body = f'{_box("r", c.red_box)}{_box("b", c.blue_box)}{_chart(charts, marks, c.chart, 968, 330)}{cnote}{hand}{reds}'
    elif c.form == "reasons":
        body = "".join(f'<div class="rbox"><h3>{e(b.title)}</h3>{_ps(b.lines)}</div>' for b in c.reasons) + f'{_chart(charts, marks, c.chart, 968, 300)}{hand}{reds}'
    elif c.form == "checklist":
        body = '<div class="checks">' + "".join(f"<p><b>✔</b>{e(x)}</p>" for x in c.checks) + f'</div>{hand}{reds}'
    elif c.form == "end":
        tiny = f"본 콘텐츠는 투자 교육 및 차트 해석 기록을 위한 자료이며, 특정 자산의 매수·매도 추천이나 투자 자문이 아닙니다. 모든 투자 판단과 책임은 본인에게 있습니다. ({s.basis})"
        ph = f'<img class="endph" src="{pathlib.Path(cover).as_uri()}">' if cover else ""
        body = (f'<div class="endname">{e(s.keyword)}</div>{ph}<div class="endq">{e(c.title)}</div>'
                f'<div class="reds"><p>팔로우+저장하고 다음 분석도 받아가세요!!</p></div><div class="tiny">{e(tiny)}</div>')
        return (f'<div class="slide paper"><div class="tag">{e(c.tag)}</div><div class="pg">{n}/{total}</div>'
                f'<div class="main" style="top:110px;gap:26px">{body}</div><div class="handle">{HANDLE}</div></div>')
    else:
        body = f'<div class="lines">{_ps(c.lines)}</div>{hand}{reds}'
    body += small
    return (f'<div class="slide paper"><div class="tag">{e(c.tag)}</div><div class="pg">{n}/{total}</div><div class="title"><div>{e(c.title)}</div></div>'
            f'<div class="main">{body}</div><div class="handle">{HANDLE}</div></div>')


def all_html(s, charts, cover, note="", marks=None):
    total = len(s.slides) + 1
    return [cover_html(s, cover)] + [slide_html(c, i, total, charts, s, note, marks, cover) for i, c in enumerate(s.slides, 2)]


def _doc(body, extra=""):
    return f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>{font_css()}{CSS}{extra}</style></head><body>{body}</body></html>'


def _open(pg, tmp, body, extra=""):
    f = pathlib.Path(tmp) / "p.html"
    f.write_text(_doc(body, extra), encoding="utf-8")
    pg.goto(f.as_uri())
    pg.evaluate("document.fonts.ready")
    pg.wait_for_function("[...document.images].every(i=>i.complete)")


def rgb(c):
    v = [int(float(x)) for x in re.findall(r"[\d.]+", c)[:3]]
    return RGBColor(*v) if len(v) == 3 else RGBColor(0, 0, 0)


def px(v):
    return Emu(int(v * PX))


def add_block(slide, b):
    slack = b["w"] * .06
    x, w = b["x"], b["w"] + slack
    if b["align"] == "center":
        x -= slack / 2
    elif b["align"] in ("right", "end"):
        x -= slack
    tb = slide.shapes.add_textbox(px(x), px(b["y"]), px(w), px(b["h"]))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.TOP
    lines, cur = [], []
    for r in b["runs"]:
        if r["t"] == "\n":
            lines.append(cur)
            cur = []
        else:
            cur.append(r)
    lines.append(cur)
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = {"center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT, "end": PP_ALIGN.RIGHT}.get(b["align"], PP_ALIGN.LEFT)
        p.line_spacing = round(b["lh"] / b["fs"], 2)
        for j, r in enumerate(line):
            t = r["t"].lstrip() if j == 0 else r["t"]
            t = t.rstrip() if j == len(line) - 1 else t
            if not t:
                continue
            run = p.add_run()
            run.text = t
            f = run.font
            fam = "Gaegu" if b.get("hand") else "Noto Sans KR"
            f.name = fam
            rpr = run._r.get_or_add_rPr()
            for tag in ("a:ea", "a:cs"):
                el = rpr.find(qn(tag))
                if el is None:
                    el = rpr.makeelement(qn(tag), {})
                    rpr.append(el)
                el.set("typeface", fam)
            f.size = Pt(round(b["fs"] * .75, 1))
            f.bold = r["w"] >= 600
            f.color.rgb = rgb(r["c"])
            if b["ls"]:
                rpr.set("spc", str(int(b["ls"] * 75)))


def _add_picture(slide, im):
    """차트를 원본 파일 그대로 넣고, 자르기는 캔바에서 되돌릴 수 있는 그림 자르기 설정으로 준다."""
    pic = slide.shapes.add_picture(im["src"], px(im["x"]), px(im["y"]), px(im["w"]), px(im["h"]))
    if im.get("crop"):
        x0, y0, x1, y1 = (float(v) for v in im["crop"].split(","))
        pic.crop_left, pic.crop_top, pic.crop_right, pic.crop_bottom = x0, y0, 1 - x1, 1 - y1
    return pic


def build(s, charts, cover, out_dir, want_pptx=True, note="", marks=None):
    """→ {"images": [...], "pptx": 경로, "problems": [...]}"""
    from playwright.sync_api import sync_playwright
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    slides = all_html(s, charts, cover, note, marks)
    prs = Presentation()
    prs.slide_width, prs.slide_height = px(W), px(H)
    images, problems = [], []
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
        b = pw.chromium.launch(channel="chrome")
        pg = b.new_page(viewport={"width": W, "height": H})
        for i, body in enumerate(slides, 1):
            _open(pg, tmp, body)
            m = pg.evaluate(MEASURE)
            problems += [f"{i}장: {x}" for x in m["over"]]
            png = pathlib.Path(tmp) / f"{i}.png"
            pg.screenshot(path=str(png))
            jpg = out_dir / f"카드_{i:02d}.jpg"
            Image.open(png).convert("RGB").save(jpg, "JPEG", quality=93)
            images.append(jpg)
            if want_pptx:
                _open(pg, tmp, body, NO_TEXT + NO_IMG)
                bg = pathlib.Path(tmp) / f"bg{i}.png"
                pg.screenshot(path=str(bg))
                sl = prs.slides.add_slide(prs.slide_layouts[6])
                sl.shapes.add_picture(str(bg), 0, 0, px(W), px(H))
                for im in m["imgs"]:
                    _add_picture(sl, im)
                    name = pathlib.Path(im["src"]).name
                    if marks and im.get("crop") and name in marks:
                        from studio import chartmark
                        chartmark.pptx_marks(sl, marks[name], im["x"], im["y"], im["w"], im["h"], px)
                for bl in m["blocks"]:
                    add_block(sl, bl)
        b.close()
    pptx = None
    if want_pptx:
        pptx = out_dir / "캔바용.pptx"
        prs.save(pptx)
    return {"images": images, "pptx": pptx, "problems": problems}


def verify_pptx(path, chart_md5):
    """장마다 글상자·그림이 따로 있는지, 차트가 원본 바이트 그대로 들어갔는지 본다."""
    import hashlib
    prs = Presentation(path)
    rows, found = [], set()
    for i, sl in enumerate(prs.slides, 1):
        texts = [x for x in sl.shapes if x.has_text_frame and x.text_frame.text.strip()]
        pics = [x for x in sl.shapes if x.shape_type == 13]
        rows.append({"slide": i, "textboxes": len(texts), "pictures": len(pics)})
        found |= {hashlib.md5(x.image.blob).hexdigest() for x in pics}
    missing = [k for k, v in chart_md5.items() if v not in found]
    return rows, missing


def caption_text(s, credit=None):
    tags = " ".join(x if x.startswith("#") else "#" + x for x in s.hashtags[:6])
    extra = f"\n\n표지 사진: {credit['artist'] or credit['title']} / {credit['license']} / {credit['page']}" if credit else ""
    return f"{s.caption.strip()}{extra}\n\n{tags}\n"


def to_json(s):
    return json.dumps(s.model_dump(), ensure_ascii=False, indent=1)
