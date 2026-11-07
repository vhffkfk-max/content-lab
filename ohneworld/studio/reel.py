"""릴스: 대본 → 9:16 MP4 + 캡컷으로 가져갈 묶음 폴더.

음성·배경음·합치기는 연구소 reels/engine.py 그대로 (Supertonic M3, 단어별 변조 없음).
화면은 오뉴월드 스타일로 새로 그림: 시작은 검정+빨간 핵심어, 차트 장면은 모눈종이 위에 원본 차트 전체.
차트는 자르거나 움직여 가리지 않는다.

캡컷 초안 파일을 직접 만들지 않는다 (공개 API 미확인). 영상·음성·자막·차트를 묶어 사람이 가져간다.
"""
import html
import json
import pathlib
import re
import shutil
import subprocess
import sys

from studio import facts, frame
from studio.material import md5
from studio.paths import CONFIG, font_css

sys.path.insert(0, str(pathlib.Path(__file__).parent / "vendor"))
import engine  # noqa: E402

BG_DARK = "#000000"
WIN_TOP, WIN_H, CAP_Y = frame.WIN_TOP, frame.WIN_H, frame.CAP_Y   # 틀 자리는 studio/frame.py 한 곳에서 (영상 연구소 '오뉴월드형'과 공유)

# 오뉴월드 릴스 틀은 frame.css() (위 날짜+제목, 가운데 칸, 아래 말풍선 자막 + 고정 질문, 바탕 검정). 여기는 오뉴월드 장면 꾸밈만.
EXTRA = frame.css() + """
#head,#tape,#paper{display:none}
#warn{top:250px!important;left:70px!important;right:70px!important;text-align:left!important;font-size:25px;color:#9a9aa2!important;z-index:4}
section.lit{background:#fff}
""" + "section.dark{background:" + frame.DARK_BG + "}" + """
#flash{z-index:5}
.burst{position:absolute;inset:0;pointer-events:none;background:radial-gradient(ellipse at center,transparent 45%,rgba(255,120,20,.55) 75%,rgba(255,60,0,.9) 100%);mix-blend-mode:screen}
.bignum{position:absolute;left:0;right:0;top:50%;transform:translateY(-50%);text-align:center;font-weight:900;letter-spacing:-6px;line-height:1;color:#FF2A2A;-webkit-text-stroke:7px #FFD23A;paint-order:stroke fill;text-shadow:0 0 40px rgba(255,80,0,.9),0 0 90px rgba(255,40,0,.6)}
.gold{font-size:200px;font-weight:900;letter-spacing:-6px;line-height:1;background:linear-gradient(#fff6c8,#ffd23a 45%,#c98a00);-webkit-background-clip:text;color:transparent;-webkit-text-stroke:3px #6b3a00;filter:drop-shadow(0 6px 0 #3a1a00) drop-shadow(0 0 30px rgba(255,190,60,.8))}
.gsub{font-size:52px;font-weight:800;color:#fff;text-align:center;text-shadow:0 3px 0 #000}
.wordk{font-size:120px;font-weight:900;color:#fff;text-align:center;line-height:1.18;letter-spacing:-4px;text-shadow:0 5px 0 #000}
.wordk .ln{display:block}.wordk .ln:last-child{color:#FF2A2A;-webkit-text-stroke:4px #FFD23A;paint-order:stroke fill}
.box{width:900px;border-radius:28px;padding:26px 34px;text-align:center}.box.r{background:#fde9e9}.box.b{background:#e6f0fd}
.box h3{margin:0 0 8px;font-size:60px;font-weight:900}.box.r h3{color:#D0121A}.box.b h3{color:#1458B8}.box p{margin:0;font-size:44px;font-weight:700;line-height:1.35;color:#111}
"""

