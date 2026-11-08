"""채널별 발행 체크: 크롤러가 쌓은 기록만 집계한다 (AI 호출 없음). local_ai.py 가 매시간 부른다.

    python channel_pulse.py    # output/site/channel_pulse.json (숫자만)
목표 주기와 계정 주소는 data/channel_targets.json.
"""
import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = Path.home() / "Desktop" / "솔개" / "insta-research" / "data" / "threads_watch.db"
KST = timezone(timedelta(hours=9))
Q = {
    "instagram": ("SELECT last_scan FROM ig_accounts WHERE username=?", "SELECT code, url, taken_at FROM ig_posts WHERE account=? AND taken_at IS NOT NULL ORDER BY taken_at DESC",
                  "SELECT views, likes, comments FROM ig_snaps WHERE code=? ORDER BY at DESC LIMIT 1"),
    "threads": ("SELECT last_scan FROM accounts WHERE username=?", "SELECT code, url, taken_at FROM posts WHERE username=? AND taken_at IS NOT NULL ORDER BY taken_at DESC",
                "SELECT views, likes, replies FROM snaps WHERE code=? ORDER BY at DESC LIMIT 1"),
}


def status(d7, target):
    return "green" if d7 >= target else "yellow" if d7 * 2 >= target else "red"


def one(c, platform, handle, target, now):
    if not handle:
        return {"state": "none", "target_7": target}
    scan_q, post_q, snap_q = Q[platform]
    row = c.execute(scan_q, (handle,)).fetchone()
    if not row or not row[0]:
        return {"handle": handle, "state": "wait", "target_7": target}
    posts = c.execute(post_q, (handle,)).fetchall()
    d7 = sum(1 for p in posts if now - p[2] <= 7 * 86400)
    d30 = sum(1 for p in posts if now - p[2] <= 30 * 86400)
    recent = []
    for code, url, at in posts[:3]:
        s = c.execute(snap_q, (code,)).fetchone() or (None, None, None)
        recent.append({"url": url, "at": at, "views": s[0], "likes": s[1], "comments": s[2]})
    return {"handle": handle, "state": status(d7, target), "last_post": posts[0][2] if posts else None, "d7": d7, "d30": d30,
            "target_7": target, "scanned": row[0], "recent": recent}


def main():
    cfg = json.loads((ROOT / "data" / "channel_targets.json").read_text(encoding="utf-8"))
    now = int(time.time())
    c = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True, timeout=30)
    out = {"updated": datetime.now(KST).isoformat(timespec="seconds"), "channels": {}}
    for ch, handles in cfg["channels"].items():
        out["channels"][ch] = {p: one(c, p, handles.get(p, ""), cfg["targets"][p]["per_week"], now) for p in Q}
    (ROOT / "output" / "site" / "channel_pulse.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("발행 체크", {k: {p: v[p]["state"] for p in v} for k, v in out["channels"].items()})


if __name__ == "__main__":
    main()
