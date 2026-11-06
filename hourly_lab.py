"""매시간 분석 (2026-11-06 대표 지시: "한 시간씩 업데이트가 무조건 돼야 한다 — Max·항상 켜진 PC 활용").

깃허브 daily.yml 은 하루 1번이라 인스타 추천·쓰레드 랭킹·X 브리핑이 최대 24시간 멈춰 있었다.
이제 PC가 1시간마다: 크롤러가 30분마다 올린 data/free_crawl.json 을 표에 넣고 → 분석·사이트 자료 → Claude(Max) 분석
(쓰레드 왜 떴나·X·내 계정·기획안 — 자료가 그대로면 각 프로그램이 스스로 건너뜀) → 바뀐 사이트 자료만 깃허브에 올림.
릴스·카드뉴스 '왜 떴나'(뜬 글 공식)는 크롤러 DB가 있는 개발 폴더에서 viral_daily.py 가 매시간 따로 돈다.

    python hourly_lab.py            # local_ai.py 가 5분마다 띄움. 이번 시각에 이미 했으면 바로 끝
    python hourly_lab.py --force    # 지금 바로

local_ai.py(5분마다 git reset --hard)와 같은 폴더를 쓰면 도중에 결과가 지워지므로 전용 폴더 ~/content-lab-hourly 에서 돈다.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
HOME = Path.home() / ".content-lab-ai"
STATE = HOME / "hourly_state.json"
LOCK = HOME / "hourly.lock"
LOCK_STALE_S = 3 * 3600
CLONE = Path.home() / "content-lab-hourly"
REPO = "https://github.com/vhffkfk-max/content-lab.git"
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# 순서대로. (프로그램, 시간 제한 초). 앞 4개는 Claude 없음, 뒤 5개는 Max — 자료가 그대로면 스스로 건너뜀
STEPS = [
    (["free_import.py"], 600),                 # 크롤러가 모은 인스타·쓰레드·X 최근 7일 숫자 → 표
    (["threads_viral.py", "--export"], 300),   # 조회수 10만+ 모음
    (["analyze.py", "--no-open"], 900),        # 주제·형식·추천
    (["export_site.py"], 600),                 # 사이트 자료
    (["account_rank.py"], 900),                # 분야별 계정 순위
    (["threads_analyze.py"], 1800),            # 쓰레드 반응 랭킹·왜 떴나
    (["x_analyze.py"], 1200),                  # X·트루스 브리핑
    (["threads_mine_analyze.py"], 1200),       # 황소개미 진단
    (["generate_drafts.py"], 1800),            # 인스타 기획안 (3일 재사용)
    (["import_ideas.py"], 1200),               # 해외 아이디어
]
# 다른 PC 작업이 30분·5분마다 더 새로 올리는 자료 — 여기서 다시 만든 옛 값으로 덮어쓰지 않는다
LIVE = ("google_", "press_", "live_meta", "hot_now", "thx_live", "igx_live", "tg_", "trd_", "thm_meta", "thm_posts", "thm_feed",
        "malhee_var", "use_audit", "thread_posts", "viral", "growth_plan", "chart_reports", "futures_brief")
# 1시간 기준 점검표: (파일, 허용 분, 이름). 파일은 내용이 바뀔 때만 커밋되므로 '시각'이 매번 바뀌는 파일만 고름
FRESH = [
    ("output/site/hourly_meta.json", 90, "매시간 분석"),
    ("output/site/live_meta.json", 90, "뉴스 수집(30분)"),
    ("output/site/thx_live_meta.json", 90, "쓰레드 실시간 추적(30분)"),
    ("output/site/igx_live_meta.json", 90, "인스타 실시간 추적(30분)"),
    ("data/free_crawl.json", 90, "무료 크롤러 원자료(30분)"),
    ("output/site/tg_meta.json", 90, "텔레그램 수집(30분)"),
    ("output/site/viral.json", 120, "뜬 글 공식(릴스·카드뉴스, 매시간)"),
    ("output/site/hot_now.json", 150, "지금 쓸 거리(2시간)"),
]


def git(*a, cwd):
    r = subprocess.run(["git", "-c", "user.name=content-lab-bot", "-c", "user.email=content-lab-bot@users.noreply.github.com", *a],
                       cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=NOWIN)
    return r.returncode, (r.stdout + r.stderr).strip()


def log(msg):
    HOME.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now(KST):%m/%d %H:%M:%S} {msg}"
    with open(HOME / "hourly.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line)


def freshness(cwd):
    """저장소(origin/main)에서 각 자료가 마지막으로 바뀐 지 몇 분 됐나 → 멈춘 것 목록."""
    now, out = time.time(), []
    for path, limit, name in FRESH:
        code, ts = git("log", "-1", "--format=%ct", "origin/main", "--", path, cwd=cwd)
        age = int((now - int(ts)) / 60) if code == 0 and ts.strip().isdigit() else None
        out.append({"name": name, "file": path.split("/")[-1], "age_min": age, "limit": limit, "stale": age is None or age > limit})
    # X 크롤러: 원자료 파일은 30분마다 올라가도 X 새 글이 0개일 수 있어(10/31~11/06 로그인·화면 문제) 가장 새 X 글 시각으로 본다
    try:
        x = json.loads((Path(cwd) / "data" / "free_crawl.json").read_text(encoding="utf-8")).get("x") or []
        newest = max((p.get("created_at") or 0) for p in x) if x else 0
        age = int((now - newest) / 60) if newest else None
        out.append({"name": "X 크롤러 새 글", "file": "free_crawl.json#x", "age_min": age, "limit": 360, "stale": age is None or age > 360})
    except (OSError, ValueError):
        pass
    return out


def alert(text):
    """멈춘 자료는 봇으로 — 3시간에 한 번만."""
    mark = HOME / "hourly_alert"
    if mark.exists() and time.time() - mark.stat().st_mtime < 3 * 3600:
        return
    mark.touch()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from common import load_env
        load_env()
    except Exception:
        pass
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return
    import urllib.parse
    import urllib.request
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage",
                               data=urllib.parse.urlencode({"chat_id": chat, "text": text}).encode(), timeout=20)
    except Exception as e:
        log(f"봇 알림 실패: {e}")


def outer(force):
    """local_ai 폴더에서: 차례·잠금 확인 → 1시간 점검 → 전용 폴더를 최신으로 → 그 폴더의 새 코드로 실행."""
    now = datetime.now(KST)
    slot = now.strftime("%Y-%m-%d-%H")
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    if not force and state.get("slot") == slot:
        return
    if LOCK.exists() and time.time() - LOCK.stat().st_mtime < LOCK_STALE_S:
        return
    HOME.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(str(os.getpid()), encoding="utf-8")
    try:
        state["slot"] = slot
        STATE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        here = Path(__file__).resolve().parent
        git("fetch", "-q", "origin", "main", cwd=here)
        fresh = freshness(here)
        stale = [f for f in fresh if f["stale"] and f["file"] != "hourly_meta.json"]
        if stale:
            alert("⚠️ 1시간 기준 점검: 멈춘 자료\n" + "\n".join(f"· {f['name']}: {f['age_min'] if f['age_min'] is not None else '?'}분째 그대로" for f in stale))
        if not (CLONE / ".git").exists():
            code, out = git("clone", "-q", "--depth", "50", REPO, str(CLONE), cwd=Path.home())
            if code != 0:
                return log(f"⚠️ 전용 폴더 만들기 실패: {out[-200:]}")
        git("fetch", "-q", "--depth", "50", "origin", "main", cwd=CLONE)
        git("reset", "-q", "--hard", "origin/main", cwd=CLONE)
        (CLONE / "data").mkdir(exist_ok=True)
        (CLONE / "data" / "hourly_fresh.json").write_text(json.dumps(fresh, ensure_ascii=False), encoding="utf-8")
        subprocess.run([sys.executable, "hourly_lab.py", "--run"], cwd=CLONE, env=ENV, creationflags=NOWIN, timeout=LOCK_STALE_S)
    except Exception as e:
        log(f"⚠️ {e!r}")
    finally:
        LOCK.unlink(missing_ok=True)


def inner():
    """전용 폴더에서: 분석 차례대로 → 바뀐 사이트 자료 + hourly_meta.json 만 올림."""
    root = Path(__file__).resolve().parent
    started, steps = time.time(), []
    log("시작")
    for args, limit in STEPS:
        t = time.time()
        try:
            r = subprocess.run([sys.executable, *args], cwd=root, env=ENV, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=limit, creationflags=NOWIN)
            ok, tail = r.returncode in (0, 3), [l for l in (r.stdout + r.stderr).splitlines() if l.strip()][-1:]
        except subprocess.TimeoutExpired:
            ok, tail = False, ["시간 초과"]
        steps.append({"step": " ".join(args), "ok": ok, "sec": round(time.time() - t), "note": (tail[0] if tail else "")[:160]})
        log(f"{'✓' if ok else '✗'} {' '.join(args)} ({steps[-1]['sec']}초) {steps[-1]['note']}")
    _, st = git("status", "--porcelain", "--", "output/site", cwd=root)
    changed = []
    for line in st.splitlines():
        f = line[3:].strip().strip('"')
        name = f.rsplit("/", 1)[-1]
        if f.endswith(".json") and not name.startswith(LIVE):
            changed.append(f)
    fp = root / "data" / "hourly_fresh.json"
    fresh = json.loads(fp.read_text(encoding="utf-8")) if fp.exists() else []
    meta = {"at": datetime.now(KST).isoformat(timespec="minutes"), "took_sec": round(time.time() - started),
            "steps": steps, "updated": [f.rsplit("/", 1)[-1][:-5] for f in changed], "fresh": fresh}
    (root / "output" / "site" / "hourly_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.path.insert(0, str(root))
    import repo_sync
    res = repo_sync.publish(changed + ["output/site/hourly_meta.json"], f"data: 매시간 분석 {datetime.now(KST):%m/%d %H시} ({len(changed)}개 갱신)")
    log(f"끝 {meta['took_sec']}초 · 갱신 {len(changed)}개 · 올리기 {res}")


if __name__ == "__main__":
    if "--run" in sys.argv:
        inner()
    else:
        outer("--force" in sys.argv)
