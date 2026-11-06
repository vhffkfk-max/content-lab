"""뜬 글 공식·광고 DB 하루 한 번 (threads_watch.py 의 side_jobs 가 30분마다 따로 띄움 → 크롤러를 붙잡지 않음).

    python viral_daily.py           # 오늘 아직 안 했고 05시가 지났으면 실행, 아니면 바로 끝
    python viral_daily.py --force   # 지금 바로

순서: viral_ads.py (광고 판단·DB·다시 재기) → viral_analyze.py (뜬 글 짝 비교·공식) → output/site/viral.json 만 깃허브에 올림.
광고 DB(data/ads.db)·보고서·이미지는 PC에만 둔다 (회사 이름에 '광고 의심'이 붙는 자료라 공개 사이트에 안 올림).
이미 비교한 글은 다시 묻지 않아서, 매일 새로 뜬 글만 Claude(Max)를 부르고 공식 묶음(Opus)은 하루 1번.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import repo_sync
from common import OUTPUT_DIR, ROOT

KST = timezone(timedelta(hours=9))
OUT = OUTPUT_DIR / "viral"
STATE = OUT / "daily_state.json"
LOCK = OUT / "daily.lock"
LOG = OUT / "daily.log"
START_HOUR = 5
LOCK_STALE_S = 4 * 3600


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(KST):%m-%d %H:%M:%S} {msg}\n")


def step(script, limit):
    try:
        r = subprocess.run([sys.executable, script], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=limit, env={**os.environ, "PYTHONIOENCODING": "utf-8"}, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        log(f"{script} 시간 초과")
        return False
    lines = [l for l in (r.stdout + r.stderr).splitlines() if l.strip()]
    for l in lines[-6:]:
        log(f"  {script}: {l[:220]}")
    return r.returncode == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    if not a.force and (state.get("done") == today or now.hour < START_HOUR):
        return
    if LOCK.exists() and time.time() - LOCK.stat().st_mtime < LOCK_STALE_S:
        return   # 다른 실행이 아직 도는 중
    LOCK.write_text(str(os.getpid()), encoding="utf-8")
    try:
        log("시작")
        ads_ok = step("viral_ads.py", 60 * 60)
        ok = step("viral_analyze.py", 2 * 60 * 60)
        if ok:
            log(f"사이트 올리기 {repo_sync.publish(['output/site/viral.json'], 'data: 뜬 글 공식 ' + now.strftime('%m/%d'))}")
        # 실패해도 오늘은 한 번만 시도 (Max 한도를 붙잡지 않게). 다음 날 다시
        STATE.write_text(json.dumps({"done": today, "ads_ok": ads_ok, "analyze_ok": ok, "at": now.isoformat()}, ensure_ascii=False), encoding="utf-8")
        log(f"끝 (광고 {ads_ok}, 공식 {ok})")
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
