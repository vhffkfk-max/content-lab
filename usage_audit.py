"""활용 체크 — 연구소가 추천한 것을 실제로 썼는지 3시간마다 확인 → output/site/use_audit.json

    python usage_audit.py           # 차례(3시간, 07~23시)일 때만 — threads_watch.py 가 30분마다 부름
    python usage_audit.py --force   # 지금 바로
    python usage_audit.py --dry-run # 모은 재료 개수만

- 추천(연구소가 보여 준 것): 지금 발행할 거리(hot_now)·인스타 추천(recs)·텔레그램 문구(tg_ai)·트레이더스 글(trd_posts)·
  마케팅 코치 카피(growth_plan)·따라 할 쓰레드(thx_top). 화면은 계속 바뀌니 볼 때마다 data/rec_log.json 에 쌓음.
  처음 한 번은 깃허브 기록(최근 14일)에서 지난 추천을 되살림.
- 실제로 한 것: 황소개미 쓰레드 글(data/threads_watch.db, PC 크롤러), 텔레그램 '차트보는 말희아빠' 채널 글(tg_mine),
  ChatGPT·Claude 대화(data/ai_chats/ 에 넣은 내보내기 파일의 제목·첫 질문만 — 원문은 저장소에 안 올림).
- 맞춰 보기: Claude Sonnet(내 PC Claude Code, Max 구독, llm.py) — 글마다 '어느 추천에서 나왔나'를 판정.
- 사이트에는 숫자와 공개된 글(쓰레드·텔레그램)만. AI 대화는 '날짜·어느 추천' 만 올리고 제목·내용은 안 올림.
"""
import argparse
import json
import sqlite3
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timedelta, timezone
from typing import List

from pydantic import BaseModel

import llm as anthropic
from apify_threads import MY_ACCOUNTS
from common import OUTPUT_DIR, ROOT, load_env

KST = timezone(timedelta(hours=9))
SITE = OUTPUT_DIR / "site"
OUT = SITE / "use_audit.json"
LOG = ROOT / "data" / "rec_log.json"
CHATS = ROOT / "data" / "ai_chats"
WATCH_DB = ROOT / "data" / "threads_watch.db"
MODEL = "claude-sonnet-5-5"
EVERY_S = 3 * 3600
DAYS = 14


