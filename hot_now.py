"""지금 발행할 거리 — 2시간마다(07~23시) 최근 몇 시간 뉴스·쓰레드·인스타·X 에서 뜨는 주제를 골라 바로 쓸 글감 3개로 정리 → 텔레그램.

    python hot_now.py          # 차례가 됐을 때만 (threads_watch.py 가 30분마다 부름)
    python hot_now.py --force  # 지금 바로

- 재료(돈 안 듦): 경제 매체·구글 뉴스 제목(최근 3시간), PC 크롤러가 잰 지금 크는 쓰레드·인스타 글, X 글(최근 6시간)
- 글 쓰기: Claude Sonnet — 내 PC Claude Code(Max 구독, llm.py)라 API 요금 없음. 구독 사용량만 조금 씀(한 번에 짧게)
- 같은 주제 반복 금지: 최근 6시간에 보낸 주제는 큰 새 소식이 없으면 빼라고 알려 줌
→ output/site/hot_now.json (최근 12번) + 텔레그램 봇 알림. 매일 06:00 추천(recs)은 30일 통계라 느리고, 이건 '지금'용.
"""
import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import List

import requests
from pydantic import BaseModel

import llm as anthropic
from common import OUTPUT_DIR, ROOT, load_env

KST = timezone(timedelta(hours=9))
SITE = OUTPUT_DIR / "site"
OUT = SITE / "hot_now.json"
WATCH_DB = ROOT / "data" / "threads_watch.db"
MODEL = "claude-sonnet-5-5"
HOURS = range(7, 24, 2)        # 07·09·11·13·15·17·19·21·23시
KEEP = 12

SYSTEM = """너는 한국 경제 콘텐츠 계정(@hotconomy, 인스타 카드뉴스·쓰레드·텔레그램 운영)의 편집장이다.
지금 몇 시간 사이 실제로 뜨는 경제 주제를 골라, 바로 발행할 글감 3개를 만든다.
- 근거는 아래 자료에 있는 숫자·제목만 쓴다. 자료에 없는 숫자·사실을 지어내지 않는다. 확인이 필요한 숫자는 [확인] 표시.
- '왜 지금'은 자료 근거로: 기사 몇 건, 쓰레드 조회 속도, X 조회수 등.
- 최근에 이미 보낸 주제는 빼라. 같은 주제라도 큰 새 소식(새 발표·급등락)이 있을 때만 '후속'으로 다시 쓴다.
- 3개는 서로 다른 주제로, 가능하면 다른 채널(쓰레드 글 / 인스타 카드뉴스 / 텔레그램 짧은 속보)로 나눈다.
- 초안은 그 채널에 바로 붙여 넣을 수 있게 쉬운 한국어로. 쓰레드는 3~6줄, 첫 줄은 멈추게 하는 한 줄.
- 트럼프·백악관·재무장관·연준·머스크 같은 해외 핵심 인물의 글은 시장을 움직이고, 이걸 빨리 한국어로 풀어 주면 반응이 아주 좋다.
  경제(관세·금리·달러·주식·코인·기업)와 관련된 핵심 인물 글이 있으면 3개 중 최소 1개는 그걸로 쓴다 — '누가 뭐라고 했고, 한국 투자자에겐 무슨 뜻인지'.
  정치·사생활 글은 경제 영향이 분명할 때만.
- 투자 권유·매수 추천 표현은 쓰지 않는다."""


class Pick(BaseModel):
    topic: str          # 주제 (짧게)
    channel: str        # 쓰레드 / 인스타 카드뉴스 / 텔레그램
    title: str          # 제목·첫 줄
    why_now: str        # 왜 지금인지 (자료 근거, 숫자 포함)
    draft: str          # 바로 쓸 초안
    sources: List[str]  # 근거 자료 링크 (자료에 있던 것만)
    follow_up: bool     # 최근 보낸 주제의 후속이면 True


class Result(BaseModel):
    summary: str        # 지금 시장 분위기 한 줄
    picks: List[Pick]


def due(force):
    now = datetime.now(KST)
    if force:
        return True
    if now.hour not in HOURS:
        return False
    last = load()
    return not last or last[0]["slot"] != now.strftime("%Y-%m-%d %H")


