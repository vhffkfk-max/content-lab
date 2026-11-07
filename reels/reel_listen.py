"""사이트 '영상 연구소' 요청을 바로 받아 처리하는 담당. 5초마다 요청함을 보고, 들어오면 곧장 만든다.

- 요청함: lab-requests 가지 requests/reel/<rid>.json (relay/api/lab.js 가 형식을 확인해 넣음).
- 일: board(대본·컷 이미지) · save(글자 고치고 컷 다시 그리기) · voice(한 컷 듣기) · make(영상).
- 달라졌는지만 묻는 조건부 요청(ETag)이라 5초마다 봐도 깃허브 한도가 줄지 않고, Claude 는 요청이 있을 때만 부른다.
- 결과는 reel-previews 가지로(reels/preview.py), 영상은 텔레그램으로 보낸다. 플랫폼 업로드는 하지 않는다.
- 작업 폴더: ~/content-lab-reel (local_ai.py 가 5분마다 reset 하는 폴더와 분리). 설치: reels/reel_listen_install.ps1
로그: ~/.content-lab-ai/reel_listen.log
"""
import base64
import json
import os
import pathlib
import queue
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

import requests

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(HERE), str(ROOT)]
KST = timezone(timedelta(hours=9))
REPO, BRANCH, FOLDER = "vhffkfk-max/content-lab", "lab-requests", "requests/reel"
API = f"https://api.github.com/repos/{REPO}/contents/{FOLDER}"
POLL_S = 5
MAX_AGE_MIN = 30
JOB_TIMEOUT_S = 20 * 60
LOG = pathlib.Path.home() / ".content-lab-ai" / "reel_listen.log"
DEV_ENV = pathlib.Path.home() / "Desktop" / "솔개" / "insta-research" / ".env"
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
S = requests.Session()


def log(*a):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(KST):%m/%d %H:%M:%S} " + " ".join(str(x) for x in a) + "\n")


def login():
    """PC에 로그인된 gh 의 토큰을 씀 (파일에 따로 두지 않음)."""
    t = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, creationflags=NO_WINDOW).stdout.strip()
    S.headers.update({"Authorization": f"Bearer {t}", "Accept": "application/vnd.github+json", "User-Agent": "content-lab-reel-listen"})


def api(method, url, **kw):
    r = S.request(method, url, timeout=20, **kw)
    if r.status_code == 401:
        login()
        r = S.request(method, url, timeout=20, **kw)
    return r


def read(name):
    r = api("GET", f"{API}/{name}", params={"ref": BRANCH})
    if r.status_code != 200:
        return None, None
    d = r.json()
    return json.loads(base64.b64decode(d["content"]).decode("utf-8")), d["sha"]


def change(name, method, message, **fields):
    for _ in range(4):
        data, sha = read(name)
        if sha is None:
            return
        body = {"message": message, "branch": BRANCH, "sha": sha}
        if method == "PUT":
            body["content"] = base64.b64encode(json.dumps({**data, **fields}, ensure_ascii=False).encode("utf-8")).decode("ascii")
        r = api(method, f"{API}/{name}", json=body)
        if r.status_code in (200, 201):
            return
        time.sleep(1)
    log("요청 파일 처리 실패:", method, name, r.status_code)


def git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)


