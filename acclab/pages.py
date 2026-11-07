"""계정별 페이지 — public/accounts/ (목록) + public/accounts/<slug>/ (그 계정 콘텐츠). build_site.py 가 부른다.

    python -m acclab.pages                 # public/ 에 바로 (build_site.py 없이 계정 페이지만)
    python -m acclab.pages --out <폴더>    # 다른 곳에 (로컬 확인용)

준비 안 된 계정(ready=false)도 주소는 열리고 '준비 중'으로 보인다. 데이터는 output/site/acc_<slug>.json.
"""
import argparse
import html
import json
import sys
from pathlib import Path

from acclab.common import TAG_NAMES, accounts, election_now, items_path, load
from common import ROOT

OUT_LABEL = {"threads": "쓰레드", "video": "숏폼 영상", "naver_blog": "네이버 블로그", "instagram_card": "인스타 카드뉴스", "reels": "릴스"}

CSS = """
:root{--ground:#f8f9fb;--surface:#fff;--raised:#f1f3f6;--border:#e3e7ec;--rule:#eef1f4;--text:#17202b;--muted:#4b5563;--faint:#5f6b7a;
--accent:#b8336a;--accent-soft:#fdf2f7;--accent-ink:#6b1d3e;--warn-bg:#fff4dc;--warn-ink:#92400e;--stop-bg:#ffedea;--stop-ink:#831c1e;
--font:"Pretendard Variable",Pretendard,"Malgun Gothic","Apple SD Gothic Neo",system-ui,sans-serif;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--ground:#0f1217;--surface:#171b22;--raised:#1f242d;--border:#2c333d;--rule:#232932;--text:#eef1f5;--muted:#aab3bf;
--faint:#97a1ae;--accent:#e2719d;--accent-soft:#2b1a22;--accent-ink:#f7c6da;--warn-bg:#2d2213;--warn-ink:#f0b86a;--stop-bg:#2e1818;--stop-ink:#f59b94;color-scheme:dark}}
*{box-sizing:border-box}html,body{margin:0;background:var(--ground);color:var(--text);font-family:var(--font);font-size:15px;line-height:1.6;word-break:keep-all;overflow-wrap:anywhere}
a{color:var(--accent)}main{max-width:980px;margin:0 auto;padding:28px 20px 80px}
.top{display:flex;align-items:baseline;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:6px}
.top a{font-size:14px;text-decoration:none}h1{font-size:28px;margin:0;letter-spacing:-.01em}h2{font-size:18px;margin:32px 0 10px}
.sub{color:var(--muted);margin:4px 0 0}.chips{display:flex;gap:6px;flex-wrap:wrap;margin:12px 0 0;padding:0;list-style:none}
.chip{font-size:12px;padding:3px 9px;border-radius:999px;background:var(--raised);color:var(--muted)}
.chip.on{background:var(--accent-soft);color:var(--accent-ink);font-weight:600}
.panel{background:var(--surface);border:1px solid var(--border);border-radius:12px}
.group{margin-top:26px}.group h2{margin:0 0 10px;font-size:13px;color:var(--faint);font-weight:700;letter-spacing:.04em}
.acc{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}
.acc a{display:block;padding:16px 18px;text-decoration:none;color:var(--text)}.acc a:hover{border-color:var(--accent)}
.acc b{font-size:17px}.acc p{margin:6px 0 0;font-size:13px;color:var(--muted)}.soon{color:var(--faint)}
.item{margin:0 0 10px}.item>summary{list-style:none;cursor:pointer;padding:14px 18px;display:grid;grid-template-columns:1fr auto;gap:4px 12px}
.item>summary::-webkit-details-marker{display:none}.item[open]>summary{border-bottom:1px solid var(--rule)}
.item .t{font-weight:600;font-size:16px}.item .m{font-size:13px;color:var(--muted);grid-column:1}.item .f{grid-row:1/3;grid-column:2;align-self:center;display:flex;gap:6px}
.body{padding:16px 18px 20px}.tabs{display:flex;gap:4px;flex-wrap:wrap;margin:0 0 10px}
.tabs button{all:unset;cursor:pointer;font-size:13px;padding:6px 12px;border-radius:8px;background:var(--raised);color:var(--muted)}
.tabs button[aria-pressed=true]{background:var(--accent-soft);color:var(--accent-ink);font-weight:600}
.tabs button:focus-visible,.copy:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
pre{white-space:pre-wrap;font:inherit;margin:0;padding:16px;background:var(--raised);border-radius:10px;line-height:1.75}
.row{display:flex;justify-content:space-between;align-items:center;gap:10px;margin:18px 0 8px}.row h3{margin:0;font-size:15px}
.copy{all:unset;cursor:pointer;font-size:13px;font-weight:600;padding:7px 14px;border-radius:8px;background:var(--accent);color:#fff}
.copy.done{background:var(--text)}
.flag{font-size:13px;padding:8px 12px;border-radius:8px;margin:0 0 6px}.flag.stop{background:var(--stop-bg);color:var(--stop-ink)}
.flag.warn{background:var(--warn-bg);color:var(--warn-ink)}.pill{font-size:12px;padding:2px 8px;border-radius:999px}
.pill.stop{background:var(--stop-bg);color:var(--stop-ink)}.pill.warn{background:var(--warn-bg);color:var(--warn-ink)}.pill.ok{background:var(--raised);color:var(--muted)}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;vertical-align:top;padding:8px 10px;border-bottom:1px solid var(--rule)}
th{font-size:12px;color:var(--faint);font-weight:600}td.s{white-space:nowrap;color:var(--muted)}
.facts{margin:0;padding-left:18px;font-size:14px;color:var(--muted)}.src{font-size:13px}.empty{padding:28px 18px;color:var(--muted)}
.notice{margin:16px 0 0;padding:12px 16px;border-radius:10px;background:var(--warn-bg);color:var(--warn-ink);font-size:14px}
@media (max-width:640px){main{padding:18px 14px 60px}h1{font-size:24px}.item>summary{grid-template-columns:1fr}.item .f{grid-row:auto;grid-column:1}
td.s{white-space:normal}.copy{padding:9px 14px}}
"""