def load():
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def rows(name):
    try:
        return json.loads((SITE / f"{name}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def recent_news(hours=3):
    now = datetime.now(KST)
    out, seen = [], set()
    for r in rows("press_headlines") + rows("google_headlines"):
        try:
            t = datetime.strptime(f"{now.year}/{r['published']}", "%Y/%m/%d %H:%M").replace(tzinfo=KST)
        except (KeyError, ValueError):
            continue
        if now - t <= timedelta(hours=hours) and r["title"] not in seen:
            seen.add(r["title"])
            out.append(f"- [{r['published'][6:]}] {r['title']} ({r.get('source', '')}) {r.get('link', '')[:120]}")
    return out[:60]


def hot_threads():
    rs = sorted((r for r in rows("thx_live") if r["age_h"] <= 12 and r.get("topics") != "기타"), key=lambda r: -(r.get("vph") or 0))[:10]
    return [f"- 시간당 조회 {r.get('vph')} · 조회 {r.get('views')} · 올린 지 {r['age_h']}시간 · @{r['username']} · {r.get('topics')}: "
            f"{r['text'][:120].replace(chr(10), ' ')} {r['url']}" for r in rs]


def hot_insta():
    rs = sorted((r for r in rows("igx_live") if r["age_h"] <= 24), key=lambda r: -(r.get("lph") or 0))[:6]
    return [f"- 시간당 좋아요 {r.get('lph')} · 평소의 {r.get('x_usual')}배 · @{r['username']} {r.get('kind')}: "
            f"{r['text'][:100].replace(chr(10), ' ')} {r['url']}" for r in rs]


def hot_x(hours=6):
    """(핵심 인물 글 — 최신 순, 그 밖 X 글 — 조회 순)."""
    if not WATCH_DB.exists():
        return [], []
    import x_watch
    v = x_watch.vips()
    c = sqlite3.connect(WATCH_DB)
    try:
        rs = c.execute("SELECT username, text, views, likes, id, created_at FROM x_live WHERE created_at >= ? AND is_repost = 0",
                       (int(time.time()) - hours * 3600,)).fetchall()
    except sqlite3.OperationalError:
        return [], []
    line = lambda u, t, vw, l, i, ts: (f"- {datetime.fromtimestamp(ts, KST):%H:%M} · 조회 {vw} · 좋아요 {l} · @{u}"
                                       f"{' (' + v[u][1] + ')' if u in v and v[u][1] else ''}: {t[:300].replace(chr(10), ' ')} "
                                       f"https://x.com/{u}/status/{i.split(':', 1)[1]}")
    vip = sorted((r for r in rs if r[0] in v), key=lambda r: -r[5])[:15]
    rest = sorted((r for r in rs if r[0] not in v), key=lambda r: -(r[2] or (r[3] or 0) * 100))[:8]
    return [line(*r) for r in vip], [line(*r) for r in rest]


def telegram(run):
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return False
    lines = [f"⏰ {run['time']} 지금 발행할 거리", run["summary"], ""]
    for i, p in enumerate(run["picks"], 1):
        lines += [f"{i}. [{p['channel']}] {p['title']}{' (후속)' if p['follow_up'] else ''}", f"왜 지금: {p['why_now']}", "", p["draft"],
                  *(p["sources"][:2]), ""]
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=20,
                      json={"chat_id": chat, "text": "\n".join(lines)[:4000], "disable_web_page_preview": True})
        return True
    except requests.RequestException as e:
        print(f"⚠️ 텔레그램 실패: {e}")
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    load_env()
    if not due(a.force):
        return
    if not anthropic.ready():
        return print("⚠️ Claude Code 가 없어요 — 건너뜀")
    news, th, ig = recent_news(), hot_threads(), hot_insta()
    vip, xs = hot_x()
    if not (news or th or xs or vip):
        return print("새 재료가 없어 건너뜀")
    hist = load()
    now = datetime.now(KST)
    sent = [f"- {h['time']}: " + ", ".join(p["topic"] for p in h["picks"]) for h in hist
            if now - datetime.fromisoformat(h["at"]) <= timedelta(hours=6)]
    daily = rows("recs")[:3]
    prompt = "\n".join([
        f"지금 {now:%m/%d %H:%M} (한국시간).", "",
        "## 최근 6시간에 이미 보낸 주제 (반복 금지, 큰 새 소식만 후속으로)", *(sent or ["- 없음"]), "",
        "## 매일 아침 30일 통계 추천 (참고만 — 며칠째 같은 주제라 '지금' 뜨는 게 아닐 수 있음)",
        *[f"- {r['topic']}" for r in daily], "",
        f"## 최근 3시간 경제 뉴스 제목 ({len(news)}건)", *(news or ["- 없음"]), "",
        "## 지금 빨리 크는 쓰레드 글 (내 PC 크롤러가 잰 속도)", *(th or ["- 없음"]), "",
        "## 지금 반응이 빠른 인스타 글", *(ig or ["- 없음"]), "",
        "## 해외 핵심 인물 최근 6시간 X 글 (트럼프·백악관·재무장관·연준·머스크·속보 계정, 최신 순) — 우선 검토", *(vip or ["- 없음"]), "",
        "## 그 밖 최근 6시간 X 글 (조회 순)", *(xs or ["- 없음"]), "",
        "위 자료로 지금 발행할 글감 3개를 만들어 줘."])
    r = anthropic.Anthropic().messages.parse(model=MODEL, max_tokens=8000, system=SYSTEM, output_config={"effort": "low"},
                                             messages=[{"role": "user", "content": prompt}], output_format=Result)
    if r.parsed_output is None:
        return print(f"⚠️ 결과를 못 받았어요(stop_reason={r.stop_reason}) — 다음 차례에 다시")
    run = {"slot": now.strftime("%Y-%m-%d %H"), "at": now.isoformat(timespec="seconds"), "time": now.strftime("%m/%d %H:%M"),
           "summary": r.parsed_output.summary, "picks": [p.model_dump() for p in r.parsed_output.picks[:3]],
           "inputs": {"news": len(news), "threads": len(th), "insta": len(ig), "x_vip": len(vip), "x": len(xs)}}
    OUT.write_text(json.dumps([run] + hist[:KEEP - 1], ensure_ascii=False, indent=1), encoding="utf-8")
    ok = telegram(run)
    print(f"✅ 지금 발행할 거리 {len(run['picks'])}개 ({', '.join(p['topic'] for p in run['picks'])}) · 텔레그램 {'보냄' if ok else '못 보냄'} · "
          f"입력 {r.usage.input_tokens:,} / 출력 {r.usage.output_tokens:,} 토큰")


if __name__ == "__main__":
    main()
