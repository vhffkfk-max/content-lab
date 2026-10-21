"""분석 결과(dict)를 한 장짜리 HTML 리포트로 그린다. 외부 라이브러리 없음."""
from html import escape

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#16181d;--sub:#5b6270;--line:#e3e6eb;--accent:#2f6fed;
--good:#12805c;--warn:#b25e09;--chip:#eef2fb;--bar:#2f6fed22}
@media (prefers-color-scheme:dark){:root{--bg:#111318;--card:#1a1d24;--ink:#eceef2;--sub:#9aa2b1;
--line:#2a2f3a;--accent:#6f9bff;--good:#3ccf97;--warn:#f0a44b;--chip:#232a38;--bar:#6f9bff33}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font-family:Pretendard,"Malgun Gothic","Apple SD Gothic Neo",system-ui,sans-serif;line-height:1.55}
.wrap{max-width:1080px;margin:0 auto;padding:28px 16px 60px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:19px;margin:36px 0 12px}
.sub{color:var(--sub);font-size:14px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:18px 0}
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.stat b{display:block;font-size:22px}.stat span{color:var(--sub);font-size:13px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;margin-bottom:14px}
.rec h3{margin:2px 0 8px;font-size:18px}.rank{color:var(--accent);font-weight:700;margin-right:6px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.chip{background:var(--chip);border-radius:999px;padding:3px 10px;font-size:13px}
.kind{font-weight:600;color:var(--accent)}.conf-높음{color:var(--good)}.conf-낮음{color:var(--warn)}
.rec ul{margin:8px 0 8px 18px;padding:0}.rec li{margin:3px 0}
.ex{font-size:13px;color:var(--sub);border-top:1px dashed var(--line);margin-top:10px;padding-top:8px}
.ex a{color:var(--accent);text-decoration:none}
.note{background:var(--chip);border-radius:12px;padding:12px 16px;font-size:14px}
.tbl{width:100%;border-collapse:collapse;font-size:14px}
.tbl th,.tbl td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
.tbl th{color:var(--sub);font-weight:600;font-size:13px}.num{text-align:right;white-space:nowrap}
.scroll{overflow-x:auto}.bar{position:relative}.bar i{position:absolute;left:0;top:2px;bottom:2px;
background:var(--bar);border-radius:4px}.bar span{position:relative}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
.muted{color:var(--sub)}a{color:var(--accent)}
"""


def fx(v):
    return "–" if v is None else f"{v:.1f}배"


def bar(v, cap=3.0):
    if v is None:
        return '<td class="num muted">–</td>'
    w = min(v / cap, 1) * 100
    return f'<td class="num bar"><i style="width:{w:.0f}%"></i><span>{v:.1f}배</span></td>'


def n_fmt(v):
    return "–" if v is None else f"{v:,}"


def example_line(e):
    link = f'<a href="{escape(e["permalink"] or "#")}" target="_blank">보기</a>' if e.get("permalink") else ""
    return (f'@{escape(e["username"])} ({e["region"]}) · {fx(e["outlier"])} · {escape(e["format"])} · '
            f'“{escape(e["caption"])}” {link}')


def render_rec(i, r):
    chips = [f'<span class="chip">주제: {escape(r["topic"])}</span>']
    if r["format"]:
        chips.append(f'<span class="chip">추천 형식: {escape(r["format"])}</span>')
    if r["hook"]:
        chips.append(f'<span class="chip">첫 문장: {escape(r["hook"])}</span>')
    if r["slot"]:
        chips.append(f'<span class="chip">업로드: {escape(r["slot"])}</span>')
    reasons = "".join(f"<li>{escape(x)}</li>" for x in r["reasons"])
    examples = "<br>".join(example_line(e) for e in r["examples"])
    return f"""<div class="card rec">
<div class="sub"><span class="kind">{escape(r["kind"])}</span> · 신뢰도 <b class="conf-{r["confidence"]}">{r["confidence"]}</b></div>
<h3><span class="rank">#{i}</span>{escape(r["title_idea"])}</h3>
<div class="chips">{"".join(chips)}</div>
<b>왜 이걸 추천하나요?</b><ul>{reasons}</ul>
<div class="ex"><b>참고할 게시물</b><br>{examples}</div></div>"""


def stat_table(rows, label):
    body = "".join(f'<tr><td>{escape(r["key"])}</td>{bar(r["avg"])}<td class="num">{r["n"]}</td></tr>'
                   for r in rows if r["n"])
    return (f'<table class="tbl"><tr><th>{label}</th><th class="num">평소 대비</th><th class="num">게시물</th></tr>'
            f'{body or "<tr><td colspan=3 class=muted>데이터 없음</td></tr>"}</table>')


def render(d):
    c = d["counts"]
    recs = "".join(render_rec(i, r) for i, r in enumerate(d["recommendations"], 1)) or \
        '<div class="card muted">아직 추천할 만큼 데이터가 쌓이지 않았어요. 계정을 늘리거나 수집을 몇 번 더 돌려주세요.</div>'
    insights = "".join(f"<li>{escape(x)}</li>" for x in d["insights"])

    topic_rows = "".join(
        f'<tr><td>{escape(t["topic"])}</td>{bar(t["kr"]["avg"])}<td class="num">{t["kr"]["n"]}</td>'
        f'{bar(t["foreign"]["avg"])}<td class="num">{t["foreign"]["n"]}</td><td class="num">{t["hashtag_hits"] or "–"}</td></tr>'
        for t in d["topics"])

    acc_rows = ""
    for a in d["accounts"]:
        g = a["growth"]
        growth = f'{g["diff"]:+,} ({g["pct"]:+.1f}%)' if g else '<span class="muted">수집 2회 이상 필요</span>'
        er = f'{a["er"]:.2f}%' if a["er"] is not None else "–"
        if a["likes_hidden"]:
            er += ' <span class="muted">(좋아요 숨김)</span>'
        top = a["top_post"]
        top_html = (f'<a href="{escape(top["permalink"] or "#")}" target="_blank">{fx(top["outlier"])}</a> '
                    f'<span class="muted">{escape(top["caption"][:40])}</span>') if top else "–"
        acc_rows += (f'<tr><td>@{escape(a["username"])}<br><span class="muted">{escape(a["category"] or "")}</span></td>'
                     f'<td>{a["region"]}</td><td class="num">{n_fmt(a["followers"])}</td><td class="num">{growth}</td>'
                     f'<td class="num">{a["posts_per_week"]}</td><td class="num">{er}</td><td>{top_html}</td></tr>')

    top_rows = "".join(
        f'<tr><td>@{escape(p["username"])} <span class="muted">{p["region"]}</span></td><td>{fx(p["outlier"])}</td>'
        f'<td>{escape(", ".join(p["topics"]))}</td><td>{escape(p["format"])}</td><td>{escape(p["hook"])}</td>'
        f'<td><a href="{escape(p["permalink"] or "#")}" target="_blank">{escape(p["caption"][:60]) or "(캡션 없음)"}</a></td></tr>'
        for p in d["top_posts"])

    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>경제 인스타 트렌드 리포트</title>
<style>{CSS}</style></head><body><div class="wrap">
<h1>경제 인스타 트렌드 리포트</h1>
<div class="sub">{d["generated_at"]} 기준 · 최근 {d["days"]}일 분석</div>
<div class="stats">
<div class="stat"><b>{c["accounts_kr"]}</b><span>한국 계정</span></div>
<div class="stat"><b>{c["accounts_foreign"]}</b><span>해외 계정</span></div>
<div class="stat"><b>{c["recent_posts"]:,}</b><span>최근 {d["days"]}일 게시물</span></div>
<div class="stat"><b>{c["hashtag_posts"]:,}</b><span>해시태그 인기 게시물</span></div>
</div>
<div class="note"><b>숫자 읽는 법 — “평소 대비 ○배”</b><br>
게시물 반응(좋아요 + 댓글×3)을 그 계정의 <b>평소 반응(중앙값)</b>으로 나눈 값이에요.
팔로워 100만 계정과 1만 계정을 같은 기준으로 비교하려고 이렇게 계산해요.
1.0배 = 평소만큼, 2.0배 = 평소의 두 배로 터진 게시물. 댓글은 좋아요보다 강한 관심 신호라 3배로 셉니다.</div>

<h2>📌 추천 콘텐츠</h2>{recs}

<h2>💡 핵심 인사이트</h2><div class="card"><ul>{insights or "<li class=muted>데이터 부족</li>"}</ul></div>

<h2>🗂 주제별 반응 — 한국 vs 해외</h2>
<div class="card scroll"><table class="tbl"><tr><th>주제</th><th class="num">한국 반응</th><th class="num">개수</th>
<th class="num">해외 반응</th><th class="num">개수</th><th class="num">해시태그</th></tr>{topic_rows}</table>
<div class="sub" style="margin-top:8px">해외 반응은 높은데 한국 개수가 적은 주제 = 먼저 다루면 선점할 수 있는 주제예요.</div></div>

<h2>🎬 형식 · 첫 문장 · 업로드 시간</h2>
<div class="grid2">
<div class="card"><b>형식 (한국)</b>{stat_table(d["formats"]["한국"], "형식")}</div>
<div class="card"><b>형식 (해외)</b>{stat_table(d["formats"]["해외"], "형식")}</div>
<div class="card"><b>첫 문장 스타일 (한국)</b>{stat_table(d["hooks"]["한국"], "스타일")}</div>
<div class="card"><b>첫 문장 스타일 (해외)</b>{stat_table(d["hooks"]["해외"], "스타일")}</div>
<div class="card"><b>업로드 시간대 (한국 계정, 한국시간)</b>{stat_table(d["slots_kr"], "시간대")}</div>
</div>

<h2>📈 계정 활성도</h2>
<div class="card scroll"><table class="tbl"><tr><th>계정</th><th>지역</th><th class="num">팔로워</th><th class="num">팔로워 변화</th>
<th class="num">주간 게시</th><th class="num">참여율</th><th>최근 최고 게시물</th></tr>{acc_rows}</table>
<div class="sub" style="margin-top:8px">참여율 = 최근 4주 게시물 반응 중앙값 ÷ 팔로워. 팔로워 변화는 수집을 여러 날 돌려야 보여요.</div></div>

<h2>🔥 최근 반응 TOP 게시물</h2>
<div class="card scroll"><table class="tbl"><tr><th>계정</th><th>평소 대비</th><th>주제</th><th>형식</th><th>첫 문장</th><th>캡션</th></tr>{top_rows}</table></div>
</div></body></html>"""