def site(name):
    try:
        return json.loads((SITE / f"{name}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def first_line(t, n=70):
    line = next((x.strip() for x in (t or "").splitlines() if x.strip()), "")
    return line[:n] + ("…" if len(line) > n else "")


# ── 추천 모으기 ──────────────────────────────────────────────
def recs_from(name, d, day):
    """사이트 파일 하나 → 추천 목록 [{src, channel, title, text}]."""
    out = []
    if not d:
        return out
    if name == "hot_now":
        for h in d if isinstance(d, list) else []:
            for p in h.get("picks", []):
                out.append({"day": (h.get("at") or day)[:10], "src": "지금 발행할 거리", "channel": p.get("channel", ""),
                            "title": p.get("title", ""), "text": p.get("topic", "") + " / " + first_line(p.get("draft"), 120)})
    elif name == "recs":
        for r in (d if isinstance(d, list) else [])[:8]:
            out.append({"day": day, "src": "인스타 추천", "channel": "인스타", "title": r.get("title_idea") or r.get("topic", ""),
                        "text": f"{r.get('topic', '')} · {r.get('format', '')}"})
    elif name == "tg_ai" and isinstance(d, dict):
        for t in d.get("today") or []:
            out.append({"day": day, "src": "텔레그램 문구", "channel": "텔레그램", "title": first_line(t.get("text")), "text": (t.get("text") or "")[:160]})
    elif name == "trd_posts" and isinstance(d, dict):
        for room in d.get("rooms") or d.get("posts") or []:
            for p in (room.get("posts") if isinstance(room, dict) and "posts" in room else [room]):
                if isinstance(p, dict) and (p.get("text") or p.get("title")):
                    out.append({"day": d.get("date") or day, "src": "트레이더스 글", "channel": "텔레그램",
                                "title": p.get("title") or first_line(p.get("text")), "text": (p.get("text") or "")[:160]})
    elif name == "growth_plan" and isinstance(d, dict):
        dd = d.get("date") or day
        for h in d.get("hooks") or []:
            out.append({"day": dd, "src": "코치 첫 줄 카피", "channel": h.get("channel", ""), "title": h.get("text", "")[:80], "text": h.get("text", "")})
        for c in d.get("calendar") or []:
            out.append({"day": dd, "src": "코치 7일 계획", "channel": c.get("channel", ""), "title": c.get("idea", "")[:80], "text": c.get("idea", "")})
    elif name == "thread_posts":   # 사이트 '쓰레드 콘텐츠 만들기'로 만든 황소개미 글 (thread_post.py)
        for x in d if isinstance(d, list) else []:
            out.append({"day": (x.get("at") or day)[:10], "src": "쓰레드 글 만들기", "channel": "쓰레드",
                        "title": f"{x.get('pick', '')} ({x.get('style', '')})", "text": (x.get("text") or "")[:160]})
    elif name == "thx_top":
        for r in (d if isinstance(d, list) else [])[:5]:
            out.append({"day": day, "src": "따라 할 쓰레드", "channel": "쓰레드", "title": first_line(r.get("text")), "text": (r.get("text") or "")[:160]})
    return out


SOURCES = ["hot_now", "recs", "tg_ai", "trd_posts", "growth_plan", "thx_top", "thread_posts"]


def git(*args):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.stdout if r.returncode == 0 else ""


def backfill():
    """깃허브 기록에서 최근 14일 추천을 되살림 (처음 한 번)."""
    out = []
    for name in SOURCES:
        path = f"output/site/{name}.json"
        seen_day = set()
        for line in git("log", "origin/main", f"--since={DAYS}.days", "--format=%H %cI", "--", path).splitlines():
            h, at = line.split(" ", 1)
            day = at[:10]
            if day in seen_day and name != "hot_now":   # 하루 한 번이면 충분 (hot_now 는 하루에도 여러 번 바뀜)
                continue
            seen_day.add(day)
            try:
                out += recs_from(name, json.loads(git("show", f"{h}:{path}") or "null"), day)
            except ValueError:
                pass
    return out


def collect_recs():
    log = json.loads(LOG.read_text(encoding="utf-8")) if LOG.exists() else None
    today = datetime.now(KST).strftime("%Y-%m-%d")
    new = backfill() if log is None else []
    for name in SOURCES:
        new += recs_from(name, site(name), today)
    log = log or []
    keys = {(r["src"], r["title"]) for r in log}
    for r in new:
        if r["title"] and (r["src"], r["title"]) not in keys:
            keys.add((r["src"], r["title"]))
            log.append(r)
    since = (datetime.now(KST) - timedelta(days=30)).strftime("%Y-%m-%d")
    log = [r for r in log if r["day"] >= since]
    LOG.write_text(json.dumps(log, ensure_ascii=False, indent=0), encoding="utf-8")
    return log


# ── 실제로 한 것 모으기 ──────────────────────────────────────
def threads_posts(since_ts):
    if not WATCH_DB.exists():
        return []
    own = MY_ACCOUNTS[0].lower()
    w = sqlite3.connect(WATCH_DB)
    out = []
    for code, url, text, taken in w.execute("SELECT code, url, text, taken_at FROM posts WHERE lower(username)=? AND taken_at>=? ORDER BY taken_at",
                                            (own, since_ts)):
        v = w.execute("SELECT views FROM snaps WHERE code=? ORDER BY at DESC LIMIT 1", (code,)).fetchone()
        out.append({"kind": "황소개미 쓰레드", "day": datetime.fromtimestamp(taken, KST).strftime("%Y-%m-%d"),
                    "time": datetime.fromtimestamp(taken, KST).strftime("%m/%d %H:%M"), "text": text or "", "url": url,
                    "views": v[0] if v else None, "public": True})
    w.close()
    return out


def telegram_posts(since_day):
    year = datetime.now(KST).year
    out = []
    for r in site("tg_mine") or []:
        if r.get("kind") != "채널" or not r.get("time"):
            continue
        day = f"{year}-{r['time'][:5].replace('/', '-')}"
        if day >= since_day:
            out.append({"kind": "텔레그램 채널", "day": day, "time": r["time"], "text": r.get("text") or "", "url": r.get("link"),
                        "views": r.get("views"), "public": True})
    return out


def _chat_items(raw, app):
    """ChatGPT(title·create_time·mapping) / Claude(name·created_at·chat_messages) 내보내기 → [{day, title, ask}]."""
    out = []
    for c in raw if isinstance(raw, list) else []:
        if app == "ChatGPT" or "mapping" in c:
            ts = c.get("create_time") or 0
            day = datetime.fromtimestamp(ts, KST).strftime("%Y-%m-%d") if ts else ""
            asks = []
            for n in sorted((c.get("mapping") or {}).values(), key=lambda n: ((n.get("message") or {}).get("create_time") or 0)):
                m = n.get("message") or {}
                if (m.get("author") or {}).get("role") == "user":
                    parts = (m.get("content") or {}).get("parts") or []
                    asks.append(" ".join(p for p in parts if isinstance(p, str)))
            out.append({"app": "ChatGPT", "day": day, "title": c.get("title") or "", "ask": " / ".join(asks)[:300]})
        else:
            day = (c.get("created_at") or "")[:10]
            asks = [m.get("text") or "" for m in c.get("chat_messages") or [] if m.get("sender") == "human"]
            out.append({"app": "Claude", "day": day, "title": c.get("name") or "", "ask": " / ".join(asks)[:300]})
    return out


def ai_chats(since_day):
    """data/ai_chats/ 안의 내보내기(zip 또는 conversations.json). 파일 이름에 chatgpt/claude 가 있으면 그걸로 구분."""
    if not CHATS.exists():
        return [], []
    items, files = [], []
    for f in sorted(CHATS.iterdir()):
        app = "Claude" if "claude" in f.name.lower() else "ChatGPT"
        try:
            if f.suffix == ".zip":
                with zipfile.ZipFile(f) as z:
                    name = next((n for n in z.namelist() if n.endswith("conversations.json")), None)
                    raw = json.loads(z.read(name)) if name else []
            elif f.suffix == ".json":
                raw = json.loads(f.read_text(encoding="utf-8"))
            else:
                continue
        except (OSError, ValueError, zipfile.BadZipFile):
            continue
        got = _chat_items(raw, app)
        files.append({"file": f.name, "app": got[0]["app"] if got else app, "last": max((c["day"] for c in got), default="")})
        items += got
    seen, out = set(), []
    for c in items:
        k = (c["app"], c["day"], c["title"])
        if c["day"] >= since_day and k not in seen:
            seen.add(k)
            out.append({"kind": f"{c['app']} 대화", "day": c["day"], "time": c["day"][5:].replace("-", "/"),
                        "text": f"{c['title']} — {c['ask']}", "public": False})
    return out, files


def connector_log(since_day):
    """연구소 커넥터(ChatGPT·Claude 에 붙인 MCP, connector/api/mcp.js)가 mcp-log 브랜치에 남긴 기록 — 언제·어느 앱이·어느 추천을 가져갔나."""
    git("fetch", "-q", "origin", "mcp-log")
    out = []
    for k in (1, 0):
        month = (datetime.now(KST).replace(day=1) - timedelta(days=k)).strftime("%Y-%m") if k else datetime.now(KST).strftime("%Y-%m")
        try:
            out += json.loads(git("show", f"origin/mcp-log:log/{month}.json") or "[]")
        except ValueError:
            pass
    return [r for r in out if r.get("at", "")[:10] >= since_day]


# ── Claude 로 맞춰 보기 ─────────────────────────────────────
class Match(BaseModel):
    out_id: int
    rec_id: int          # 없으면 -1
    how: str             # 그대로 | 고쳐서 | 주제만 | 없음
    note: str


class Audit(BaseModel):
    matches: List[Match]
    verdict: str
    nudge: str
    wasted: List[int]    # 안 쓴 추천 중 아까운 것 rec_id (최대 5)


SYSTEM = """너는 경제 콘텐츠 사업(쓰레드 '황소개미', 텔레그램 '차트보는 말희아빠', 인스타 카드뉴스)의 '연구소 활용 체크' 담당이다.
연구소 사이트는 매일 '이걸 올리세요'라는 추천을 보여 준다. 대표가 실제로 올린 글·AI 대화가 그 추천에서 나왔는지 판정한다.

판정 기준(out 하나마다 정확히 하나):
- 그대로: 추천 초안·제목을 거의 그대로 씀
- 고쳐서: 추천의 같은 사건·숫자를 자기 말로 바꿔 씀
- 주제만: 같은 주제(같은 종목·사건)지만 각도·숫자가 다름. 추천 날짜와 1일 이상 차이 나면 '주제만'까지만
- 없음: 연결 없음(rec_id=-1). 억지로 맞추지 않는다. 같은 날 같은 주제가 아니면 대부분 없음이다.
추천 날짜가 글보다 늦으면 그 추천에서 나온 게 아니다.

verdict: 어떤 추천을 쓰고 어떤 추천은 안 쓰는지 패턴을 한두 문장(전체 개수는 화면에 따로 나오니 다시 세지 말 것). 칭찬·꾸밈 없이.
nudge: 내일 바로 할 한 가지(어느 메뉴를 언제 보고 무엇을 할지). 쉬운 한국어, 한 문장.
wasted: 안 쓴 추천 중 실제로 많이 퍼진 주제였거나 지금도 쓸 만한 것 최대 5개 rec_id."""


def judge(recs, outs):
    rl = [f"[{i}] {r['day']} · {r['src']} · {r['channel']} · {r['title']} | {r['text'][:110]}" for i, r in enumerate(recs)]
    ol = [f"[{i}] {o['day']} {o['time'][-5:] if ':' in o['time'] else ''} · {o['kind']} · {first_line(o['text'], 160)}" for i, o in enumerate(outs)]
    prompt = "## 연구소 추천\n" + "\n".join(rl) + "\n\n## 실제로 한 것\n" + "\n".join(ol) + "\n\n실제로 한 것마다 판정해 줘."
    r = anthropic.Anthropic().messages.parse(model=MODEL, max_tokens=8000, system=SYSTEM, output_config={"effort": "low"},
                                             messages=[{"role": "user", "content": prompt}], output_format=Audit)
    return r


def due(force):
    if force:
        return True
    h = datetime.now(KST).hour
    return 7 <= h <= 23 and (not OUT.exists() or time.time() - OUT.stat().st_mtime >= EVERY_S)


def site_minutes():
    try:
        d = json.loads((ROOT / "data" / "site_usage.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    tot = {}
    for days in d.get("devices", {}).values():
        for day, pages in days.items():
            tot[day] = tot.get(day, 0) + sum(pages.values())
    return {k: round(v / 60) for k, v in tot.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    load_env()
    if not (a.dry_run or due(a.force)):
        return
    now = datetime.now(KST)
    since_day = (now - timedelta(days=DAYS - 1)).strftime("%Y-%m-%d")
    log = collect_recs()
    recs = [r for r in log if r["day"] >= since_day]
    chats, chat_files = ai_chats(since_day)
    outs = sorted(threads_posts((now - timedelta(days=DAYS)).timestamp()) + telegram_posts(since_day) + chats, key=lambda o: o["day"])
    if a.dry_run:
        by = {}
        for r in recs:
            by[r["src"]] = by.get(r["src"], 0) + 1
        return print(f"추천 {len(recs)}개 {by} · 실제 {len(outs)}개 (AI 대화 {len(chats)}개, 파일 {len(chat_files)}개)")
    if not anthropic.ready():
        return print("⚠️ Claude Code 가 없어요 — 건너뜀")
    res = judge(recs, outs) if outs and recs else None
    A = res.parsed_output if res else None
    m = {x.out_id: x for x in (A.matches if A else [])}
    used_rec = {}
    matches = []
    for i, o in enumerate(outs):
        x = m.get(i)
        ok = bool(x and x.rec_id >= 0 and x.rec_id < len(recs) and x.how != "없음")
        o["used"] = ok
        if ok:
            r = recs[x.rec_id]
            used_rec[x.rec_id] = used_rec.get(x.rec_id, 0) + 1
            matches.append({"day": o["day"], "time": o["time"], "kind": o["kind"], "how": x.how, "note": x.note,
                            "out": first_line(o["text"], 80) if o["public"] else "", "url": o.get("url") if o["public"] else None,
                            "views": o.get("views"), "rec": r["title"], "rec_src": r["src"], "rec_day": r["day"]})
    clog = connector_log(since_day)
    rec_key = {(r["src"], r["title"]): i for i, r in enumerate(recs)}
    for c in clog:
        for u in c.get("used") or []:
            i = rec_key.get((u.get("src"), u.get("title")))
            if i is not None:
                used_rec[i] = used_rec.get(i, 0) + 1
            matches.append({"day": c["at"][:10], "time": c["at"][5:].replace("-", "/"), "kind": f"{c.get('app', '기타')} 커넥터", "how": "가져감",
                            "note": c.get("tool", ""), "out": "", "url": None, "views": None, "rec": u.get("title", ""),
                            "rec_src": u.get("src", ""), "rec_day": recs[i]["day"] if i is not None else c["at"][:10]})
    mins = site_minutes()
    days = []
    for k in range(7):
        d = (now - timedelta(days=6 - k)).strftime("%Y-%m-%d")
        os_ = [o for o in outs if o["day"] == d]
        days.append({"day": d, "label": d[5:].replace("-", "/"),
                     "posts": sum(o["kind"] != "ChatGPT 대화" and o["kind"] != "Claude 대화" for o in os_),
                     "posts_used": sum(o["used"] and o["public"] for o in os_),
                     "chats": sum(not o["public"] for o in os_), "chats_used": sum(o["used"] and not o["public"] for o in os_),
                     "recs": sum(r["day"] == d for r in recs), "site_min": (mins or {}).get(d),
                     "connector": sum(c["at"][:10] == d for c in clog)})
    by_src = {}
    for i, r in enumerate(recs):
        s = by_src.setdefault(r["src"], {"src": r["src"], "shown": 0, "used": 0})
        s["shown"] += 1
        s["used"] += 1 if i in used_rec else 0
    week = (now - timedelta(days=6)).strftime("%Y-%m-%d")
    w_posts = [o for o in outs if o["public"] and o["day"] >= week]
    out = {
        "time": now.strftime("%m/%d %H:%M"), "days": days,
        "week": {"posts": len(w_posts), "posts_used": sum(o["used"] for o in w_posts),
                 "threads": sum(o["kind"] == "황소개미 쓰레드" for o in w_posts),
                 "threads_used": sum(o["used"] and o["kind"] == "황소개미 쓰레드" for o in w_posts),
                 "chats": sum(not o["public"] and o["day"] >= week for o in outs),
                 "chats_used": sum(o["used"] and not o["public"] and o["day"] >= week for o in outs),
                 "recs": sum(r["day"] >= week for r in recs),
                 "connector": sum(c["at"][:10] >= week for c in clog),
                 "connector_apps": sorted({c.get("app", "기타") for c in clog if c["at"][:10] >= week}),
                 "site_min": sum(v for k, v in (mins or {}).items() if k >= week) if mins else None},
        "verdict": A.verdict if A else "아직 맞춰 볼 글이 없어요.", "nudge": A.nudge if A else "",
        "matches": sorted(matches, key=lambda x: x["time"], reverse=True)[:40],
        "wasted": [{"title": recs[i]["title"], "src": recs[i]["src"], "day": recs[i]["day"], "channel": recs[i]["channel"]}
                   for i in (A.wasted if A else []) if 0 <= i < len(recs) and i not in used_rec][:5],
        "by_src": sorted(by_src.values(), key=lambda s: -s["shown"]),
        "chat_files": [{"app": f["app"], "last": f["last"]} for f in chat_files],
        "site_connected": mins is not None,
        "connector_last": max((c["at"] for c in clog), default=None),
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    wk = out["week"]
    print(f"✅ 활용 체크: 7일 글 {wk['posts']}개 중 추천에서 {wk['posts_used']}개 · AI 대화 {wk['chats']}개 중 {wk['chats_used']}개"
          + (f" · 입력 {res.usage.input_tokens:,} / 출력 {res.usage.output_tokens:,} 토큰" if res else ""))


if __name__ == "__main__":
    main()
