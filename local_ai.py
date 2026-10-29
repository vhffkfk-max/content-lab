"""내 PC에서 5분마다 도는 'Claude 작업 담당' — 깃허브 대신 Max 구독(Claude Code)으로 글·분석을 쓰고 푸시한다.

작업 전용 폴더(C:\\Users\\qkreo\\content-lab-ai, 저장소 복사본)에서 돈다. 개발 폴더는 건드리지 않는다.
설치: powershell -ExecutionPolicy Bypass -File local_ai_install.ps1   (작업 스케줄러 content-lab-ai)

매번 하는 일
  1) 저장소 최신으로 맞춤 (작업 폴더라 로컬 변경은 버림)
  2) 깃허브가 남긴 요청(data/ai_requests.json) 처리: daily·social·tg·trd·draft
  3) 정해진 시각 일: 텔레그램 문구(07·12·18시), 트레이더스 글(07·18시), 시황 변환, 트레이더스 피드백
  4) 결과 파일만 커밋·푸시 → 깃허브가 사이트를 다시 배포
로그: data/local_ai.log
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KST = timezone(timedelta(hours=9))
STATE = Path.home() / ".content-lab-ai" / "state.json"
LOCK = Path.home() / ".content-lab-ai" / "lock"
LOG = ROOT / "data" / "local_ai.log"
SITE = "output/site/"
OUTPUTS = [SITE + f for f in ("tg_ai.json", "tg_rewrites.json", "trd_rooms.json", "trd_posts.json", "drafts.json",
                               "imports.json", "threads_ai.json", "x_ai.json", "thm_ai.json")] + ["data/publish_queue.json"]
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}


def log(*a):
    line = f"{datetime.now(KST):%m/%d %H:%M:%S} " + " ".join(str(x) for x in a)
    print(line)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def git(*a, check=True):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=check)


def py(*a, timeout=40 * 60):
    """하위 프로그램 실행 → 종료 코드. 출력은 로그에 마지막 몇 줄만."""
    try:
        p = subprocess.run([sys.executable, *a], cwd=ROOT, env=ENV, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        log("⏱️ 시간 초과:", *a)
        return 1
    tail = [l for l in (p.stdout + p.stderr).strip().splitlines() if l.strip()][-3:]
    log(f"{'✓' if p.returncode in (0, 3) else '✗'} {' '.join(a)} →", " / ".join(tail)[:500])
    return p.returncode


def refresh_news(done=[]):
    """오늘 뉴스 새로 (텔레그램·트레이더스 글 재료). 한 번 실행에 한 번만. 결과는 커밋하지 않음."""
    if done:
        return
    done.append(1)
    for s in ("press_collect.py", "google_collect.py"):
        py(s)
    py("analyze.py", "--no-open")
    py("export_site.py")


def slot_once(state, key, hours):
    """정해진 시각(07·12·18시 등)마다 한 번만 시도 — 뉴스가 그대로라 건너뛴 경우에도 5분마다 다시 모으지 않게."""
    now = datetime.now(KST)
    passed = [h for h in hours if now.hour >= h]
    if not passed:
        return False
    slot = f"{now:%Y-%m-%d}-{passed[-1]}"
    if state.get(key) == slot:
        return False
    state[key] = slot
    return True


def run_cycle():
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"done": []}
    reqs = json.loads((ROOT / "data" / "ai_requests.json").read_text(encoding="utf-8")) if (ROOT / "data" / "ai_requests.json").exists() else []
    if not STATE.exists():   # 처음 설치: 지난 요청은 건너뜀
        state["done"] = [r["id"] for r in reqs]
    todo = [r for r in reqs if r["id"] not in state["done"]]
    latest = {r["job"]: r for r in todo}   # 같은 일은 마지막 요청 하나만 (draft 는 주제별로 따로)
    did = []

    if "daily" in latest:
        py("analyze.py", "--no-open")   # output/report.json 은 저장소에 없어서 PC에서 새로 만듦
        for s in ("generate_drafts.py", "import_ideas.py", "threads_analyze.py", "x_analyze.py", "threads_mine_analyze.py"):
            py(s)
        did.append("매일 분석")
    elif "social" in latest:
        for s in ("threads_analyze.py", "x_analyze.py", "threads_mine_analyze.py"):
            py(s)
        did.append("쓰레드·X 분석")

    if "tg" in latest:
        refresh_news()
        focus = latest["tg"]["args"].get("focus", "")
        py("tg_analyze.py", "--force", *(["--focus", focus] if focus else []))
        did.append("텔레그램 문구(요청)")
    elif slot_once(state, "tg", (7, 12, 18)) and py("tg_analyze.py", "--due") == 0:
        refresh_news()
        py("tg_analyze.py", "--scheduled")
        did.append("텔레그램 문구")

    if "trd" in latest:
        refresh_news()
        py("trd_posts.py", "--force")
        did.append("트레이더스 글(요청)")
    elif slot_once(state, "trd", (7, 18)) and py("trd_posts.py", "--due") == 0:
        refresh_news()
        py("trd_posts.py")
        did.append("트레이더스 글")

    py("tg_rewrite.py")              # 새 시황이 있을 때만 Claude 를 부름
    py("tg_traders.py", "--ai-only")  # PC가 올린 통계가 바뀌었을 때만

    drafts = [r for r in todo if r["job"] == "draft"][-3:]
    for r in drafts:
        topic = r["args"].get("topic", "")
        py("-m", "publish.draft_card", *(["--topic", topic] if topic else []))
        did.append(f"카드뉴스 초안 {topic}")

    state["done"] = (state["done"] + [r["id"] for r in todo])[-200:]
    STATE.write_text(json.dumps(state), encoding="utf-8")
    return did


def push(did):
    git("add", "--", *[p for p in OUTPUTS if (ROOT / p).exists()])
    if git("diff", "--cached", "--quiet", check=False).returncode == 0:
        return
    git("commit", "-q", "-m", f"data: PC Claude(Max) {datetime.now(KST):%m/%d %H:%M} {', '.join(did) or '갱신'}")
    git("reset", "-q", "--hard", "HEAD")   # 재료로 만든 다른 파일은 버림
    for _ in range(3):
        if git("pull", "-q", "--rebase", "-X", "theirs", check=False).returncode != 0:
            git("rebase", "--abort", check=False)
        if git("push", "-q", check=False).returncode == 0:
            return log("⬆️ 푸시:", ", ".join(did) or "갱신")
        time.sleep(10)
    log("⚠️ 푸시 실패 — 다음 차례에 다시")


def main():
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    if "--run" not in sys.argv:
        # 1) 작업 폴더를 저장소 최신으로 맞춘 뒤, 새 코드로 다시 실행
        if LOCK.exists() and time.time() - LOCK.stat().st_mtime < 90 * 60:
            return
        LOCK.write_text(str(os.getpid()))
        try:
            git("fetch", "-q", "origin")
            git("reset", "-q", "--hard", "origin/main")
            subprocess.run([sys.executable, __file__, "--run"], cwd=ROOT, env=ENV)
        except Exception as e:
            log("⚠️", e)
        finally:
            LOCK.unlink(missing_ok=True)
        return
    sys.path.insert(0, str(ROOT))
    import llm
    if not llm.ready():
        return log("⚠️ claude 명령이 없어요 — Claude Code 설치·로그인 확인")
    did = run_cycle()
    push(did)


if __name__ == "__main__":
    main()
