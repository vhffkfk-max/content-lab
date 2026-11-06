"""릴스 공용 부품: 시세, 숫자 읽기, 내레이션, 9:16 화면 틀, 영상 합치기. 주제별 제작은 make_reel.py.

"""
import json
import os
import shutil
import time
from concurrent.futures import ProcessPoolExecutor
import re
import wave
import pathlib
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from common import ROOT  # noqa: E402
from publish.render import font_css  # noqa: E402

OUT = ROOT / "output" / "reels" / "work"   # make_reel.py 가 주제별 폴더로 바꾼다
TTS_PY = pathlib.Path(r"C:\Users\qkreo\voice-lab\st\Scripts\python.exe")
VOICE = "M3"   # 사용자가 고른 Supertonic 남성 음성 (무료, PC에서 실행. 코드 MIT, 모델 OpenRAIL-M)
SR = 44100
W, H, FPS = 1080, 1920, 30
KST = timezone(timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0"}
GAP = 0.05      # 문장 사이 쉼(초)
DIGIT = "영일이삼사오육칠팔구"


# ── 시세 ──
def naver(path):
    x = requests.get(f"https://polling.finance.naver.com/api/realtime/domestic/{path}", headers=UA, timeout=20).json()["datas"][0]
    return {"close": float(x["closePrice"].replace(",", "")), "pct": float(x["fluctuationsRatio"]),
            "at": x["localTradedAt"], "status": x["marketStatus"]}


def yahoo(sym):
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(sym)}?range=2mo&interval=1d", headers=UA, timeout=20).json()["chart"]["result"][0]
    rows = [(t, c) for t, c in zip(r["timestamp"], r["indicators"]["quote"][0]["close"]) if c is not None]
    return {"closes": [c for _, c in rows], "date": datetime.fromtimestamp(rows[-1][0], KST).strftime("%m/%d"),
            "pct": (rows[-1][1] / rows[-2][1] - 1) * 100}


# ── 숫자 읽기 ──
def under_10k(n):
    out = ""
    for u, name in ((1000, "천"), (100, "백"), (10, "십")):
        d, n = divmod(n, u)
        if d:
            out += ("" if d == 1 else DIGIT[d]) + name
    return out + (DIGIT[n] if n else "")


def read_pct(x):
    x = round(abs(x), 1)
    a, b = int(x), round((x - int(x)) * 10)
    return (under_10k(a) or "영") + (f" 점 {DIGIT[b]}" if b else "") + " 퍼센트"


def pct(x, sign=False):
    return f"{'+' if sign and x > 0 else '−' if sign and x < 0 else ''}{abs(round(x, 1)):.1f}%"


# ── 음성 ──
NUM_WORD = re.compile(r"^[영일이삼사오육칠팔구십백천만억조점]+(퍼센트|원|달러|조|억|만|배|위|개월|년|월|일|거래일|석)?[은는이가을를의에도]?$|^퍼센트")
KEY_WORD = re.compile(r"폭락|폭등|급락|급등|최대|최저|역대|사상|처음|첫|왜|대체|압승|그런데|근데|하지만|다만|진짜|모두|반전|쇼크|충격")


def speed_of(text):
    """문장마다 빠르기를 다르게: 질문과 숫자·핵심어 문장은 천천히, 설명은 빠르게."""
    if text.rstrip().endswith("?"):
        return 1.05
    if any(NUM_WORD.match(w) or KEY_WORD.search(w) for w in text.split()):
        return 1.1
    return 1.15


def spoken(say):
    """숫자 앞에 쉼표를 넣어 숫자를 끊어 말하게 한다 (음성에 변조를 가하지 않는다)."""
    words = say.replace("*", "").replace("|", " ").split()
    out = []
    for i, w in enumerate(words):
        if i and NUM_WORD.match(w) and not NUM_WORD.match(words[i - 1]) and not out[-1].endswith(","):
            out[-1] += ","
        out.append(w)
    return " ".join(out)