def maker(*args):
    """make_reel.py 실행 → (종료코드, 줄들)."""
    try:
        p = subprocess.run([sys.executable, str(HERE / "make_reel.py"), *args], cwd=ROOT, env=ENV, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=JOB_TIMEOUT_S, creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        return 1, ["20분 안에 끝나지 않았어요."]
    return p.returncode, [x for x in (p.stdout + p.stderr).splitlines() if x.strip()]


def plain(lines):
    """오류 줄 가운데 사람이 읽을 마지막 한 줄."""
    good = [x for x in lines if re.search(r"[가-힣]", x) and not x.startswith(("Traceback", "  File"))]
    return (good[-1] if good else "PC에서 만들다가 멈췄어요. 다시 눌러 주세요.").strip()[:200]


def folder(name):
    """요청에 적힌 보드 이름 검사: 보드 폴더 바로 아래만 허용한다."""
    import make_reel as mr
    if not re.fullmatch(r"[0-9A-Za-z가-힣_]+", name or ""):
        raise ValueError("잘못된 보드 이름")
    d = (mr.REELS_DIR / name).resolve()
    if d.parent != mr.REELS_DIR.resolve() or not (d / "대본.json").exists():
        raise ValueError("없는 보드예요")
    return d


def send_video(d):
    from publish.notify import send, send_video as tg_video
    upload = d / "업로드글.txt"
    ok = tg_video(d / "영상.mp4", f"릴스·쇼츠 영상이 나왔어요: {json.loads((d / '대본.json').read_text(encoding='utf-8'))['topic']}\n확인한 뒤 직접 올려 주세요.")
    if ok and upload.exists():
        send(upload.read_text(encoding="utf-8"))
    return ok


HOT_MAKER = pathlib.Path.home() / "Desktop" / "솔개" / "hotconomy-reels" / "src" / "auto.py"   # 핫코노미 전용 영상 버전 A (PC에만 있는 제작기)


def hot_video(q):
    """핫코노미 A: 주제 → 기사 → 대본(사실 검사) → 영상 → 텔레그램. 실패하면 사람이 읽을 한 줄을 돌려준다."""
    import suggest
    from publish.notify import send, send_video as tg_video
    seeds = q.get("seeds") or suggest.seed_for(q["topic"])
    args = [sys.executable, str(HOT_MAKER), q["topic"], "--lab", str(ROOT)]
    if seeds:
        f = pathlib.Path.home() / ".content-lab-ai" / "hot_seed.json"
        f.write_text(json.dumps(seeds), encoding="utf-8")
        args += ["--seed", str(f)]
    try:
        p = subprocess.run(args, cwd=HOT_MAKER.parent.parent, env=ENV, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=JOB_TIMEOUT_S, creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        return "20분 안에 끝나지 않았어요."
    lines = [x for x in (p.stdout + p.stderr).splitlines() if x.strip()]
    found = next((x for x in lines if x.startswith("완성: ")), None)
    if p.returncode or not found:
        return plain(lines)
    video = pathlib.Path(found[4:].strip())
    upload = video.with_name(video.stem + "_업로드글.txt")
    if not tg_video(video, f"핫코노미 A 영상이 나왔어요: {q['topic']}\n확인한 뒤 직접 올려 주세요."):
        return "영상은 만들었지만 텔레그램 전송에 실패했어요. 바탕화면 릴스 완성영상 폴더에서 확인해 주세요."
    if upload.exists():
        send(upload.read_text(encoding="utf-8"))
    return None


def run(name, q):
    import make_reel as mr
    import preview
    action, t0, msg, out = q["action"], time.time(), None, None
    if action == "board":
        import suggest
        seeds = q.get("seeds") or suggest.seed_for(q["topic"])
        extra = []
        if seeds:
            f = mr.REELS_DIR / "seed.json"
            f.write_text(json.dumps(seeds), encoding="utf-8")
            extra = ["--seed", str(f)]
        code, lines = maker(q["topic"], "--board", *extra, *(["--auto"] if q.get("auto") else []))
        found = next((x for x in lines if x.startswith("폴더: ")), None)
        if code or not found:
            msg = plain(lines)
        else:
            out = pathlib.Path(found[4:].strip())
            mr.write_board(out, rid=q["rid"])
    elif action == "hot":
        msg = hot_video(q)
    else:
        out = folder(q["id"])
        mr.write_board(out, rid=q["rid"])
        script = str(out / "대본.json")
        if action == "save":
            preview.apply_edit(out, q["cuts"])
            code, lines = maker("--stills", script)
            msg = plain(lines) if code else None
        elif action == "photo":
            import base64 as b64
            import io
            import formats
            from PIL import Image
            st = mr.load_state(out)
            cut = int(q["cut"])
            photos = list(st.get("photos") or [None] * len(st["script"]["cuts"]))
            if not 0 <= cut < len(photos):
                raise ValueError("없는 컷")
            op = q.get("op")
            if op == "search":
                items = formats.candidates(q.get("query", "")[:80])
                mr.save_state(out, candidates={"cut": cut, "query": q.get("query", ""), "items": items, "at": datetime.now(KST).strftime("%H:%M")})
                if not items:
                    msg = "위키미디어 공용에서 상업 이용이 되는 사진을 찾지 못했어요. 다른 검색어(영어)로 찾거나 직접 올려 주세요."
            else:
                if op == "pick":
                    pick = next((x for x in (st.get("candidates") or {}).get("items", []) if x["url"] == q.get("url")), None)
                    if not pick:
                        raise ValueError("후보에 없는 사진")
                    photos[cut] = formats.full(pick)
                elif op == "remove":
                    photos[cut] = None
                elif op == "upload":
                    raw = b64.b64decode(q.get("data", ""), validate=True)
                    if len(raw) > 4_000_000:
                        raise ValueError("사진이 너무 커요")
                    img = Image.open(io.BytesIO(raw))
                    img.verify()
                    img = Image.open(io.BytesIO(raw)).convert("RGB")
                    img.thumbnail((1800, 1800))
                    up = out / "user_photos"
                    up.mkdir(exist_ok=True)
                    f = up / f"cut{cut}_{q['rid']}.jpg"
                    img.save(f, "JPEG", quality=88)
                    photos[cut] = {"uri": f.as_uri(), "url": f"user:{f.name}", "credit": "", "page": "", "user": True}   # 사용권은 올린 사람 책임 (출처 표시 안 함)
                else:
                    raise ValueError("모르는 사진 작업")
                mr.save_state(out, photos=photos)
                mr.write_board(out, video=False)
                code, lines = maker("--stills", script, "--cut", str(cut))   # 바꾼 컷만 다시 그린다
                msg = plain(lines) if code else None
        elif action == "format":
            import formats
            if q.get("format") not in formats.FORMATS:
                raise ValueError("모르는 형식")
            mr.save_state(out, format=q["format"])
            mr.write_board(out, video=False)
            code, lines = maker("--stills", script)
            msg = plain(lines) if code else None
        elif action == "voice":
            import engine
            st = mr.load_state(out)
            cut = int(q["cut"])
            say = mr.Script(**st["script"]).cuts[cut].say
            pv = out / "preview"
            pv.mkdir(exist_ok=True)
            engine.speak_all([mr.to_say(say, st.get("quotes") or {})], pv)
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(pv / "01.wav"), "-c:a", "libmp3lame", "-b:a", "96k", str(pv / f"v{cut}.mp3")], check=True, creationflags=NO_WINDOW)
        elif action == "make":
            code, lines = maker("--from-script", script, *(["--accept-market"] if q.get("accept") else []))
            if code == 0:
                if not send_video(out):
                    msg = "영상은 만들었지만 텔레그램 전송에 실패했어요. PC 폴더에서 확인해 주세요."
            elif code not in (3, 4):   # 3 시세 바뀜, 4 사실 대조 문제: 보드에 표시된다
                msg = plain(lines)
        else:
            raise ValueError("모르는 요청")
    if out:
        if action == "board":
            import suggest
            suggest.save()   # 방금 만든 주제가 추천 칩에 남아 있지 않게
        with PUSH_LOCK:   # 두 줄이 동시에 가지를 덮어쓰지 않게
            log("미리보기:", preview.push())
    log(q["rid"], action, f"{time.time() - t0:.0f}초", msg or "완료")
    if name is None:   # PC가 스스로 만든 일 (요청 파일 없음)
        return
    if msg:
        change(name, "PUT", "reel request failed", error=msg)
    else:
        change(name, "DELETE", "reel request done")


