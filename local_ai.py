"""내 PC에서 5분마다 도는 'Claude 작업 담당' — 깃허브 대신 Max 구독(Claude Code)으로 글·분석을 쓰고 푸시한다.

작업 전용 폴더(C:\\Users\\qkreo\\content-lab-ai, 저장소 복사본)에서 돈다. 개발 폴더는 건드리지 않는다.
설치: powershell -ExecutionPolicy Bypass -File local_ai_install.ps1   (작업 스케줄러 content-lab-ai)

매번 하는 일
  1) 저장소 최신으로 맞춤 (작업 폴더라 로컬 변경은 버림)
  2) 깃허브가 남긴 요청(data/ai_requests.json) 처리: daily·social·tg·trd·draft·thpost(쓰레드 글 A·B·C)
  3) 정해진 시각 일: 텔레그램 문구(07·12·18시), 트레이더스 글(07·18시), 카드뉴스 추천안(07~22시 1시간마다), 시황 변환, 트레이더스 피드백
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
try:   # 계정별 콘텐츠 결과 파일 (accounts.config.json)
    _ACCS = json.loads((ROOT / "accounts.config.json").read_text(encoding="utf-8"))["accounts"]
except (OSError, ValueError, KeyError):
    _ACCS = []
KST = timezone(timedelta(hours=9))
STATE = Path.home() / ".content-lab-ai" / "state.json"
LOCK = Path.home() / ".content-lab-ai" / "lock"
LOG = ROOT / "data" / "local_ai.log"
SITE = "output/site/"
OUTPUTS = [SITE + f for f in ("tg_ai.json", "tg_rewrites.json", "trd_rooms.json", "trd_posts.json", "drafts.json",
                               "imports.json", "threads_ai.json", "x_ai.json", "thm_ai.json", "growth_plan.json", "thread_posts.json",
                               "chart_reports.json", "charts", "futures_brief.json", "futures", "malhee_var.json", "acc_topics.json", "channel_pulse.json", "trader_posts.json")] + [SITE + f"acc_{a['slug']}.json" for a in _ACCS] + ["data/publish_queue.json", "data/card_style.json", "data/form_stats.json"]
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
CRAWLERS = (("content-lab-telegram-live", "tg_live.py"), ("content-lab-threads-watch", "threads_watch.py"), ("content-lab-thread-listen", "thread_listen.py"))
TG_BEAT = Path.home() / ".content-lab-ai" / "tg_live.beat"
TG_STALE_MIN = 40   # 10분마다 갱신되는 표시가 이만큼 멈추면 수집이 걸린 것
ALERTED = Path.home() / ".content-lab-ai" / "crawl_alert"


def log(*a):
    line = f"{datetime.now(KST):%m/%d %H:%M:%S} " + " ".join(str(x) for x in a)
    print(line)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def git(*a, check=True):
    ident = ["-c", "user.name=content-lab-bot", "-c", "user.email=content-lab-bot@users.noreply.github.com"]   # 작업 폴더엔 이름 설정이 없음
    return subprocess.run(["git", *ident, *a], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=check, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


AUTO_CHART = False   # 매일 아침 08시 자동 차트 (11/07 사용자 요청으로 잠시 멈춤 — 시스템 업그레이드 뒤 True 로). 사이트 버튼 차트는 그대로 됨
AUTO_FUTURES = False   # 선물 브리핑 자동 08:30·21시 (11/07 사용자 요청으로 잠시 멈춤 — 업그레이드 뒤 True 로). 사이트 버튼은 그대로 됨


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


def alert_owner(text):
    """크롤러 문제를 봇으로 — 1시간에 한 번만."""
    if ALERTED.exists() and time.time() - ALERTED.stat().st_mtime < 3600:
        return
    ALERTED.touch()
    sys.path.insert(0, str(ROOT))
    from common import load_env
    load_env()
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return
    import urllib.parse
    import urllib.request
    try:
        data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=20)
    except Exception as e:
        log("⚠️ 봇 알림 실패:", e)


def watch_crawlers():
    """크롤링은 멈추면 안 된다 — 꺼졌거나 걸렸으면 작업 스케줄러로 다시 켠다."""
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    run = lambda *a: subprocess.run(a, capture_output=True, text=True, errors="replace", creationflags=flags)
    ps = run("powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | ForEach-Object CommandLine")
    if ps.returncode != 0:
        return log("⚠️ 크롤러 확인 실패:", ps.stderr[:200])
    for task, script in CRAWLERS:
        hung = script == "tg_live.py" and TG_BEAT.exists() and time.time() - TG_BEAT.stat().st_mtime > TG_STALE_MIN * 60
        if script in ps.stdout and not hung:
            continue
        if hung:
            run("schtasks", "/end", "/tn", task)
        r = run("schtasks", "/run", "/tn", task)
        msg = f"{'걸려서' if hung else '꺼져서'} 다시 켬: {script}" + ("" if r.returncode == 0 else f" (실패: {r.stderr.strip()[:120]})")
        log("🔁", msg)
        alert_owner(f"⚠️ 크롤러 {msg}")


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
    passed = [h for h in hours if now.hour + now.minute / 60 >= h]   # 8.5 = 08:30
    if not passed:
        return False
    slot = f"{now:%Y-%m-%d}-{passed[-1]}"
    if state.get(key) == slot:
        return False
    state[key] = slot
    return True


IDEA_SLOTS = tuple(range(7, 23))   # 07~22시 1시간마다 텍스트 추천안 + 표지 시안. 완성 카드는 대표가 사이트에서 고른 것만 (2026-11-05)


def auto_ideas(state, did):
    """이번 시각에 추천안이 없으면 만듦. PC가 꺼져 있던 시간은 따라잡지 않는다(지난 소식을 몰아 만들면 Max 사용량만 쓴다)."""
    now = datetime.now(KST)
    today = f"{now:%Y-%m-%d}"
    if state.get("draft_fail", {}).get("day") == today and state["draft_fail"]["n"] >= 3:
        return   # 오늘 3번 실패했으면 멈춤 (Max 사용량 낭비 방지) — 봇 알림은 draft_card 가 함
    qp = ROOT / "data" / "publish_queue.json"
    ideas = json.loads(qp.read_text(encoding="utf-8")).get("ideas", []) if qp.exists() else []
    if now.hour not in IDEA_SLOTS or any(i["created_at"].startswith(f"{now:%Y-%m-%dT%H}") for i in ideas):
        return
    if py("-m", "publish.card_ideas") != 0:
        f = state.get("draft_fail", {})
        state["draft_fail"] = {"day": today, "n": (f.get("n", 0) if f.get("day") == today else 0) + 1}
        return
    did.append("카드뉴스 추천안")


DAILY_REQ = {"draft": 30, "daily": 3, "social": 6, "tg": 10, "trd": 10, "chart": 20, "thpost": 40, "refresh_canva": 3, "trader": 20}


def cap_requests(state, todo):
    """하루 한도를 넘은 요청은 건너뜀 (2026-11-06 사이트 암호를 없애서). 건너뛴 요청도 처리한 것으로 적어 다시 보지 않는다."""
    today = datetime.now(KST).strftime("%Y-%m-%d")
    if state.get("req_count", {}).get("day") != today:
        state["req_count"] = {"day": today}
    count, keep = state["req_count"], []
    for r in todo:
        n = count.get(r["job"], 0)
        if n >= DAILY_REQ.get(r["job"], 10):
            log("⏭ 하루 한도 넘은 요청 건너뜀:", r["job"], r.get("args", {}))
            continue
        count[r["job"]] = n + 1
        keep.append(r)
    return keep


def run_cycle():
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"done": []}
    reqs = json.loads((ROOT / "data" / "ai_requests.json").read_text(encoding="utf-8")) if (ROOT / "data" / "ai_requests.json").exists() else []
    if not STATE.exists():   # 처음 설치: 지난 요청은 건너뜀
        state["done"] = [r["id"] for r in reqs]
    todo_all = [r for r in reqs if r["id"] not in state["done"]]
    todo = cap_requests(state, todo_all)   # 사이트가 암호 없이 요청을 받아서 하루 처리량을 막는다
    latest = {r["job"]: r for r in todo}   # 같은 일은 마지막 요청 하나만 (draft 는 주제별로 따로)
    did = []

    posts = [r for r in todo if r["job"] == "thpost"][-6:]   # 지금은 thread_listen.py 가 바로 처리. 이전 요청 경로용으로만 남김
    for r in posts:
        a = r["args"]
        py("thread_post.py", "--idx", a.get("idx", "0"), "--styles", a.get("styles", "ABC"), "--slot", a.get("slot", ""),
           "--rid", a.get("rid", r["id"]), timeout=10 * 60)
        did.append(f"쓰레드 글 {a.get('styles', 'ABC')}")

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

    charts = [r for r in todo if r["job"] == "chart"][-3:]   # 사이트 '차트 만들기' 버튼 (빈칸이면 auto = 오늘 차트 글 종목)
    for r in charts:
        syms = r["args"].get("symbols", "") or "auto"
        s, _, tf = syms.partition("@")   # 'auto@4h' = 오늘 차트 글 종목을 4시간봉으로
        if s == "futures":   # 사이트 '선물 브리핑 만들기' 버튼
            py("futures_brief.py", "--send", timeout=15 * 60)
        else:
            py("chart_report.py", *(["--from-tg", "--force", *(["--tf", tf] if tf else [])] if s == "auto" else [syms, "--send"]), timeout=15 * 60)
        did.append(f"차트 {syms}")
    if AUTO_CHART and slot_once(state, "chart", (8,)):   # 자동 차트리포트는 하루 1번 아침 08시 (PC가 꺼져 있었으면 켜진 뒤 바로). --force: 어제 문구 그대로여도 매일 새로 만듦
        py("chart_report.py", "--from-tg", "--force", timeout=15 * 60)
        did.append("차트리포트")
    if AUTO_FUTURES and slot_once(state, "futures", (8.5, 21)):   # BTC·ETH 선물 브리핑 하루 2번 (08:30 · 미국장 전 21시)
        py("futures_brief.py", "--send", timeout=15 * 60)
        did.append("선물 브리핑")

    trds = [r["args"].get("room") for r in todo if r["job"] == "trd"]   # 사이트 버튼: 폴더별 요청은 모아서 한 번에, 전체 요청이 하나라도 있으면 전부
    if trds:
        refresh_news()
        if all(trds):
            py("trd_posts.py", *[x for room in dict.fromkeys(trds) for x in ("--room", room)])
        else:
            py("trd_posts.py", "--force")
        did.append("트레이더스 글(요청)")
    elif slot_once(state, "trd", (7, 18)) and py("trd_posts.py", "--due") == 0:
        refresh_news()
        py("trd_posts.py")
        did.append("트레이더스 글")

    py("tg_rewrite.py")              # 새 시황이 있을 때만 Claude 를 부름
    mv = ROOT / SITE / "malhee_var.json"
    before = mv.stat().st_mtime if mv.exists() else 0
    py("malhee_watch.py", timeout=15 * 60)   # 말희아빠 블로그·오뉴월드 인스타 새 글 → 채널용 바레이션 (새 글이 있을 때만 Claude 를 부름)
    if mv.exists() and mv.stat().st_mtime != before:
        did.append("말희아빠 바레이션")
    py("tg_traders.py", "--ai-only")  # PC가 올린 통계가 바뀌었을 때만
    gp = ROOT / SITE / "growth_plan.json"
    before = gp.stat().st_mtime if gp.exists() else 0
    py("growth_coach.py")             # 마케팅 코치 — 월·목 아침 한 번 (스스로 차례를 봄)
    if gp.exists() and gp.stat().st_mtime != before:
        did.append("마케팅 코치")

    if any(r["job"] == "refresh_canva" for r in todo):   # 배치를 고친 뒤 안 고친 초안의 캔바 사본을 새로 (publish/refresh_canva.py)
        py("-m", "publish.refresh_canva", timeout=30 * 60)
        did.append("캔바 사본 새 배치로")

    for r in [r for r in todo if r["job"] == "publish"]:   # 대표가 고른 초안 발행 (PC가 꺼져 있다 뒤늦게 올라가지 않게 6시간 지난 요청은 버림)
        if datetime.now(KST) - datetime.fromisoformat(r["at"]) > timedelta(hours=6):
            log("⏭ 오래된 발행 요청 건너뜀:", r["args"].get("id", ""))
            continue
        py("-m", "publish.publish_card", r["args"].get("id", ""), "--yes", timeout=15 * 60)
        did.append(f"인스타 발행 {r['args'].get('id', '')}")

    if time.time() - state.get("pulse_at", 0) >= 3600:   # 채널 발행 체크: AI 없이 크롤링 기록만 집계 (매시간)
        state["pulse_at"] = time.time()
        py("channel_pulse.py", timeout=120)
        did.append("발행 체크")

    for r in [x for x in todo if x["job"] == "trader"][-3:]:   # 차트덕후: 트레이더 분석 → 쓰레드 글
        py("chart_trader.py", "--rid", r["id"], timeout=15 * 60)
        did.append("트레이더 분석 변환")

    drafts = [r for r in todo if r["job"] == "draft"][-3:]
    for r in drafts:
        topic, pick = r["args"].get("topic", ""), r["args"].get("pick", "")
        py("-m", "publish.draft_card", *(["--topic", topic, "--style", pick[6:]] if pick.startswith("style:") else ["--pick", pick] if pick else ["--topic", topic] if topic else []))
        did.append(f"카드뉴스 초안 {pick or topic}")
    if not drafts:
        auto_ideas(state, did)

    if slot_once(state, "accounts", (7, 12, 18)):   # 계정별 콘텐츠: 소재 정제 → 준비된 계정 글·영상 대본 (acclab, 계정당 하루 3건)
        refresh_news()
        py("news_pool.py")              # 같은 소식 묶음 (수집 소스는 그대로)
        py("-m", "acclab.run", timeout=30 * 60)
        did.append("계정별 콘텐츠")

    if slot_once(state, "learn", tuple(range(8, 24))):   # 1시간마다: 캔바에서 고친 것·48시간 성적 배우기 (publish/card_learn.py)
        py("-m", "publish.card_learn")

    state["done"] = (state["done"] + [r["id"] for r in todo_all])[-200:]
    STATE.write_text(json.dumps(state), encoding="utf-8")
    return did


def strip_canva_links():
    """저장소가 공개라 캔바 편집 링크(열쇠가 든 주소)는 큐에서 빼고 올린다. 링크는 텔레그램으로만, 사이트는 디자인 id 로 만든 주소를 쓴다."""
    qp = ROOT / "data" / "publish_queue.json"
    if not qp.exists():
        return
    queue = json.loads(qp.read_text(encoding="utf-8"))
    found = [it for it in queue.get("items", []) if "edit_url" in (it.get("canva") or {})]
    for it in found:
        del it["canva"]["edit_url"]
    if found:
        qp.write_text(json.dumps(queue, ensure_ascii=False, indent=1), encoding="utf-8")


def push(did):
    strip_canva_links()
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
        watch_crawlers()
        try:   # 매시간 분석 (hourly_lab.py): 오래 걸려서 따로 띄움 — 이 5분 작업(말희아빠·시황 변환)을 막지 않게. 차례·잠금은 스스로 봄
            subprocess.Popen([sys.executable, "hourly_lab.py"], cwd=ROOT, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        except OSError as e:
            log("⚠️ 매시간 분석 띄우기 실패:", e)
        try:   # 만든 영상·카드를 텔레그램으로 (publish/tg_watch.py) — 잠금과 상관없이 5분마다, 겹치면 스스로 건너뜀
            subprocess.Popen([sys.executable, "-m", "publish.tg_watch"], cwd=ROOT, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        except OSError as e:
            log("⚠️ 텔레그램 자동 전송 띄우기 실패:", e)
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
