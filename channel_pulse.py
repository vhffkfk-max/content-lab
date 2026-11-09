"""채널별 발행 체크: 크롤러가 쌓은 기록만 집계한다 (AI 호출 없음). local_ai.py 가 매시간 부른다.

    python channel_pulse.py    # output/site/channel_pulse.json (숫자만)
목표 주기와 계정 주소는 data/channel_targets.json.
수집·집계는 AI 없이. "잘 된/안 된 이유, 다음에 할 것" 문장만 그 계정에 새 글이 생겼을 때 PC의 Claude(Max)로 쓴다.
"""
import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent
DB = Path.home() / "Desktop" / "솔개" / "insta-research" / "data" / "threads_watch.db"
KST = timezone(timedelta(hours=9))
Q = {
    "instagram": ("SELECT last_scan FROM ig_accounts WHERE username=?", "SELECT code, url, taken_at, text FROM ig_posts WHERE account=? AND taken_at IS NOT NULL ORDER BY taken_at DESC",
                  "SELECT views, likes, comments FROM ig_snaps WHERE code=? ORDER BY at DESC LIMIT 1"),
    "threads": ("SELECT last_scan FROM accounts WHERE username=?", "SELECT code, url, taken_at, text FROM posts WHERE username=? AND taken_at IS NOT NULL ORDER BY taken_at DESC",
                "SELECT views, likes, replies FROM snaps WHERE code=? ORDER BY at DESC LIMIT 1"),
}


def status(d7, target):
    return "green" if d7 >= target else "yellow" if d7 * 2 >= target else "red"