FX = """
const base0=window.seek;
window.seek=t=>{base0(t);const i=TL.findIndex(s=>t<s.end),k=i<0?TL.length-1:i,el=S[k],l=t-TL[k].start;
 document.body.style.background='#000';
 el.querySelectorAll('.mk').forEach(m=>{const q=ease((l-.45-(+m.dataset.i)*.35)/.45);m.style.strokeDasharray=1;m.style.strokeDashoffset=1-q;m.style.opacity=q>0?1:0});
 el.querySelectorAll('.mkt').forEach(m=>{const q=ease((l-.45-(+m.dataset.i)*.35)/.25);m.style.opacity=q});
 el.querySelectorAll('.burst').forEach(b=>{b.style.opacity=Math.max(0,1-l/1.1)});
 el.querySelectorAll('.bignum').forEach(b=>{const q=ease((l-.15)/.25);b.style.opacity=q;b.style.transform=`translateY(-50%) scale(${1.6-.6*q})`});
 el.querySelectorAll('.gold').forEach(b=>{const q=ease((l-.05)/.3);b.style.transform=`scale(${1.5-.5*q})`;b.style.opacity=q});
};
"""


def fit_keyword(word, base=240, width=1000):
    return min(base, int(width / max(1, sum(1 if ord(c) > 255 else .62 for c in word))))


def e(s):
    return html.escape(s or "")


def _box(cls, b):
    return f'<div class="a box {cls}"><h3>{e(b.title)}</h3>' + "".join(f"<p>{e(x)}</p>" for x in b.lines) + "</div>" if b else ""


def _chart_win(charts, marks, name, anim=True):
    """가운데 칸을 꽉 채우게 차트(잘라 낸 부분)를 넣는다."""
    from PIL import Image
    from studio import chartmark
    path = charts[name]
    plan = (marks or {}).get(name) or chartmark.Plan()
    size = Image.open(path).size
    w, h = chartmark.box_size(size, plan, 1080, WIN_H)
    return chartmark.html(path, size, plan, w, h, anim=anim)


def scene_html(i, sc, charts, cover, note="", marks=None):
    first_chart = next(iter(charts), None)
    if sc.kind == "hook":
        name = sc.chart or first_chart
        inner = _chart_win(charts, marks, name, anim=False) if name else ""
        big = f'<div class="bignum" style="font-size:{fit_keyword(sc.big, 230, 980)}px">{e(sc.big)}</div>' if sc.big else ""
        return f'<section id="c{i}" class="lit" data-bg="#000">{inner}<div class="burst"></div>{big}</section>'
    if sc.kind in ("chart", "end") and (sc.chart or (sc.kind == "end" and first_chart)):
        name = sc.chart or first_chart
        return f'<section id="c{i}" class="lit" data-bg="#000">{_chart_win(charts, marks, name, anim=sc.kind == "chart")}</section>'
    if sc.kind == "stat":
        body = f'<div class="gsub a">{e(sc.title)}</div><div class="gold">{e(sc.big)}</div><div class="gsub a" data-d=".2">{e(sc.sub)}</div>'
    elif sc.kind == "points":
        body = f'{_box("r", sc.red_box)}{_box("b", sc.blue_box)}'
    else:
        rows = (sc.big or sc.title or "").replace("\\n", "\n").split("\n")
        body = '<div class="a wordk">' + "".join(f'<span class="ln">{e(x)}</span>' for x in rows) + "</div>"
    return f'<section id="c{i}" class="dark" data-bg="#000">{body}</section>'


def date_text(s):
    import datetime
    m = re.search(r"(\d{1,2})/(\d{1,2})", s.basis or "")
    if not m:
        return ""
    return f"{datetime.date.today().year}년{int(m[1])}월{int(m[2])}일"


def build_page(out, s, scenes, charts, cover, hide_cap=False, note="", marks=None):
    tl = [{"id": x["id"], "start": x["start"], "end": x["end"], "caps": x["caps"]} for x in scenes]
    secs = "".join(scene_html(i, sc, charts, cover, note, marks) for i, sc in enumerate(s.reel, 1))
    hide = "#cap{display:none!important}" if hide_cap else ""
    title = getattr(s, "reel_title", "") or s.keyword
    question = getattr(s, "reel_question", "") or s.cover_sub
    doc = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>{font_css()}{engine.CSS}{EXTRA}{hide}</style></head><body>
