"""컷 보드 → 저장소 reel-previews 가지 (연구소 사이트 '영상 연구소'가 보여 줌).

- 가지에는 커밋을 하나만 둔다(부모 없는 커밋을 덮어씀). 지난 그림이 기록에 쌓이지 않아 저장소가 안 커진다.
- 폭 540px 그림과 대본만 올린다. 영상 파일과 기사 본문은 올리지 않는다 (영상은 텔레그램으로 보낸다).
- 공개 저장소라 주소를 알면 볼 수 있다. 사이트 목록은 암호 뒤에 있지만 그림 자체는 비공개가 아니다.
"""
import hashlib
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta

from PIL import Image

HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
import formats  # noqa: E402
import make_reel as mr  # noqa: E402
from common import ROOT  # noqa: E402

BRANCH = "reel-previews"
WIDTH, QUALITY = 540, 74
KEEP_DAYS, KEEP_BOARDS = 10, 20
AUTO_TIMES = ["08:40", "12:10", "16:10"]   # reel_listen.py 가 이 시각에 추천 1위로 보드를 미리 만든다
IDENT = ["-c", "user.name=content-lab-bot", "-c", "user.email=content-lab-bot@users.noreply.github.com"]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
TEXT_LIMIT = 240


def git(*args, env=None, data=None):
    r = subprocess.run(["git", *IDENT, *args], cwd=ROOT, capture_output=True, input=data, env=env, creationflags=NO_WINDOW)
    if r.returncode:
        raise RuntimeError(r.stderr.decode("utf-8", "ignore")[-300:])
    return r.stdout.decode("utf-8", "ignore").strip()


def small(path):
    im = Image.open(path).convert("RGB")
    im = im.resize((WIDTH, round(im.height * WIDTH / im.width)), Image.LANCZOS)
    b = io.BytesIO()
    im.save(b, "JPEG", quality=QUALITY, optimize=True)
    return b.getvalue()