JS = r"""
const D = JSON.parse(document.getElementById('data').textContent);
const NAMES = {main:'기본형', A:'A 판단형', B:'B 리스트형', C:'C 단문형', D:'D 연결형'};
const text = (it, k) => Array.isArray(it.thread[k]) ? it.thread[k].map((p, i) => `[${i + 1}칸]\n${p}`).join('\n\n') : it.thread[k];
async function copy(btn, s) {
  try { await navigator.clipboard.writeText(s); } catch (e) {
    const t = document.createElement('textarea'); t.value = s; document.body.appendChild(t); t.select(); document.execCommand('copy'); t.remove(); }
  const o = btn.textContent; btn.textContent = '복사됨'; btn.classList.add('done'); setTimeout(() => { btn.textContent = o; btn.classList.remove('done'); }, 1400);
}
document.querySelectorAll('.item').forEach(el => {
  const it = D.items[+el.dataset.i]; let cur = 'main';
  const pre = el.querySelector('pre.thread'), flags = el.querySelector('.tflags');
  const draw = () => {
    pre.textContent = text(it, cur);
    el.querySelectorAll('.tabs button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.k === cur)));
    flags.innerHTML = (it.flags[cur] || []).map(f => `<div class="flag ${f.level}">⚠ ${f.kind}${f.hit ? ` — “${f.hit.replace(/</g, '&lt;')}”` : ''}</div>`).join('');
  };
  el.querySelectorAll('.tabs button').forEach(b => b.addEventListener('click', () => { cur = b.dataset.k; draw(); }));
  el.querySelector('.copy.th').addEventListener('click', e => copy(e.target, Array.isArray(it.thread[cur]) ? it.thread[cur].join('\n\n') : it.thread[cur]));
  el.querySelector('.copy.vs').addEventListener('click', e => copy(e.target,
    [it.video.hook, '', ...it.video.scenes.map(s => `[${s.sec}초] ${s.narration}\n자막: ${s.caption}\n화면: ${s.visual}`), '', it.video.cta, it.video.disclaimer].join('\n')));
  el.querySelector('.copy.vj').addEventListener('click', e => copy(e.target, JSON.stringify(it.video, null, 1)));
  draw();
});
"""