FAST = ("save", "voice", "format", "photo")   # 몇 초~수십 초 걸리는 일: 보드·영상(몇 분)을 기다리지 않게 따로 줄을 세운다
PUSH_LOCK = threading.Lock()


def worker(jobs, fresh=True):
    """fresh: 일감 전에 저장소 최신으로 맞추기. 짧은 일 줄은 긴 일이 쓰는 파일을 건드리지 않게 맞추지 않는다."""
    while True:
        name, q = jobs.get()
        try:
            if fresh:
                git("fetch", "-q", "--depth", "1", "origin", "main")
                git("reset", "-q", "--hard", "origin/main")
                git("clean", "-qfd", "output/site")
            run(name, q)
        except Exception as e:
            log("오류", name, repr(e)[:400])
            if name:
                change(name, "PUT", "reel request failed", error="PC에서 만들다가 멈췄어요. 다시 눌러 주세요.")


def poll(lines, seen, etag):
    r = api("GET", API, params={"ref": BRANCH}, headers={"If-None-Match": etag} if etag else {})
    if r.status_code == 304:
        return etag
    names = [f["name"] for f in r.json() if f["name"].endswith(".json")] if r.status_code == 200 else []
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        q, _ = read(name)
        if not q:
            continue
        old = datetime.now(KST) - datetime.fromisoformat(q["at"]) > timedelta(minutes=MAX_AGE_MIN)
        if old or q.get("error"):   # PC가 꺼져 있던 사이 쌓인 요청·지난 실패 기록
            change(name, "DELETE", "reel request expired")
            continue
        if not q.get("auto") and over_limit(q.get("action", "")):
            log("하루 한도 넘음:", q["rid"], q.get("action"))
            change(name, "PUT", "reel request over limit", error="오늘 처리할 수 있는 횟수를 넘었어요. 내일 다시 눌러 주세요.")
            continue
        change(name, "PUT", "reel request picked", picked=datetime.now(KST).isoformat(timespec="seconds"))
        log("요청 받음:", q["rid"], q["action"])
        (lines[1] if q["action"] in FAST else lines[0]).put((name, q))
    seen &= set(names)
    return r.headers.get("ETag") if r.status_code in (200, 404) else None