def read_wav(f):
    with wave.open(str(f)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def write_wav(f, x, sr=SR):
    with wave.open(str(f), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())


def speak_all(lines, d):
    """모든 문장을 한 번에 만든다 (모델 불러오기가 오래 걸려서). 앞뒤 무음만 잘라 내고 소리는 그대로 둔다."""
    jobs = [{"text": spoken(x), "speed": speed_of(spoken(x)), "out": str(d / f"{n:02d}.wav")} for n, x in enumerate(lines, 1)]
    f = d / "jobs.json"
    f.write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")
    subprocess.run([str(TTS_PY), str(pathlib.Path(__file__).with_name("tts_supertonic.py")), str(f), VOICE], check=True,
                   env={**os.environ, "PYTHONIOENCODING": "utf-8", "SUPERTONIC_INTRA_OP_THREADS": str(max(4, (os.cpu_count() or 8) // 4))})   # 성능 코어 수만큼: 전부 쓰면 오히려 2배 이상 느렸다 (i9-14900K 실측)
    for job in jobs:
        x = read_wav(job["out"])
        loud = np.nonzero(np.abs(x) > .006)[0]
        y = x[max(0, int(loud[0]) - int(.01 * SR)):int(loud[-1]) + int(.05 * SR)].copy()
        fade = int(.006 * SR)
        y[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
        write_wav(job["out"], y)


def _lowpass(x, a):
    y = np.zeros_like(x)
    prev = 0.0
    for i, v in enumerate(x):
        prev += a * (v - prev)
        y[i] = prev
    return y


def make_sfx(sr):
    """효과음을 코드로 직접 만든다 (저작권 없음)."""
    rng = np.random.default_rng(7)
    n = int(.24 * sr)
    t = np.linspace(0, 1, n, dtype=np.float32)
    noise = rng.standard_normal(n).astype(np.float32)
    whoosh = (_lowpass(noise, .28) - _lowpass(noise, .03)) * np.sin(np.pi * t) ** 2
    whoosh = whoosh / np.abs(whoosh).max()
    m = int(.32 * sr)
    tt = np.arange(m, dtype=np.float32) / sr
    thump = np.sin(2 * np.pi * (46 * tt + 28 * (1 - np.exp(-tt * 28)) / 28 * 2)) * np.exp(-tt * 13)
    click = rng.standard_normal(m).astype(np.float32) * np.exp(-tt * 110) * .35
    hit = thump + click
    return whoosh, hit / np.abs(hit).max()


def make_music(total, sr):
    """낮은 베이스와 잔잔한 박자만 있는 긴장감 배경음 (직접 합성, 저작권 없음)."""
    beat = 60 / 104
    n = int(total * sr) + sr
    out = np.zeros(n, dtype=np.float32)
    roots = [55.0, 55.0, 65.41, 49.0]
    rng = np.random.default_rng(11)
    bar = 0
    pos = 0.0
    while pos < total + 1:
        i = int(pos * sr)
        f = roots[bar % 4]
        dur = int(beat * 4 * sr)
        tt = np.arange(dur, dtype=np.float32) / sr
        env = np.minimum(tt / .05, 1) * np.exp(-tt * .55)
        pad = (np.sin(2 * np.pi * f * tt) + .35 * np.sin(2 * np.pi * f * 2 * tt) + .18 * np.sin(2 * np.pi * f * 3.001 * tt)) * env
        e = min(n, i + dur)
        out[i:e] += pad[:e - i].astype(np.float32) * .6
        for k in range(8):
            j = int((pos + k * beat / 2) * sr)
            m = int(.03 * sr)
            if j + m < n:
                out[j:j + m] += rng.standard_normal(m).astype(np.float32) * np.exp(-np.arange(m) / sr * 180).astype(np.float32) * (.1 if k % 2 else .05)
        for k in (0, 2):
            j = int((pos + k * beat) * sr)
            m = int(.16 * sr)
            if j + m < n:
                q = np.arange(m, dtype=np.float32) / sr
                out[j:j + m] += np.sin(2 * np.pi * 62 * q) * np.exp(-q * 24) * .6
        pos += beat * 4
        bar += 1
    return out / np.abs(out).max()


def mix_audio(scenes, total, hits):
    """음성 + 전환 효과음 + 숫자 강조음 + 배경음(말할 때는 작아진다). 음성만 든 파일은 받아쓰기에 쓴다."""
    sr = 44100
    voice_only, final, tmp = OUT / "voice_only.m4a", OUT / "voice.m4a", OUT / "mix.wav"
    final.replace(voice_only)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(voice_only), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"], capture_output=True, check=True).stdout
    v = np.frombuffer(raw, dtype=np.float32).copy()
    whoosh, hit = make_sfx(sr)
    music = make_music(len(v) / sr, sr)[:len(v)]
    win = int(.25 * sr)
    level = np.convolve(np.abs(v), np.ones(win, dtype=np.float32) / win, mode="same")
    duck = np.where(level > .012, 1.0, 1.9).astype(np.float32)
    duck = np.convolve(duck, np.ones(win, dtype=np.float32) / win, mode="same")
    mix = v + music * duck * .045
    for k, sc in enumerate(scenes):
        at = int(sc["start"] * sr)
        if k:
            a = max(0, at - int(.12 * sr))
            e = min(len(mix), a + len(whoosh))
            mix[a:e] += whoosh[:e - a] * .075
        if sc["id"] in hits:
            e = min(len(mix), at + len(hit))
            mix[at:e] += hit[:e - at] * .2
    pcm = (np.clip(mix, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(tmp), "-af", "alimiter=limit=0.89", "-ac", "2", "-c:a", "aac", "-b:a", "192k", str(final)], check=True)
    tmp.unlink()


def duration(f):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                                capture_output=True, text=True, check=True).stdout)


def narrate(scenes):
    """문장별로 음성을 만들고, 장면·자막 시각을 잰다. 자막 구간은 글자 수 비례."""
    d = OUT / "tts"
    d.mkdir(parents=True, exist_ok=True)
    parts, t, n = [], 0.15, 0
    silence = lambda name, sec: subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", str(sec), "-c:a", "pcm_s16le", str(d / name)], check=True)
    silence("gap.wav", GAP)
    silence("lead.wav", 0.15)
    silence("gap_long.wav", .2)
    parts.append(d / "lead.wav")
    speak_all([ln["say"] for sc in scenes for ln in sc["lines"]], d)
    for sc in scenes:
        sc["start"] = t
        sc["caps"] = []
        for ln in sc["lines"]:
            n += 1
            wav = d / f"{n:02d}.wav"
            dur = duration(wav)
            chunks = ln["say"].replace("*", "").split("|")
            assert len(chunks) == len(ln["cap"]), ln
            total = sum(len(c) for c in chunks)
            at = t
            for c, cap in zip(chunks, ln["cap"]):
                span = dur * len(c) / total
                sc["caps"].append({"t": round(at, 3), "e": round(at + span, 3), "text": cap})
                at += span
            gap_name = "gap_long.wav" if ln["say"].rstrip("* ").endswith("?") else "gap.wav"
            parts += [wav, d / gap_name]
            t += dur + (.2 if gap_name == "gap_long.wav" else GAP)
        sc["end"] = t
    scenes[-1]["end"] = t + 0.4
    listf = d / "list.txt"
    listf.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listf), "-af", "highpass=f=90,equalizer=f=250:t=q:w=1:g=-2,highshelf=f=3500:g=3,loudnorm=I=-14:TP=-1.5:LRA=11,apad=pad_dur=0.8",
                    "-ar", "44100", "-ac", "2", "-c:a", "aac", "-b:a", "192k", str(OUT / "voice.m4a")], check=True)
    return scenes[-1]["end"]


# ── 화면 (안전 구역: 위 14%, 아래 35%, 좌우 6% 안에 핵심을 둔다) ──
def sparkline(hist):
    lo, hi = min(hist), max(hist)
    w, h = 900, 400
    pts = [(i / (len(hist) - 1) * w, 20 + (hi - v) / (hi - lo) * (h - 40)) for i, v in enumerate(hist)]
    return w, h, " ".join(f"{x:.1f},{y:.1f}" for x, y in pts), pts[-1]


def bar(label, val, lim, delay):
    up = val > 0
    w = min(abs(val) / lim, 1) * 430
    return f"""<div class="a row" data-d="{delay}"><div class="lb">{label}</div><div class="track"><div class="fill {'up' if up else 'dn'}" data-w="{w:.0f}" data-d="{delay}"></div></div><div class="v {'up' if up else 'dn'}">{pct(val, True)}</div></div>"""


CSS = """
html,body{margin:0;width:1080px;height:1920px;overflow:hidden;background:#0B0B0D;color:#fff;font-family:HSans,'Noto Sans CJK KR','Malgun Gothic',sans-serif}
*{box-sizing:border-box}
.up{color:#FF4B4F}.dn{color:#5AA2FF}.y{color:#FFC23A}
#head{position:absolute;top:150px;left:65px;right:65px;display:flex;align-items:center;justify-content:space-between}
#head img{height:84px;border-radius:50%}#head span{font-size:30px;color:#a9a9b2;font-weight:500}
section{position:absolute;left:65px;right:65px;top:285px;height:770px;display:none;flex-direction:column;justify-content:center;gap:26px}
.kick{font-size:44px;font-weight:800;color:#FFC23A}.kick.y{margin-top:26px}
.nm{font-size:46px;font-weight:700;color:#e6e6ea}.nm small{font-size:30px;color:#a9a9b2;margin-left:10px}
.xl{font-size:72px}.why{font-size:420px;font-weight:900;text-align:center;line-height:1}.big{font-size:128px;font-weight:900;letter-spacing:-3px;line-height:1.08}.huge{font-size:164px}.big.mega{font-size:230px;letter-spacing:-6px}
.vs{display:flex;flex-direction:column;gap:26px}.card{background:#17171b;border-radius:28px;padding:30px 38px}.card.hot{border:5px solid #E3262B}
.num{font-size:82px;font-weight:900;letter-spacing:-2px}.chart{display:block;width:100%;height:auto}.tag{font-size:46px;font-weight:700}
.stock{background:#17171b;border-radius:28px;padding:24px 38px}.sub{font-size:48px;color:#c5c5cc;font-weight:700}
.wave{line-height:1.08;font-size:200px;font-weight:900;color:#5AA2FF;letter-spacing:-3px}
.seats{display:flex;gap:24px}.seat{flex:1;background:#12233f;border-radius:26px;padding:26px 32px}.s{font-size:104px;font-weight:900}.s small{font-size:34px;font-weight:600;margin-left:8px;color:#b9cdea}
.arrow{font-size:104px;line-height:1.2;font-weight:900;background:#E3262B;border-radius:24px;padding:44px 30px;text-align:center}
.rows{display:flex;flex-direction:column;gap:22px}.row{display:grid;grid-template-columns:1fr auto;gap:8px 16px;align-items:center}
.lb{font-size:40px;font-weight:700;grid-column:1/3}.track{height:48px;background:#1b1b20;border-radius:12px;overflow:hidden}.fill{height:100%;width:0;border-radius:12px}.fill.up{background:#FF4B4F}.fill.dn{background:#5AA2FF}.v{font-size:58px;font-weight:900;min-width:230px;text-align:right}
.q{font-size:104px;font-weight:900;line-height:1.2;letter-spacing:-2px}.q.big2{font-size:130px}.chk{font-size:110px;font-weight:800}.cmt{font-size:66px;font-weight:900;background:#E3262B;border-radius:20px;padding:22px;text-align:center;margin-top:18px}
.warn{font-size:32px;color:#c9c9d1;line-height:1.45;margin-top:10px}
#cap{position:absolute;left:65px;right:65px;top:1072px;height:185px;display:flex;align-items:center;justify-content:center;text-align:center;font-size:66px;line-height:1.24;font-weight:900;letter-spacing:-1px;word-break:keep-all;text-shadow:0 3px 0 #000}
#cap em{font-style:normal;color:#FFC23A}
#tape{position:absolute;left:0;right:0;top:1330px;height:76px;background:#141418;border-top:2px solid #26262c;border-bottom:2px solid #26262c;overflow:hidden}
#tape div{position:absolute;white-space:nowrap;font-size:40px;font-weight:700;line-height:76px;color:#d7d7dd}
#flash{position:absolute;inset:0;background:#fff;opacity:0;pointer-events:none}#warn{position:absolute;left:65px;right:65px;top:244px;font-size:27px;color:#d9d9de;text-align:right}
#bar{position:absolute;left:0;top:0;height:10px;background:#E3262B}
"""

JS = """
const S=[...document.querySelectorAll('section')],CAPS=TL.flatMap(s=>s.caps),ease=x=>1-Math.pow(1-Math.min(Math.max(x,0),1),3);
const cap=document.getElementById('cap'),tape=document.querySelector('#tape div'),bar=document.getElementById('bar');
const esc=s=>s.replace(/([+−-]?\\d[\\d,.]*(?:%|대|석)?)/g,'<em>$1</em>');let lastCap=null;
window.seek=t=>{
  const i=TL.findIndex(s=>t<s.end);const k=i<0?TL.length-1:i;const sc=TL[k];
  S.forEach((e,j)=>e.style.display=j===k?'flex':'none');
  const el=S[k],l=t-sc.start;document.body.style.background=el.dataset.bg||'#0B0B0D';el.style.transform=`scale(${1+.07*(1-ease(l/.16))})`;document.getElementById('flash').style.opacity=k?Math.max(0,.28*(1-l/.09)):0;
  el.querySelectorAll('.a').forEach(a=>{const p=ease((l-+(a.dataset.d||0))/.12);a.style.opacity=p;a.style.transform=`translateY(${(1-p)*24}px)`});
  el.querySelectorAll('[data-count]').forEach(n=>{const d=+(n.dataset.d||0),p=ease((l-d)/.3),v=Math.abs(+n.dataset.count)*p;n.textContent=(n.dataset.sign||'')+v.toFixed(1)+'%'});
  el.querySelectorAll('.fill').forEach(f=>{f.style.width=(+f.dataset.w*ease((l-+f.dataset.d)/.25))+'px'});
  const ln=el.querySelector('#line');if(ln){const p=ease(l/.7);ln.style.strokeDasharray=1;ln.style.strokeDashoffset=1-p;el.querySelector('#dot').style.opacity=p>.97?1:0}
  const c=CAPS.find(c=>t>=c.t&&t<c.e)||CAPS.filter(c=>c.t<=t).pop();const txt=c?c.text:'';if(txt!==lastCap){cap.innerHTML='<div>'+esc(txt)+'</div>';lastCap=txt}
  tape.style.transform=`translateX(${-(t*110)%(tape.scrollWidth/12)}px)`;bar.style.width=(t/TL[TL.length-1].end*100)+'%';
};
"""


WORKERS = min(12, max(2, (os.cpu_count() or 4) // 2))   # 화면 그리기에 쓸 크롬 수 (i9-14900K 32스레드 기준 12)
CHROME_ARGS = ["--enable-gpu-rasterization", "--ignore-gpu-blocklist", "--use-angle=d3d11"]


def render_range(job):
    """크롬 하나가 맡은 구간의 화면을 번호 붙은 그림으로 저장한다."""
    from playwright.sync_api import sync_playwright
    page_uri, start, end, frames = job
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="chrome", args=CHROME_ARGS)
        pg = b.new_page(viewport={"width": W, "height": H})
        pg.goto(page_uri)
        pg.evaluate("document.fonts.ready")
        for f in range(start, end):
            pg.evaluate(f"seek({f / FPS})")
            pg.screenshot(path=str(pathlib.Path(frames) / f"{f:05d}.jpg"), type="jpeg", quality=92)
        b.close()
    return end - start


def encode(frames, out_file):
    """그래픽카드 인코더(NVENC)로 합치고, 안 되면 CPU 인코더로 합친다."""
    base = ["ffmpeg", "-y", "-v", "error", "-framerate", str(FPS), "-i", str(frames / "%05d.jpg"), "-i", str(OUT / "voice.m4a")]
    tail = ["-pix_fmt", "yuv420p", "-c:a", "copy", "-shortest", "-movflags", "+faststart", str(out_file)]
    nvenc = ["-c:v", "h264_nvenc", "-preset", "p7", "-tune", "hq", "-rc", "vbr", "-cq", "26", "-b:v", "0", "-maxrate", "12M", "-bufsize", "24M",
             "-profile:v", "high", "-spatial-aq", "1", "-temporal-aq", "1", "-bf", "3"]
    if subprocess.run(base + nvenc + tail).returncode == 0:
        return "NVENC"
    subprocess.run(base + ["-c:v", "libx264", "-preset", "medium", "-crf", "20"] + tail, check=True)
    return "x264"


def shoot(page_file, total, video, only=None, prefix=""):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="chrome", args=CHROME_ARGS)
        pg = b.new_page(viewport={"width": W, "height": H})
        pg.goto(page_file.as_uri())
        pg.evaluate("document.fonts.ready")
        stills = OUT / "stills"
        stills.mkdir(exist_ok=True)
        tl = pg.evaluate("TL")
        problems = []
        for s in tl:
            if only and s["id"] not in only:
                continue
            pg.evaluate(f"seek({s['end'] - 0.1})")
            pg.screenshot(path=str(stills / f"{prefix}{s['id']}.jpg"), type="jpeg", quality=88)
            over = pg.evaluate("(()=>{const e=S.find(x=>x.style.display!=='none'),c=document.getElementById('cap').firstElementChild;e.querySelectorAll('.ph').forEach(p=>p.style.display='none');const r=[e.scrollHeight>e.clientHeight+2||e.scrollWidth>e.clientWidth+2,c&&c.offsetHeight>185];e.querySelectorAll('.ph').forEach(p=>p.style.display='');return r})()")
            if over[0] or over[1]:
                problems.append(f"{s['id']}: {'화면' if over[0] else ''} {'자막' if over[1] else ''} 넘침")
        b.close()
    if video:
        frames = OUT / "frames"
        shutil.rmtree(frames, ignore_errors=True)
        frames.mkdir()
        count = int(total * FPS)
        step = count // WORKERS + 1
        jobs = [(page_file.as_uri(), a, min(a + step, count), str(frames)) for a in range(0, count, step)]
        t0 = time.time()
        with ProcessPoolExecutor(max_workers=WORKERS) as pool:
            done = sum(pool.map(render_range, jobs))
        t1 = time.time()
        if done != count or len(list(frames.glob("*.jpg"))) != count:
            raise SystemExit(f"화면 {count}장 중 {done}장만 그렸어요.")
        how = encode(frames, OUT / "영상.mp4")
        print(f"화면 {count}장 {t1 - t0:.0f}초 (크롬 {WORKERS}개) · 합치기 {time.time() - t1:.0f}초 ({how})")
        shutil.rmtree(frames, ignore_errors=True)
    return problems