e = html.escape


def page(title, body, data=None, depth=1):
    script = ""
    if data is not None:
        script = ('<script id="data" type="application/json">' + json.dumps(data, ensure_ascii=False).replace("</", "<\\/") + "</script><script>" + JS + "</script>")
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="robots" content="noindex"><title>{e(title)}</title>'
            f'<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">'
            f"<style>{CSS}</style></head><body><main>{body}</main>{script}</body></html>")


def badge(flags):
    lv = [f["level"] for f in flags]
    if "stop" in lv:
        return f'<span class="pill stop">⚠ 검사 {lv.count("stop")}건</span>'
    if "warn" in lv:
        return f'<span class="pill warn">⚠ 확인 {lv.count("warn")}건</span>'
    return '<span class="pill ok">검사 통과</span>'


def item_html(i, it):
    allflags = sum(it["flags"].values(), []) + it.get("video_flags", [])
    tags = " · ".join(TAG_NAMES.get(t, t) for t in it.get("tags", []))
    when = it["at"][5:16].replace("T", " ")
    tabs = "".join(f'<button type="button" data-k="{k}" aria-pressed="false">{n}</button>'
                   for k, n in (("main", "기본형"), ("A", "A 판단형"), ("B", "B 리스트형"), ("C", "C 단문형"), ("D", "D 연결형")))
    scenes = "".join(f'<tr><td class="s">{e(s["sec"])}초</td><td>{e(s["narration"])}</td><td>{e(s["caption"])}</td><td>{e(s["visual"])}</td></tr>'
                     for s in it["video"]["scenes"])
    vflags = "".join(f'<div class="flag {f["level"]}">⚠ {e(f["kind"])}{" — “" + e(f["hit"]) + "”" if f["hit"] else ""}</div>' for f in it.get("video_flags", []))
    dup = "".join(f'<div class="flag warn">⚠ 첫 문장이 {e(o)} 계정 글과 겹침</div>' for o in it.get("hook_dupes", []))
    facts = "".join(f'<li>{e(f["text"])} <span class="src">({e(f.get("source") or "-")})</span></li>' for f in it.get("facts", []))
    links = " ".join(f'<a href="{e(u)}" target="_blank" rel="noopener">원문 {n + 1}</a>' for n, u in enumerate(it.get("sources", [])))
    return f"""<details class="item panel" data-i="{i}"><summary><span class="t">{e(it["title"])}</span>
<span class="m">{when} · {e(tags)} · {len(it.get("outlets", []))}개 매체 보도</span><span class="f">{badge(allflags)}</span></summary>
<div class="body">{dup}
<div class="row"><h3>쓰레드 글</h3><button type="button" class="copy th">이 글 복사</button></div>
<div class="tabs" role="group" aria-label="글 형식">{tabs}</div><div class="tflags"></div><pre class="thread"></pre>
<div class="row"><h3>영상 스크립트 · {it["video"]["duration_sec"]}초 · 9:16 흑백</h3><span><button type="button" class="copy vs">대본 복사</button> <button type="button" class="copy vj">JSON 복사</button></span></div>
{vflags}<p class="sub"><b>첫 3초</b> {e(it["video"]["hook"])}</p>
<div style="overflow-x:auto"><table><thead><tr><th>구간</th><th>대사</th><th>자막</th><th>화면</th></tr></thead><tbody>{scenes}</tbody></table></div>
<p class="sub"><b>마지막</b> {e(it["video"]["cta"])} {e(it["video"]["disclaimer"])}</p>
<div class="row"><h3>원본 소재</h3></div><ul class="facts">{facts or "<li>사실 목록 없음</li>"}</ul><p class="src">{links}</p>
</div></details>"""