<div id="bar"></div>{frame.top_html(date_text(s), title, question)}{secs}<div id="cap"></div>
<div id="warn">{e(s.basis)} · 정보 제공 목적 · 투자 권유 아님 · AI 음성 · @oh_neworld</div><div id="tape"><div></div></div><div id="flash"></div>
<script>const TL={json.dumps(tl, ensure_ascii=False)};{engine.JS}{FX}</script></body></html>"""
    p = out / ("page_자막없음.html" if hide_cap else "page.html")
    p.write_text(doc, encoding="utf-8")
    return p


def srt_time(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    sec, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"


def make_srt(scenes):
    rows, n = [], 0
    for sc in scenes:
        for c in sc["caps"]:
            n += 1
            rows.append(f"{n}\n{srt_time(c['t'])} --> {srt_time(c['e'])}\n{c['text']}\n")
    return "\n".join(rows)


def round_trip(out, s):
    """받아쓰기로 자막 숫자가 음성에서 나오는지 본다. 음성 인식 환경이 없으면 건너뛴다."""
    env = {**__import__("os").environ, "PYTHONIOENCODING": "utf-8"}
    voice = str(out / "voice_only.m4a")
    jobs = [[CONFIG.get("asr_python", ""), str(pathlib.Path(__file__).parent / "vendor" / "rt_gpu.py"), voice], [CONFIG.get("asr_cpu_python", ""), CONFIG.get("asr_cpu_script", ""), voice]]   # 그래픽카드, 안 되면 CPU
    r = None
    for job in jobs:
        if pathlib.Path(job[0]).exists() and pathlib.Path(job[1]).exists():
            r = subprocess.run(job, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
            if r.returncode == 0:
                break
    if r is None or r.returncode:
        return "", ["받아쓰기 실패 (음성 인식 환경 확인)"]
    heard = (r.stdout.strip().splitlines() or [""])[-1].split("|", 1)[-1].strip()
    want = [n for sc in s.reel for ln in sc.lines for n in facts.nums(ln.cap)]
    plain = heard.replace(",", "").replace(" ", "")
    miss = [n for n in want if n not in plain and facts.read_number(n).replace(" ", "") not in plain]
    return heard, miss


CAPCUT_NOTE = """캡컷으로 고치는 법

바로 올리기: 완성본.mp4 를 그대로 씁니다.

고칠 때 (캡컷 데스크톱에서 새 프로젝트를 열고 이 폴더 파일을 가져옵니다):
1. 영상 줄: 장면영상 폴더의 01, 02, 03... 을 순서대로 놓습니다. 글자가 구워지지 않은 영상이고 소리가 없습니다. 장면을 빼거나 순서를 바꾸거나 길이를 바꿀 수 있습니다.
2. 음성 줄: 음성만.m4a. 맨 앞부터 놓으면 장면과 맞습니다. 장면을 고쳤으면 음성도 같은 자리를 자릅니다. 다시 녹음한 음성으로 바꿔도 됩니다.
3. 배경음 줄: 배경음.m4a. 소리를 줄이거나 다른 음악으로 바꿉니다.
4. 자막: 자막.srt 를 가져오면 캡컷 자막으로 고칠 수 있습니다. 메뉴 위치는 버전마다 다릅니다. 가져오기가 안 되면 대본.txt 를 보고 넣습니다.
5. 차트: 차트 폴더의 원본을 씁니다. 자르거나 색을 바꾸지 말아 주세요.

글자까지 바꾸고 싶은 장면은 원고.json 을 고쳐 `python studio.py 다시 결과폴더 --릴스만` 으로 다시 만들 수도 있습니다.

참고용: 자막없는영상.mp4 (장면을 이어 붙인 판, 소리 있음), 음성_배경음_효과음.m4a (섞은 소리), 장면 폴더 (정지 화면)

