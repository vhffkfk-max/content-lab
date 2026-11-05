"""숏폼 컷 보드: 대본과 컷 이미지를 먼저 보고 고친 뒤, 버튼을 눌렀을 때만 영상을 만든다.

    python reels/board.py      # http://127.0.0.1:8766  (내 PC에서만 열린다)

제작은 make_reel.py 를 별도 프로세스로 부른다. 한 번에 한 작업만 돌린다. 업로드는 하지 않는다.
"""
import json
import os
import pathlib
import re
import subprocess
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
import engine  # noqa: E402
import make_reel as mr  # noqa: E402

REELS = mr.REELS_DIR
PORT = 8766
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
FIELDS = ("say", "cap", "kind", "kick", "big", "ticker", "tickers", "items", "bg", "emoji")
TYPES = {".jpg": "image/jpeg", ".mp4": "video/mp4", ".wav": "audio/wav", ".txt": "text/plain; charset=utf-8"}
job = {"kind": "", "id": "", "running": False, "code": None, "log": []}
lock = threading.Lock()


def folder(name):
    """보드 폴더 이름 검사: output/reels 바로 아래만 허용한다."""
    if not re.fullmatch(r"[0-9A-Za-z가-힣_]+", name or ""):
        raise ValueError("잘못된 보드 이름")
    d = (REELS / name).resolve()
    if d.parent != REELS.resolve() or not d.is_dir():
        raise ValueError("없는 보드")
    return d


