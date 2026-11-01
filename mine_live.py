"""황소개미(@bullant_economy) 진단 숫자를 2시간마다 새로 — 유료 수집(Apify)을 끈 뒤 매일 아침 진단이 멈춰 있던 것을 PC 크롤러 숫자로 채움.

    python mine_live.py          # 차례가 됐을 때만 (threads_watch.py 가 30분마다 부름)
    python mine_live.py --force  # 지금 바로

- 재료: data/threads_watch.db (PC 로그인 크롤러가 1시간마다 황소개미 프로필·글 조회수를 잼) + data/insta.db (남의 글 비교 기준)
- insta.db 는 건드리지 않음 — 메모리에 복사해서 내 글만 최신으로 바꾼 뒤 threads_mine.section 으로 계산
→ output/site/thm_meta·thm_posts·thm_feed.json, 3시간마다 AI 진단(thm_ai.json, Max 구독)도 새로
"""
import argparse
import json
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import threads_mine
from apify_threads import MY_ACCOUNTS
from common import OUTPUT_DIR, ROOT
from topics import topics_of

KST = timezone(timedelta(hours=9))
SITE = OUTPUT_DIR / "site"
WATCH_DB = ROOT / "data" / "threads_watch.db"
EVERY_S = 2 * 3600
AI_EVERY_S = 6 * 3600   # AI 진단은 한 번에 입력 8만·출력 4만 토큰이라 6시간마다 (숫자는 2시간마다)


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def fresh_rows(own):
    """PC 크롤러가 본 내 글 (마지막 숫자)."""
    w = sqlite3.connect(WATCH_DB)
    followers = (w.execute("SELECT followers FROM accounts WHERE lower(username)=?", (own,)).fetchone() or [None])[0]
    out = []
    for code, url, text, taken, pf in w.execute("SELECT code, url, text, taken_at, followers FROM posts WHERE lower(username)=?", (own,)):
        s = w.execute("SELECT at, views, likes, replies, reposts FROM snaps WHERE code=? ORDER BY at DESC LIMIT 1", (code,)).fetchone()
        out.append({"code": code, "url": url, "text": text or "", "taken": taken, "followers": followers or pf,
                    "at": s[0] if s else None, "views": s[1] if s else None, "likes": s[2] if s else None,
                    "replies": s[3] if s else None, "reposts": s[4] if s else None})
    w.close()
    return followers, out


def build():
    own = MY_ACCOUNTS[0].lower()
    followers, rows = fresh_rows(own)
    if not rows:
        return print("PC 크롤러가 아직 황소개미 글을 못 봤어요 — 건너뜀")
    mem = sqlite3.connect(":memory:")
    mem.row_factory = sqlite3.Row
    src = sqlite3.connect(f"file:{ROOT / 'data' / 'insta.db'}?mode=ro", uri=True)
    src.backup(mem)
    src.close()
    for r in rows:
        old = mem.execute("SELECT post_id FROM threads_apify WHERE code=? AND lower(username)=?", (r["code"], own)).fetchone()
        if old:
            mem.execute("UPDATE threads_apify SET likes=COALESCE(?, likes), replies=COALESCE(?, replies), reposts=COALESCE(?, reposts), "
                        "views=COALESCE(?, views), followers=COALESCE(?, followers) WHERE post_id=?",
                        (r["likes"], r["replies"], r["reposts"], r["views"], r["followers"], old[0]))
        else:
            mem.execute("INSERT INTO threads_apify (post_id, code, url, username, text, posted_at, likes, replies, reposts, is_reply, "
                        "source, topics, views, followers) VALUES (?,?,?,?,?,?,?,?,?,0,'내 계정',?,?,?)",
                        (r["code"], r["code"], r["url"], MY_ACCOUNTS[0], r["text"], iso(r["taken"]), r["likes"] or 0, r["replies"] or 0,
                         r["reposts"] or 0, ", ".join(t for t in topics_of(r["text"]) if t != "기타"), r["views"], r["followers"]))
    if followers:   # 팔로워는 지금 숫자로 (진단은 '가장 최근 글'의 팔로워를 씀)
        mem.execute("UPDATE threads_apify SET followers=? WHERE lower(username)=?", (followers, own))
    now = datetime.now(timezone.utc)
    d = threads_mine.section(mem, now, MY_ACCOUNTS)
    if d["meta"]:
        d["meta"][0]["updated"] = datetime.now(KST).strftime("%m/%d %H:%M")
    for k in ("meta", "posts", "feed"):
        (SITE / f"thm_{k}.json").write_text(json.dumps(d[k], ensure_ascii=False, indent=1), encoding="utf-8")
    m = d["meta"][0] if d["meta"] else {}
    print(f"✅ 황소개미 진단 숫자 새로: 팔로워 {m.get('followers')} · 글 {len(d['posts'])}개 · 마지막 글 {m.get('last_post')}")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    meta = SITE / "thm_meta.json"
    if not a.force and meta.exists() and time.time() - meta.stat().st_mtime < EVERY_S:
        return
    if not build():
        return
    ai = SITE / "thm_ai.json"
    hour = datetime.now(KST).hour
    if a.force or (7 <= hour <= 23 and (not ai.exists() or time.time() - ai.stat().st_mtime >= AI_EVERY_S)):
        r = subprocess.run([sys.executable, "threads_mine_analyze.py"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=900)
        out = [l for l in (r.stdout + r.stderr).splitlines() if l.strip()]
        print(out[-1] if out else "AI 진단 끝")


if __name__ == "__main__":
    main()