지키기: 투자 고지와 기준 시점 문구를 남겨 주세요.
이 폴더는 캡컷 프로젝트 파일이 아닙니다. 파일을 가져와서 편집하는 방식입니다.
"""


def split_scenes(video, scenes, folder):
    """자막 없는 영상을 장면별 무음 MP4 로 나눈다 (이어 붙이면 음성·자막 시각과 맞는다)."""
    folder.mkdir(exist_ok=True)
    start = 0.0
    out = []
    for n, sc in enumerate(scenes, 1):
        end = sc["end"]
        f = folder / f"{n:02d}.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(video), "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p", str(f)], check=True)
        out.append(f)
        start = end
    return out


def write_music(total, f):
    """배경음만 따로. 음악은 engine 이 직접 합성한 것이라 저작권 문제가 없다."""
    tmp = pathlib.Path(f).with_suffix(".wav")
    engine.write_wav(tmp, engine.make_music(total, engine.SR)[:int(total * engine.SR)] * .25)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(tmp), "-c:a", "aac", "-b:a", "160k", str(f)], check=True)
    tmp.unlink()


def pack_capcut(out, s, scenes, charts, chart_md5):
    pack = out / "캡컷용"
    if pack.exists():
        shutil.rmtree(pack)
    (pack / "차트").mkdir(parents=True)
    (pack / "장면").mkdir()
    shutil.copy2(out / "영상.mp4", pack / "완성본.mp4")
    shutil.copy2(out / "자막없는영상.mp4", pack / "자막없는영상.mp4")
    shutil.copy2(out / "voice_only.m4a", pack / "음성만.m4a")
    shutil.copy2(out / "voice.m4a", pack / "음성_배경음_효과음.m4a")
    (pack / "자막.srt").write_text(make_srt(scenes), encoding="utf-8-sig")
    (pack / "대본.txt").write_text("\n".join(f"[{i}] {ln.say}\n    자막: {ln.cap}" for i, sc in enumerate(s.reel, 1) for ln in sc.lines), encoding="utf-8")
    (pack / "안내.txt").write_text(CAPCUT_NOTE, encoding="utf-8")
    bad = []
    for name in sorted({sc.chart for sc in s.reel if sc.chart}):
        src = pathlib.Path(charts[name])
        dst = pack / "차트" / name
        shutil.copy2(src, dst)
        if md5(dst) != chart_md5.get(name):
            bad.append(name)
    split_scenes(pack / "자막없는영상.mp4", scenes, pack / "장면영상")
    write_music(scenes[-1]["end"], pack / "배경음.m4a")
    for f in (out / "stills").glob("*.jpg"):
        shutil.copy2(f, pack / "장면" / f.name)
    return pack, bad


def build(s, charts, cover, out, note="", marks=None):
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    engine.OUT = out
    scenes = [{"id": f"c{i}", "lines": [{"say": facts.to_reading(ln.say), "cap": [ln.cap]} for ln in sc.lines]} for i, sc in enumerate(s.reel, 1)]
    total = engine.narrate(scenes)
    engine.mix_audio(scenes, total, {f"c{i}" for i, sc in enumerate(s.reel, 1) if sc.kind == "stat"})
    # 자막 없는 판을 먼저 만든 뒤 자막 판을 만든다 (정지 화면은 자막 판 기준으로 남김)
    p0 = build_page(out, s, scenes, charts, cover, hide_cap=True, note=note, marks=marks)
    engine.shoot(p0, total, True)
    (out / "영상.mp4").replace(out / "자막없는영상.mp4")
    p1 = build_page(out, s, scenes, charts, cover, note=note, marks=marks)
    problems = engine.shoot(p1, total, True)
    heard, miss = round_trip(out, s)
    long_empty = [f"{x['id']} {x['end'] - x['start']:.1f}초" for x in scenes if x["end"] - x["start"] > 12]
    shutil.rmtree(out / "tts", ignore_errors=True)
    return {"duration": round(total, 1), "problems": problems, "heard": heard, "miss": miss, "long": long_empty, "scenes": scenes}