def site_video(d):
    """사이트에서 볼 720p 영상 (원본 약 20MB → 3~5MB). 원본이 바뀌었을 때만 다시 만든다."""
    src, out = d / "영상.mp4", d / "preview" / "site.mp4"
    if not src.exists():
        return None
    if not out.exists() or out.stat().st_mtime < src.stat().st_mtime:
        out.parent.mkdir(exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", "scale=720:-2", "-c:v", "libx264", "-preset", "slow", "-crf", "29",
                        "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(out)], check=True, creationflags=NO_WINDOW)
    return out


def view(d):
    """사이트가 읽을 보드 내용과 올릴 파일들."""
    st, b = mr.load_state(d), json.loads((d / "board.json").read_text(encoding="utf-8"))
    s, q = mr.Script(**st["script"]), st.get("quotes") or {}
    known = lambda t: not any(n not in q for n in mr.PH.findall(t))
    files, cuts = {}, []
    for i, c in enumerate(s.cuts, 1):
        img = d / "stills" / f"c{i}.jpg"
        name = None
        if img.exists():
            data = small(img)
            name = f"{d.name}/c{i}.jpg"
            files[name] = data
        voice = d / "preview" / f"v{i - 1}.mp3"
        fresh = voice.exists() and voice.stat().st_mtime > (d / "대본.json").stat().st_mtime
        if fresh:
            files[f"{d.name}/v{i - 1}.mp3"] = voice.read_bytes()
        cuts.append({"kind": c.kind, "say": c.say, "cap": c.cap, "kick": c.kick, "big": c.big.replace("\\n", "\n"), "items": c.items,
                     "say_text": mr.to_say(c.say, q).replace("*", "") if known(c.say) else c.say,
                     "image": name, "v": hashlib.md5(files[name]).hexdigest()[:8] if name else "", "voice": f"{d.name}/v{i - 1}.mp3" if fresh else None})
    fmt = st.get("format") or formats.DEFAULT
    samples = []
    for key, (name, why, _) in formats.FORMATS.items():
        imgs = []
        for cid in b.get("samples") or ["c1"]:
            f = d / "stills" / f"fmt-{key}-{cid}.jpg"
            if f.exists():
                data = small(f)
                files[f"{d.name}/fmt-{key}-{cid}.jpg"] = data
                imgs.append({"path": f"{d.name}/fmt-{key}-{cid}.jpg", "v": hashlib.md5(data).hexdigest()[:8]})
        samples.append({"key": key, "name": name, "why": why, "images": imgs})
    upload = d / "업로드글.txt"
    video = site_video(d) if b.get("video") else None
    if video:
        files[f"{d.name}/video.mp4"] = video.read_bytes()
    board = {"id": d.name, "topic": st["topic"], "edited": st.get("edited", False), "cuts": cuts, "board": {k: b.get(k) for k in ("updated", "basis", "block", "problems", "seconds", "hooks", "changes", "video", "miss", "rid", "caption", "auto")},
             "ig_title": s.ig_title, "yt_title": s.yt_title, "summary": s.summary, "question": s.question,
             "format": fmt, "formats": samples, "photo_count": sum(1 for p in (st.get("photos") or []) if p),
             "video_file": f"{d.name}/video.mp4" if video else None, "video_v": hashlib.md5(files[f"{d.name}/video.mp4"]).hexdigest()[:8] if video else "",
             "upload": upload.read_text(encoding="utf-8") if b.get("video") and upload.exists() else "",
             "sources": [{"source": r.get("source", ""), "title": r["title"], "link": r.get("link", "")} for r in st.get("news", [])[:12]]}
    files[f"{d.name}/board.json"] = json.dumps(board, ensure_ascii=False).encode("utf-8")
    item = {"id": d.name, "topic": st["topic"], "updated": b.get("updated", ""), "video": bool(b.get("video")), "blocked": bool(b.get("block") or b.get("problems")), "rid": b.get("rid", ""), "auto": bool(b.get("auto"))}
    return item, files


def recent():
    cutoff = f"{datetime.now() - timedelta(days=KEEP_DAYS):%Y%m%d}"
    out = [x for x in mr.REELS_DIR.iterdir() if x.is_dir() and (x / "board.json").exists() and (x / "대본.json").exists() and x.name[:8] >= cutoff]
    return sorted(out, key=lambda x: x.stat().st_mtime, reverse=True)[:KEEP_BOARDS]


def push():
    """보드 전체를 부모 없는 커밋 하나로 만들어 가지를 덮어쓴다 (이 가지는 이 프로그램만 쓴다)."""
    items, blobs = [], {}
    for d in recent():
        item, files = view(d)
        items.append(item)
        blobs.update(files)
    try:
        sug = json.loads((mr.REELS_DIR / "suggest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        sug = {"items": []}
    suggest = [{k: r.get(k, "") for k in ("keyword", "title", "why", "at", "from")} for r in sug.get("items", [])]
    blobs["index.json"] = json.dumps({"boards": items, "suggest": suggest, "suggest_updated": sug.get("updated", ""), "auto_times": AUTO_TIMES}, ensure_ascii=False).encode("utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": os.path.join(tmp, "index")}
        for path, data in blobs.items():
            sha = git("hash-object", "-w", "--stdin", data=data)
            git("update-index", "--add", "--cacheinfo", f"100644,{sha},{path}", env=env)
        tree = git("write-tree", env=env)
    commit = git("commit-tree", tree, "-m", f"reel previews {datetime.now():%m/%d %H:%M}")
    git("push", "-q", "-f", "origin", f"{commit}:refs/heads/{BRANCH}")
    return f"보드 {len(items)}개"


def apply_edit(d, payload):
    """사이트에서 고친 대본 반영. 글자만 바꿀 수 있고, 컷 종류·종목은 원래 컷의 값을 그대로 쓴다."""
    st = mr.load_state(d)
    old = st["script"]["cuts"]
    cuts = []
    for row in payload:
        base = dict(old[int(row["i"])])
        for k in ("say", "cap", "kick", "big"):
            if k in row:
                base[k] = re.sub(r"[\x00-\x09\x0b-\x1f]", "", str(row[k]))[:TEXT_LIMIT].strip()
        if "big" in row:
            base["big"] = base["big"].replace("\n", "\\n")
        if "items" in row:
            base["items"] = [str(x)[:60].strip() for x in row["items"]][:3]
        cuts.append(mr.Cut(**base).model_dump())
    if not 1 <= len(cuts) <= 20:
        raise ValueError("컷은 1~20개여야 해요")
    st["script"]["cuts"] = cuts
    old_photos = st.get("photos")
    photos = [old_photos[int(row["i"])] if old_photos and int(row["i"]) < len(old_photos) else None for row in payload] if old_photos is not None else None
    mr.save_state(d, script=st["script"], edited=True, review=[], photos=photos)
    mr.write_board(d, video=False)


if __name__ == "__main__":
    print(push())
