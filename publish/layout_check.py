"""카드뉴스 글자 겹침 자동 검사 — 크롬에서 실제로 그린 위치를 재서 글끼리·글과 그림이 겹치거나 화면 밖으로 나간 곳을 찾는다.

    from publish.layout_check import check
    problems = check(slides_html, css)     # → ["3장: '제목…' ↔ '본문…' 겹침 40px", ...] (없으면 빈 목록)
    python -m publish.layout_check         # 12개 유형 예시와 긴 글 시험본 전부 검사
초안을 만들 때 draft_card 가 부르고, 겹치면 초안 경고로 남겨 발행을 막는다 (publish_card 는 경고 남은 초안을 거절).
"""
import json
import re
import sys
import tempfile

from publish.render import chrome, page

MEASURE = r"""<script>
document.fonts.ready.then(() => {
  const INL = new Set(['B','STRONG','SPAN','I','EM','U','BR','SMALL','SUP','SUB','A','MARK']);
  const SKIP = '.ticker,.demo,.pricebox';
  const root = document.body, items = [];
  const rectsOf = el => {
    const out = [];
    const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    while (w.nextNode()) {
      if (!w.currentNode.textContent.trim()) continue;
      const r = document.createRange(); r.selectNodeContents(w.currentNode);
      for (const q of r.getClientRects()) if (q.width > 1 && q.height > 1) out.push([q.left, q.top, q.right, q.bottom]);
    }
    return out;
  };
  const isBlock = el => {
    let has = false;
    for (const n of el.childNodes) {
      if (n.nodeType === 3 && n.textContent.trim()) has = true;
      else if (n.nodeType === 1 && n.textContent.trim()) { if (!INL.has(n.tagName)) return false; has = true; }
    }
    return has;
  };
  for (const el of root.querySelectorAll('*')) {
    if (el.closest(SKIP) || INL.has(el.tagName) || el.closest('svg') || !isBlock(el)) continue;
    const rects = rectsOf(el);
    if (rects.length) items.push({kind: 'text', text: el.textContent.trim().slice(0, 24), rects, el: 0, idx: items.length});
    el.dataset.lc = items.length - 1;
  }
  for (const el of root.querySelectorAll('svg,img,.ui,.point,.bub,.btn')) {
    if (el.closest('.foot') || el.closest('svg') !== null && el.tagName !== 'svg' || el.matches('.bgph,.ph,.nw-ph')) continue;
    const q = el.getBoundingClientRect();
    if (q.width < 2 || q.height < 2) continue;
    const inside = [...el.querySelectorAll('[data-lc]')].map(x => +x.dataset.lc);
    if (el.dataset.lc !== undefined) inside.push(+el.dataset.lc);
    items.push({kind: 'box', text: el.tagName === 'svg' ? '차트' : el.tagName === 'IMG' ? '그림' : el.className, rects: [[q.left, q.top, q.right, q.bottom]], inside});
  }
  const pre = document.createElement('pre'); pre.id = 'lc-result'; pre.style.display = 'none';
  pre.textContent = JSON.stringify(items); document.body.appendChild(pre);
});
</script>"""
TOL = 8        # 글자 상자는 실제 글자보다 위아래로 넉넉해서 이 정도 겹침은 눈에 안 보인다
W, H = 1080, 1350
TOP, BOTTOM = 60, 1340   # 4:5 에서 글이 가장자리에 붙지 않게. 위는 인스타 쪽 번호 표시 자리
LEFT, RIGHT = 44, 1036   # 프로필 격자(3:4)가 좌우 34px씩 자르는 것보다 10px 안쪽


def overlap(a, b):
    w, h = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
    return min(w, h) if w > TOL and h > TOL else 0


def problems_of(items, n, safe=False):
    out, texts = [], [(i, x) for i, x in enumerate(items) if x["kind"] == "text"]
    for i, x in texts:
        if safe and any(r[1] < TOP - 2 or r[3] > BOTTOM + 2 or r[0] < LEFT - 2 or r[2] > RIGHT + 2 for r in x["rects"]):
            out.append(f"{n}장: '{x['text']}' 가장자리에 붙거나 프로필 격자에서 잘림")
        for r in x["rects"]:
            if r[0] < -2 or r[2] > W + 2 or r[3] > H + 2 or r[1] < -2:
                out.append(f"{n}장: '{x['text']}' 화면 밖으로 나감")
                break
    for a, (i, x) in enumerate(texts):
        for _, y in texts[a + 1:]:
            d = max((overlap(p, q) for p in x["rects"] for q in y["rects"]), default=0)
            if d:
                out.append(f"{n}장: '{x['text']}' ↔ '{y['text']}' 겹침 {d:.0f}px")
    for b in (x for x in items if x["kind"] == "box"):
        for i, x in texts:
            if i in b.get("inside", []):
                continue
            d = max((overlap(p, b["rects"][0]) for p in x["rects"]), default=0)
            if d:
                out.append(f"{n}장: '{x['text']}' ↔ {b['text']} 겹침 {d:.0f}px")
    return list(dict.fromkeys(out))


def check(slides, css, safe=False):
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        for n, body in enumerate(slides, 1):
            dom = chrome(page(body + MEASURE, css), tmp, "--dump-dom")
            m = re.search(r'<pre id="lc-result"[^>]*>(.*?)</pre>', dom, re.S)
            if not m:
                out.append(f"{n}장: 검사 실패 (위치를 재지 못함)")
                continue
            import html
            out += problems_of(json.loads(html.unescape(m.group(1))), n, safe)
    return out


LONG = "시장이 예상보다 빠르게 움직이면서 투자자들의 시선이 쏠렸다는 보도가 나왔어요. 다음 발표까지 지켜볼 부분이 남아 있어요."
T2 = "다음 주 시장이 지켜볼\n**핵심 변수**는 이것입니다"
STRESS_END = {"title": "호르무즈, **48시간** 안에\n실제로 다시 열릴까요?",
              "checks": ["이란, 48시간 내 재개방 제안이라는 보도, 아직 공식 확인은 안 됐어요", "트럼프 '협상 순조롭다', 재개방은 미확인", "월요일 유가, 원/달러 환율 반응 확인"], "keyword": "호르무즈"}


def stress(forms):
    """각 유형을 규칙이 허용하는 가장 긴 글로 채운 시험본."""
    out = {}
    for form, post in forms.DEMO.items():
        p = json.loads(json.dumps(post))
        p["form"], p["end"] = form, STRESS_END
        for d in [p["cover"], *p.get("slides", [])]:
            for k in ("title", "say", "quote"):
                if k in d:
                    d[k] = T2
            for k in ("text", "sub", "caption", "tip", "point", "narration"):
                if k in d:
                    d[k] = LONG[:60] if k != "text" else LONG
        out[form] = p
    return out


def main():
    from publish import forms
    bad = 0
    for label, posts in (("예시", {k: {"form": k, **v} for k, v in forms.DEMO.items()}), ("긴 글", stress(forms))):
        for form, post in posts.items():
            pr = check(forms.slides_of(post), forms.CSS, form in forms.ACTIVE)
            bad += len(pr)
            print(f"[{label}] {form}: {'✅' if not pr else ''}")
            for x in pr:
                print("   ❌", x)
    print(f"문제 {bad}개")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