def start(kind, name, args):
    with lock:
        if job["running"]:
            return False
        job.update(kind=kind, id=name, running=True, code=None, log=[])

    def run():
        p = subprocess.Popen([sys.executable, str(HERE / "make_reel.py"), *args], cwd=HERE.parent, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        for line in p.stdout:
            job["log"] = (job["log"] + [line.rstrip()[:240]])[-14:]
            m = re.match(r"폴더: .*[\\/]([^\\/]+)$", line.strip())
            if m:
                job["id"] = m[1]
        job.update(code=p.wait(), running=False)

    threading.Thread(target=run, daemon=True).start()
    return True


def boards():
    out = []
    for d in sorted((x for x in REELS.iterdir() if x.is_dir() and (x / "board.json").exists()), key=lambda x: x.stat().st_mtime, reverse=True):
        st = mr.load_state(d)
        b = json.loads((d / "board.json").read_text(encoding="utf-8"))
        out.append({"id": d.name, "topic": st.get("topic", d.name), "updated": b.get("updated", ""), "video": bool(b.get("video")), "blocked": bool(b.get("block"))})
    return out


def detail(name):
    d = folder(name)
    st, b = mr.load_state(d), json.loads((d / "board.json").read_text(encoding="utf-8"))
    s, q = mr.Script(**st["script"]), st.get("quotes") or {}
    ok = lambda t: not any(n not in q for n in mr.PH.findall(t))
    cuts = []
    for i, c in enumerate(s.cuts, 1):
        img = d / "stills" / f"c{i}.jpg"
        cuts.append({**c.model_dump(), "say_text": mr.to_say(c.say, q).replace("*", "") if ok(c.say) else c.say, "cap_text": mr.to_text(c.cap, q) if ok(c.cap) else c.cap,
                     "image": f"/file/{urllib.parse.quote(name)}/stills/c{i}.jpg?v={int(img.stat().st_mtime)}" if img.exists() else ""})
    extra = {k: getattr(s, k) for k in ("ig_title", "yt_title", "summary", "question", "hashtags")}
    video = d / "영상.mp4"
    return {"id": name, "topic": st["topic"], "edited": st.get("edited", False), "cuts": cuts, "board": b, **extra, "names": list(q),
            "video_url": f"/file/{urllib.parse.quote(name)}/{urllib.parse.quote('영상.mp4')}?v={int(video.stat().st_mtime)}" if video.exists() and b.get("video") else "",
            "upload": (d / "업로드글.txt").read_text(encoding="utf-8") if (d / "업로드글.txt").exists() and b.get("video") else "",
            "sources": [{"source": r.get("source", ""), "title": r["title"], "link": r.get("link", "")} for r in st.get("news", [])[:12]]}


def save(body):
    d = folder(body["id"])
    st = mr.load_state(d)
    script = st["script"]
    cuts = []
    for c in body["cuts"]:
        cut = {k: c.get(k) for k in FIELDS if k in c}
        cut["big"] = cut.get("big") or ""
        cuts.append(mr.Cut(**cut).model_dump())
    if not cuts:
        raise ValueError("컷이 하나는 있어야 해요")
    script["cuts"] = cuts
    for k in ("ig_title", "yt_title", "question"):
        if isinstance(body.get(k), str):
            script[k] = body[k]
    mr.save_state(d, script=script, edited=True, review=[])
    mr.write_board(d, video=False)
    return start("stills", d.name, ["--stills", str(d / "대본.json")])


def voice(body):
    d = folder(body["id"])
    st = mr.load_state(d)
    cut = mr.Script(**st["script"]).cuts[int(body["cut"])]
    pv = d / "preview"
    pv.mkdir(exist_ok=True)
    engine.speak_all([mr.to_say(cut.say, st.get("quotes") or {})], pv)
    return f"/file/{urllib.parse.quote(d.name)}/preview/01.wav?v={os.urandom(3).hex()}"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, data, kind="application/json; charset=utf-8", code=200):
        if not isinstance(data, bytes):
            data = (data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def local_only(self):
        """다른 사이트가 내 PC의 작업을 몰래 시키지 못하게 한다."""
        hosts = (f"127.0.0.1:{PORT}", f"localhost:{PORT}")
        origin = self.headers.get("Origin")
        return self.headers.get("Host") in hosts and (origin is None or origin in [f"http://{h}" for h in hosts])

    def do_GET(self):
        if not self.local_only():
            return self.send({"error": "내 PC에서만 열 수 있어요"}, code=403)
        url = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(url.query)
        try:
            if url.path == "/":
                return self.send((HERE / "board.html").read_bytes(), "text/html; charset=utf-8")
            if url.path == "/api/boards":
                return self.send(boards())
            if url.path == "/api/board":
                return self.send(detail(qs.get("id", [""])[0]))
            if url.path == "/api/job":
                return self.send(job)
            if url.path.startswith("/file/"):
                parts = [urllib.parse.unquote(x) for x in url.path.split("/")[2:]]
                base = folder(parts[0])
                f = base.joinpath(*parts[1:]).resolve()
                if base not in f.parents or f.suffix not in TYPES or not f.is_file():
                    return self.send({"error": "없는 파일"}, code=404)
                return self.send(f.read_bytes(), TYPES[f.suffix])
            self.send({"error": "없는 주소"}, code=404)
        except (ValueError, OSError, KeyError) as e:
            self.send({"error": str(e)}, code=400)

    def do_POST(self):
        if not self.local_only():
            return self.send({"error": "내 PC에서만 쓸 수 있어요"}, code=403)
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if self.path == "/api/new":
                topic = re.sub(r"\s+", " ", str(body.get("topic", ""))).strip()[:60]
                if len(topic) < 2:
                    raise ValueError("주제를 2글자 이상 넣어 주세요")
                return self.send({"started": start("board", "", [topic, "--board"])})
            if self.path == "/api/save":
                return self.send({"started": save(body)})
            if self.path == "/api/make":
                d = folder(body["id"])
                return self.send({"started": start("video", d.name, ["--from-script", str(d / "대본.json")] + (["--accept-market"] if body.get("accept") else []))})
            if self.path == "/api/voice":
                return self.send({"url": voice(body)})
            self.send({"error": "없는 주소"}, code=404)
        except (ValueError, KeyError, IndexError, TypeError, OSError, subprocess.SubprocessError) as e:
            self.send({"error": str(e)}, code=400)


if __name__ == "__main__":
    print(f"컷 보드: http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