AUTO_STATE = pathlib.Path.home() / ".content-lab-ai" / "reel_auto.json"
LIMIT_STATE = pathlib.Path.home() / ".content-lab-ai" / "reel_limits.json"
DAILY = {"board": 15, "make": 12, "hot": 10, "save": 150, "voice": 150, "format": 150, "photo": 200}   # 사이트 요청은 암호가 없어서 하루 처리량을 막는다 (자동 보드는 따로)


def over_limit(action):
    """오늘 이 일을 너무 많이 받았으면 True. 받은 횟수를 센다."""
    today = datetime.now(KST).strftime("%Y%m%d")
    state = json.loads(LIMIT_STATE.read_text(encoding="utf-8")) if LIMIT_STATE.exists() else {}
    counts = state.get(today, {})
    if counts.get(action, 0) >= DAILY.get(action, 0):
        return True
    counts[action] = counts.get(action, 0) + 1
    LIMIT_STATE.write_text(json.dumps({today: counts}), encoding="utf-8")
    return False
SUGGEST_EVERY_S = 30 * 60


def auto_due():
    """정해진 시각(preview.AUTO_TIMES)이 지났고 오늘 아직 안 만든 차례 하나. PC가 꺼져 있다 켜지면 2시간 안의 차례만."""
    import preview
    now = datetime.now(KST)
    state = json.loads(AUTO_STATE.read_text(encoding="utf-8")) if AUTO_STATE.exists() else {}
    done = state.get(now.strftime("%Y%m%d"), [])
    for hhmm in preview.AUTO_TIMES:
        h, m = map(int, hhmm.split(":"))
        at = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if hhmm not in done and at <= now < at + timedelta(hours=2):
            state = {now.strftime("%Y%m%d"): done + [hhmm]}
            AUTO_STATE.write_text(json.dumps(state), encoding="utf-8")
            return hhmm
    return None


def refresh(jobs):
    """추천 주제 새로 고르기 (Claude 호출 없음) + 정해진 시각이면 추천 1위로 보드 미리 만들기."""
    import preview
    import suggest
    git("fetch", "-q", "--depth", "1", "origin", "main")
    git("reset", "-q", "--hard", "origin/main")
    rows, changed = suggest.save()
    slot = auto_due()
    if slot and rows:
        top = rows[0]
        log("자동 보드:", slot, top["keyword"])
        rid = f"auto{datetime.now(KST):%m%d%H%M}"
        body = {"rid": rid, "action": "board", "topic": top["keyword"], "seeds": top["links"], "auto": True, "at": datetime.now(KST).isoformat(timespec="seconds")}
        r = api("PUT", f"{API}/{rid}.json", json={"message": "reel auto board", "branch": BRANCH,   # 사이트 진행 목록에 보이게 요청함에 넣는다
                                                   "content": base64.b64encode(json.dumps(body, ensure_ascii=False).encode("utf-8")).decode("ascii")})
        if r.status_code not in (200, 201):
            log("자동 보드 요청 실패:", r.status_code)
            jobs.put((None, body))
    elif changed:
        with PUSH_LOCK:
            log("추천 갱신:", ", ".join(r["keyword"] for r in rows), preview.push())


def main():
    if ROOT.name != "content-lab-reel":   # 일감마다 reset --hard 를 하므로 개발 폴더에서 돌면 작업 중인 코드가 사라진다
        sys.exit("전용 폴더(content-lab-reel)에서만 실행해요: reels/reel_listen_install.ps1")
    from common import load_env
    LOG.parent.mkdir(parents=True, exist_ok=True)
    load_env()
    load_env(DEV_ENV)   # 이 폴더는 저장소 복사본이라 .env 가 없다 (텔레그램 봇 설정)
    login()
    log("시작")
    jobs, quick, seen, etag = queue.Queue(), queue.Queue(), set(), None
    threading.Thread(target=worker, args=(jobs,), daemon=True).start()
    threading.Thread(target=worker, args=(quick, False), daemon=True).start()
    last = 0
    while True:
        try:
            etag = poll((jobs, quick), seen, etag)
            if jobs.empty() and (time.time() - last > SUGGEST_EVERY_S or auto_peek()):
                last = time.time()
                refresh(jobs)
        except Exception as e:   # 인터넷이 잠깐 끊겨도 계속
            log("오류", repr(e)[:300])
        time.sleep(POLL_S)


def auto_peek():
    """차례가 왔는지만 본다 (상태는 바꾸지 않음)."""
    import preview
    now = datetime.now(KST)
    done = (json.loads(AUTO_STATE.read_text(encoding="utf-8")) if AUTO_STATE.exists() else {}).get(now.strftime("%Y%m%d"), [])
    for hhmm in preview.AUTO_TIMES:
        h, m = map(int, hhmm.split(":"))
        at = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if hhmm not in done and at <= now < at + timedelta(hours=2):
            return True
    return False


if __name__ == "__main__":
    main()