def one(c, platform, handle, target, now):
    if handle == "-":   # 정지된 계정
        return {"state": "off", "target_7": target}
    if not handle:
        return {"state": "none", "target_7": target}
    scan_q, post_q, snap_q = Q[platform]
    row = c.execute(scan_q, (handle,)).fetchone()
    if not row or not row[0]:
        return {"handle": handle, "state": "wait", "target_7": target}
    posts = c.execute(post_q, (handle,)).fetchall()
    d7 = sum(1 for p in posts if now - p[2] <= 7 * 86400)
    d30 = sum(1 for p in posts if now - p[2] <= 30 * 86400)
    day = int(datetime.now(KST).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    if platform == "instagram":
        kinds = dict(c.execute("SELECT kind, COUNT(*) FROM ig_posts WHERE account=? AND taken_at>=? GROUP BY kind", (handle, day)).fetchall())
        today = {"card": kinds.get("카드뉴스", 0), "reel": kinds.get("릴스", 0)}
    else:
        today = {"n": sum(1 for p in posts if p[2] >= day)}
    recent = []
    for code, url, at, text in [x for x in posts if now - x[2] <= 30 * 86400][:20]:
        s = c.execute(snap_q, (code,)).fetchone() or (None, None, None)
        recent.append({"code": code, "url": url, "at": at, "text": " ".join((text or "").split())[:60], "views": s[0], "likes": s[1], "comments": s[2]})
    # 24시간 지난 글끼리만 비교 (막 올린 글은 숫자가 덜 쌓임)
    old = [x for x in recent if now - x["at"] >= 86400 and x["likes"] is not None]
    score = lambda x: (x["likes"] or 0) + (x["comments"] or 0)
    best = max(old, key=score) if len(old) >= 2 else None
    worst = min(old, key=score) if len(old) >= 2 else None
    return {"handle": handle, "state": status(d7, target), "last_post": posts[0][2] if posts else None, "d7": d7, "d30": d30,
            "target_7": target, "today": today, "scanned": row[0], "recent": recent, "best": best, "worst": worst}


SYSTEM = """너는 경제 콘텐츠 계정의 편집 코치다. 한 계정의 최근 30일에서 반응이 가장 좋은 글과 가장 나쁜 글을 받아 비교한다.
글 두 개 비교일 뿐이므로 원인을 단정하지 말고 '~일 수 있어요'처럼 쓴다. 주어진 글과 숫자에 없는 사실은 쓰지 않는다. 특정 종목을 사거나 팔라는 말은 쓰지 않는다. 해요체로 각 항목 한두 문장."""
class Note(BaseModel):
    why_good: str
    why_bad: str
    next: str


def note(name, v, old):
    """새 글이 생겼을 때만 AI를 부른다. 실패하면 이전 문장을 유지."""
    if not v.get("best") or not v.get("recent"):
        return old
    sig = v["recent"][0]["code"]
    if old and old.get("sig") == sig:
        return old
    try:
        import llm
        if not llm.ready():
            return old
        pick = lambda x: {k: x[k] for k in ("text", "views", "likes", "comments")}
        r = llm._claude("claude-haiku-5-5", SYSTEM, [{"role": "user", "content": json.dumps({"계정": name, "잘 된 글": pick(v["best"]), "안 된 글": pick(v["worst"]), "최근 7일 발행": v["d7"], "주간 목표": v["target_7"]}, ensure_ascii=False)}], Note)
        return {"sig": sig, "at": datetime.now(KST).isoformat(timespec="minutes"), **r.parsed_output.model_dump()}
    except Exception as e:
        print("피드백 문장 실패 (이전 문장 유지):", str(e)[:200])
        return old


BOARD = ("c-bull", "c-hot", "c-asset", "c-chart")   # 메인 현황판 계정 (말희아빠 제외)
DAYS = 42


def history(c, channels):
    """최근 42일, 날마다 계정별 [카드뉴스, 릴스, 쓰레드] 개수. 메인 현황판 날짜별·요일별 화면용."""
    today = datetime.now(KST).replace(hour=0, minute=0, second=0, microsecond=0)
    keys = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(DAYS - 1, -1, -1)]
    start = int((today - timedelta(days=DAYS - 1)).timestamp())
    table = {k: {ch: [0, 0, 0] for ch in BOARD} for k in keys}
    day = lambda ts: datetime.fromtimestamp(ts, KST).strftime("%Y-%m-%d")
    for ch in BOARD:
        ig, th = channels[ch].get("instagram", ""), channels[ch].get("threads", "")
        if ig and ig != "-":
            for ts, kind in c.execute("SELECT taken_at, kind FROM ig_posts WHERE account=? AND taken_at>=?", (ig, start)):
                slot = {"카드뉴스": 0, "릴스": 1}.get(kind)
                if slot is not None and day(ts) in table:
                    table[day(ts)][ch][slot] += 1
        if th and th != "-":
            for (ts,) in c.execute("SELECT taken_at FROM posts WHERE username=? AND taken_at>=?", (th, start)):
                if day(ts) in table:
                    table[day(ts)][ch][2] += 1
    return [{"d": k, "a": table[k]} for k in keys]


def main():
    cfg = json.loads((ROOT / "data" / "channel_targets.json").read_text(encoding="utf-8"))
    now = int(time.time())
    c = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True, timeout=30)
    out = {"updated": datetime.now(KST).isoformat(timespec="seconds"), "daily": cfg["daily"], "channels": {}}
    path = ROOT / "output" / "site" / "channel_pulse.json"
    try:
        before = json.loads(path.read_text(encoding="utf-8"))["channels"]
    except (OSError, ValueError, KeyError):
        before = {}
    for ch, handles in cfg["channels"].items():
        out["channels"][ch] = {p: one(c, p, handles.get(p, ""), handles.get("per_week", {}).get(p, cfg["targets"][p]["per_week"]), now) for p in Q}
        for pf, v in out["channels"][ch].items():
            v["note"] = note(handles.get(pf, ""), v, before.get(ch, {}).get(pf, {}).get("note"))
    out["days"] = history(c, cfg["channels"])
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("발행 체크", {k: {p: v[p]["state"] for p in v} for k, v in out["channels"].items()})


if __name__ == "__main__":
    main()
