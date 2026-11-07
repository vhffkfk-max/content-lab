"""사이트 '쓰레드 콘텐츠 만들기' 요청을 바로 받아 쓰는 담당 — 5초마다 요청함을 보고, 들어오면 곧장 thread_post.py 를 돌린다.

- 요청함: 저장소의 lab-requests 가지 requests/thpost/<rid>.json (relay/api/lab.js 가 넣음). main 이 아니라서 크롤러 푸시와 안 부딪혀 요청이 사라지지 않는다.
- 달라졌는지만 묻는 조건부 요청(ETag)이라 5초마다 봐도 깃허브 한도가 줄지 않고, Claude 는 요청이 있을 때만 부른다.
- 요청 파일에 받은 시각(picked)·실패 이유(error)를 적어 두면 사이트가 읽어서 보여 준다. 끝나면 파일을 지운다.
- 작업 폴더: C:\\Users\\qkreo\\content-lab-thread (local_ai.py 가 5분마다 reset 하는 폴더와 분리). 설치: thread_listen_install.ps1
로그: ~/.content-lab-ai/thread_listen.log
"""
import base64
import json
import os
import queue
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
KST = timezone(timedelta(hours=9))
REPO, BRANCH, FOLDER = "vhffkfk-max/content-lab", "lab-requests", "requests/thpost"
API = f"https://api.github.com/repos/{REPO}/contents/{FOLDER}"
POLL_S = 5
DAILY_MAX = 40          # 사이트가 암호 없이 요청을 받아서(2026-11-06) 하루 처리량을 막는다
LIMIT_STATE = Path.home() / ".content-lab-ai" / "thread_limits.json"
MAX_AGE_MIN = 20       # 사이트가 기다리는 시간과 같음. 이보다 오래된 요청은 쓰지 않고 지움
JOB_TIMEOUT_S = 10 * 60
LOG = Path.home() / ".content-lab-ai" / "thread_listen.log"
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
S = requests.Session()


def log(*a):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(KST):%m/%d %H:%M:%S} " + " ".join(str(x) for x in a) + "\n")


def login():
    """PC에 로그인된 gh 의 토큰을 씀 (파일에 따로 두지 않음)."""
    t = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, creationflags=NO_WINDOW).stdout.strip()
    S.headers.update({"Authorization": f"Bearer {t}", "Accept": "application/vnd.github+json", "User-Agent": "content-lab-thread-listen"})


def api(method, url, **kw):
    r = S.request(method, url, timeout=20, **kw)
    if r.status_code == 401:
        login()
        r = S.request(method, url, timeout=20, **kw)
    return r


def read(name):
    """요청 파일 → (내용, sha). 없으면 (None, None)."""
    r = api("GET", f"{API}/{name}", params={"ref": BRANCH})
    if r.status_code != 200:
        return None, None
    d = r.json()
    return json.loads(base64.b64decode(d["content"]).decode("utf-8")), d["sha"]


def change(name, method, message, **fields):
    """파일 고치기·지우기. 그사이 가지가 움직이면(409) 다시 시도."""
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
    log("⚠️ 요청 파일 처리 실패:", method, name, r.status_code)


def git(*a):
    ident = ["-c", "user.name=content-lab-bot", "-c", "user.email=content-lab-bot@users.noreply.github.com"]
    return subprocess.run(["git", *ident, *a], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)


def run(name, q):
    """글 쓰기 → 성공이면 요청 파일 지움, 실패면 이유를 적어 둠."""
    git("fetch", "-q", "--depth", "1", "origin", "main")
    git("reset", "-q", "--hard", "origin/main")
    git("clean", "-qfd", "output/site")
    t0 = time.time()
    try:
        p = subprocess.run([sys.executable, "thread_post.py", "--idx", str(q["idx"]), "--styles", q["styles"], "--slot", q.get("slot", ""), "--rid", q["rid"], "--push"],
                           cwd=ROOT, env=ENV, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=JOB_TIMEOUT_S, creationflags=NO_WINDOW)
        out = p.stdout + p.stderr
    except subprocess.TimeoutExpired:
        out = "⚠️ 글 쓰기가 10분 안에 안 끝났어요."
    lines = [l for l in out.strip().splitlines() if l.strip()]
    log(f"{q['rid']} {q['styles']} {time.time() - t0:.0f}초 →", " / ".join(lines[-3:])[:500])
    bad = next((l for l in lines if l.startswith("⚠️")), None)
    if bad or not any(l.startswith("✅") for l in lines):
        change(name, "PUT", "thread request failed", error=(bad or "글을 쓰다가 멈췄어요.").lstrip("⚠️ ")[:200])
    else:
        change(name, "DELETE", "thread request done")


def worker(jobs):
    while True:
        name, q = jobs.get()
        try:
            run(name, q)
        except Exception as e:
            log("⚠️", name, repr(e)[:300])
            change(name, "PUT", "thread request failed", error="PC에서 글을 쓰다가 멈췄어요. 다시 눌러 주세요.")


def over_limit():
    """오늘 받은 요청이 한도를 넘었으면 True. 받은 횟수를 센다."""
    today = datetime.now(KST).strftime("%Y%m%d")
    state = json.loads(LIMIT_STATE.read_text(encoding="utf-8")) if LIMIT_STATE.exists() else {}
    n = state.get(today, 0)
    if n >= DAILY_MAX:
        return True
    LIMIT_STATE.write_text(json.dumps({today: n + 1}), encoding="utf-8")
    return False


def poll(jobs, seen, etag):
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
            change(name, "DELETE", "thread request expired")
            continue
        if over_limit():
            log("하루 한도 넘음:", q["rid"])
            change(name, "PUT", "thread request over limit", error="오늘 처리할 수 있는 횟수를 넘었어요. 내일 다시 눌러 주세요.")
            continue
        change(name, "PUT", "thread request picked", picked=datetime.now(KST).isoformat(timespec="seconds"))   # 사이트에 '받았어요' 표시
        log("요청 받음:", q["rid"], q["styles"], f"{q['idx'] + 1}번")
        jobs.put((name, q))
    seen &= set(names)
    return r.headers.get("ETag") if r.status_code in (200, 404) else None


def main():
    LOG.parent.mkdir(parents=True, exist_ok=True)
    login()
    log("시작")
    jobs, seen, etag = queue.Queue(), set(), None
    threading.Thread(target=worker, args=(jobs,), daemon=True).start()
    while True:
        try:
            etag = poll(jobs, seen, etag)
        except Exception as e:   # 인터넷이 잠깐 끊겨도 계속
            log("⚠️", repr(e)[:300])
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