def account_page(a, items):
    chips = "".join(f'<li class="chip on">{OUT_LABEL.get(o, o)}</li>' for o in a["outputs"])
    head = (f'<div class="top"><h1>{e(a["name"])}</h1><a href="../">← 계정 목록</a></div>'
            f'<p class="sub">{e(a["group"])} · {e(a.get("handle") or "핸들 미정")}</p><ul class="chips">{chips}</ul>')
    if a["group"] == "정치":
        head += '<p class="notice">정치 계정은 사실(수치·발언·날짜)이 짝 계정과 같아야 하고, 인용은 출처 확인된 것만 씁니다. 프로필에 운영자 공개 문구를 둡니다.</p>'
        el = election_now()
        if el:
            head += f'<p class="notice">⚠ 선거 기간입니다 ({e(el["name"])}). 선거법 위반 표현이 없는지 꼭 확인하세요.</p>'
    if not a.get("ready"):
        return page(f'{a["name"]} — 준비 중', head + '<div class="panel empty">이 계정은 준비 중이에요. 순서대로 하나씩 만들고 있습니다.</div>')
    today = items[0]["at"][:10] if items else ""
    new = [(i, it) for i, it in enumerate(items) if it["at"][:10] == today]
    old = [(i, it) for i, it in enumerate(items) if it["at"][:10] != today]
    body = head + f'<h2>오늘 만든 콘텐츠 <span class="sub">{today[5:].replace("-", "/") if today else ""}</span></h2>'
    body += "".join(item_html(i, it) for i, it in new) or '<div class="panel empty">아직 오늘 만든 글이 없어요. PC가 07·12·18시에 만듭니다.</div>'
    if old:
        body += "<h2>지난 콘텐츠</h2>" + "".join(item_html(i, it) for i, it in old)
    body += '<p class="sub" style="margin-top:28px">자동 검사는 놓칠 수 있어요. 올리기 전 숫자와 표현을 한 번 확인해 주세요.</p>'
    return page(a["name"], body, {"items": items})


def index_page(accs):
    groups = {}
    for a in accs:
        groups.setdefault(a["group"], []).append(a)
    body = ('<div class="top"><h1>계정별 콘텐츠</h1><a href="../">← 연구소</a></div>'
            '<p class="sub">같은 뉴스 소재를 계정마다 다른 관점으로 바꾼 글과 영상 대본입니다.</p>')
    for g, rows in groups.items():
        cards = ""
        for a in rows:
            items = load(items_path(a["slug"]), [])
            outs = ", ".join(OUT_LABEL.get(o, o) for o in a["outputs"])
            state = f'글 {len(items)}개' if a.get("ready") else '<span class="soon">준비 중</span>'
            cards += f'<a class="panel" href="{a["slug"]}/"><b>{e(a["name"])}</b><p>{outs} · {state}</p></a>'
        body += f'<section class="group"><h2>{e(g)}</h2><div class="acc">{cards}</div></section>'
    return page("계정별 콘텐츠", body)


def build(out):
    out = Path(out) / "accounts"
    accs = accounts()
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(index_page(accs), encoding="utf-8")
    for a in accs:
        d = out / a["slug"]
        d.mkdir(exist_ok=True)
        (d / "index.html").write_text(account_page(a, load(items_path(a["slug"]), [])), encoding="utf-8")
    return len(accs)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "public"))
    print("계정 페이지:", build(ap.parse_args().out))


if __name__ == "__main__":
    main()
