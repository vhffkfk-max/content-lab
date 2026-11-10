"""올릴 자료함 — 다른 경제 채널과 우리 방(말희아빠 채널·트레이더스 그룹)을 비교해 '오늘 올릴 자료'를 만들고 대표 폰 텔레그램으로 보낸다.

대표가 검토 → 복사해서 직접 올림 (방에 자동으로 올리지 않는다). 올렸는지는 usage_audit.py 가 실제 채널 글과 맞춰 본다.

  python tg_inbox.py               # 지금 만들기 (사이트 파일만)
  python tg_inbox.py --send        # 만들고 봇으로 대표에게 보내기
  python tg_inbox.py --due         # 08·17시 차례면 0, 아니면 3 (local_ai 용)
  python tg_inbox.py --stats       # Claude 없이 비교 숫자만 출력
  python tg_inbox.py --dry-run     # Claude 없이 프롬프트만 출력

재료: tg_live 가 쌓는 data/telegram_history.db (개발 폴더에 있음, 읽기만) + 트레이더스 폴더·방 통계(trd_folders/trd_rooms) + 오늘 뉴스·시세.
채널은 한 방향 방송, 트레이더스는 회원이 대화하는 포럼형 그룹이라 글을 따로 쓴다. 트레이더스 매매 콜(진입·익절·손절)은 쓰지 않는다
(콜 양식은 대표와 시험 중 — 자동 반영 금지). 다른 채널 문장은 베끼지 않고 사실·숫자만, 출처를 남긴다.
"""
import argparse
import json
import os
import re
import sqlite3
import statistics as st
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

from common import OUTPUT_DIR, ROOT, load_env

KST = timezone(timedelta(hours=9))
SITE = OUTPUT_DIR / "site"
OUT = SITE / "tg_inbox.json"
MODEL = "claude-opus-5-5"   # 텔레그램 문구 = Opus (2026-10-26 대표 결정)
SLOTS = (8, 17)             # 08시: 장 전·오전용 · 17시: 장 마감 뒤·저녁용
OURS = "-1003746144429"     # 차트보는 말희아빠 (채널)
DAYS = 30
HOT_HOURS = 36
N_CHANNEL, N_TRADERS = 4, 3
LOG_DAYS = 14


def history_db():
    for p in (ROOT / "data" / "telegram_history.db", Path.home() / "Desktop" / "솔개" / "insta-research" / "data" / "telegram_history.db"):
        if p.exists():
            return sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True, timeout=30)
    sys.exit("data/telegram_history.db 가 없어요 (tg_live.py 가 개발 폴더에 쌓아요).")


def posts(db, since):
    """앨범(사진 여러 장)은 한 글로 묶는다. 글자가 있는 칸의 글자를 쓴다."""
    rows = db.execute("""SELECT m.chat_id, m.id, m.date, m.text, m.views, m.forwards, m.reactions, m.media, m.has_link, m.is_forward,
                                m.grouped_id, c.title, c.username, c.members, c.role, c.kind
                         FROM msgs m JOIN chats c ON c.id = m.chat_id WHERE m.date >= ? ORDER BY m.date""", (since,)).fetchall()
    latest = dict(db.execute("SELECT chat_id, count FROM members m WHERE date = (SELECT MAX(date) FROM members WHERE chat_id = m.chat_id)"))
    out, seen = [], {}
    for r in rows:
        x = dict(zip(("chat", "id", "date", "text", "views", "fwd", "react", "media", "link", "is_fwd", "grp", "title", "user", "members", "role", "kind"), r))
        x["members"] = latest.get(x["chat"]) or x["members"]   # 채널 정보는 처음 모을 때 값이라, 매일 세는 구독자 수를 쓴다
        if x["grp"]:
            k = (x["chat"], x["grp"])
            if k in seen:
                y = seen[k]
                y["text"] = y["text"] or x["text"]
                for f in ("views", "fwd", "react"):
                    y[f] = max(y[f] or 0, x[f] or 0)
                continue
            seen[k] = x
        out.append(x)
    return out


def at(x):
    return datetime.fromisoformat(x["date"]).astimezone(KST)


def link(x):
    return f"https://t.me/{x['user']}/{x['id']}" if x["user"] else ""


def compare(ps):
    """채널마다 최근 30일 숫자. reach = 글 조회 중앙값 ÷ 구독자."""
    by = defaultdict(list)
    for x in ps:
        if x["kind"] == "채널":
            by[x["chat"]].append(x)
    rows = []
    for chat, xs in by.items():
        v = [x["views"] or 0 for x in xs]
        if len(xs) < 5 or not any(v):
            continue
        med = st.median(v)
        sv = sum(v) or 1
        hours = defaultdict(list)
        for x in xs:
            hours[at(x).hour].append((x["views"] or 0) / (med or 1))
        best = sorted(((st.median(h), k) for k, h in hours.items() if len(h) >= 3), reverse=True)[:3]
        days = max(1, (at(xs[-1]) - at(xs[0])).days or 1)
        rows.append({"chat": chat, "title": xs[0]["title"], "user": xs[0]["user"], "mine": xs[0]["role"] == "mine",
                     "members": xs[0]["members"], "posts_day": round(len(xs) / days, 1), "views_med": int(med),
                     "reach_pct": round(med / xs[0]["members"] * 100, 1) if xs[0]["members"] else None,
                     "react_1k": round(sum(x["react"] or 0 for x in xs) / sv * 1000, 1),
                     "fwd_1k": round(sum(x["fwd"] or 0 for x in xs) / sv * 1000, 1),
                     "photo_pct": round(sum(x["media"] in ("사진", "영상") for x in xs) / len(xs) * 100),
                     "link_pct": round(sum(bool(x["link"]) for x in xs) / len(xs) * 100),
                     "len_med": int(st.median(len(x["text"] or "") for x in xs)),
                     "best_hours": [f"{k:02d}시" for _, k in best]})
    rows.sort(key=lambda r: -(r["reach_pct"] or 0))
    return rows


def hot(ps, meds, now):
    """최근 36시간, 그 채널 평소(30일 중앙값)보다 잘 나간 글 — 올린 지 2시간 넘은 것만 (조회가 쌓일 시간)."""
    cut, young = now - timedelta(hours=HOT_HOURS), now - timedelta(hours=2)
    xs = [x for x in ps if x["role"] != "mine" and x["kind"] == "채널" and cut <= at(x) <= young
          and len((x["text"] or "").strip()) >= 40 and meds.get(x["chat"])]
    for x in xs:
        x["ratio"] = round((x["views"] or 0) / meds[x["chat"]], 1)
    xs.sort(key=lambda x: -x["ratio"])
    out, per = [], defaultdict(int)
    for x in xs:
        if per[x["chat"]] >= 2:
            continue
        per[x["chat"]] += 1
        out.append(x)
        if len(out) >= 16:
            break
    return out


def ours(ps, meds, now):
    xs = [x for x in ps if x["chat"] == OURS and at(x) >= now - timedelta(days=14)]
    med = meds.get(OURS) or 1
    first = lambda x: re.sub(r"\s+", " ", (x["text"] or "(사진만)").strip())[:90]
    rank = sorted(xs, key=lambda x: -(x["views"] or 0))
    row = lambda x: {"시각": at(x).strftime("%m/%d %H:%M"), "첫 줄": first(x), "평소 대비": round((x["views"] or 0) / med, 2),
                     "반응": x["react"] or 0, "형식": x["media"], "글자 수": len(x["text"] or "")}
    return {"잘 된 글": [row(x) for x in rank[:6]], "덜 본 글": [row(x) for x in rank[-4:] if x["text"]],
            "최근 3일 올린 것(겹치지 않게)": [first(x) for x in xs if at(x) >= now - timedelta(days=3) and x["text"]][-15:]}


def traders():
    def load(n):
        p = SITE / f"{n}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    rooms = [{k: r.get(k) for k in ("title", "per_day", "last7", "trend", "peak_hours", "questions", "unanswered", "react_avg")}
             for r in load("trd_rooms").get("rooms", [])]
    folders = [{"폴더": f["room"], "역할": f["role"], "넣을 것": [i["what"] for i in f.get("items", [])][:3]} for f in load("trd_folders").get("folders", [])]
    done = [p.get("title") for p in load("trd_posts").get("posts", [])]
    return {"방 통계(최근)": rooms, "폴더 역할": folders, "오늘 이미 만든 자동 글 제목(겹치지 않게)": done}


SYSTEM = """당신은 경제 텔레그램 두 곳의 편집자입니다. 대표가 검토한 뒤 직접 복사해 올릴 '오늘 올릴 자료'를 만듭니다.

두 방은 성격이 다릅니다. 섞지 마세요.
1) 차트보는 말희아빠 — 채널(한 방향 방송, 구독자 약 880명). 대표 이름 '말희아빠'. 차트·시황을 짧게 정리하는 톤.
   폰에서 한눈에: 첫 줄이 훅(숫자나 비교), 줄마다 짧게, 이모지는 줄머리 표시용으로만 조금. 300~600자.
   마지막 줄은 '투자 판단은 본인 몫입니다.' 같은 짧은 고지.
2) 트레이더스 — 포럼형 그룹(주제 폴더 여러 개, 회원 약 260명). 회원이 답하게 만드는 글이 목적.
   어느 폴더에 올릴지 정하고, 질문 하나로 끝내세요. 200~450자.
   매매 콜(진입가·익절가·손절가·레버리지 지시)과 '사라/팔아라'는 절대 쓰지 않습니다.

비교 자료로 판단하세요.
- '채널 비교'는 최근 30일 숫자입니다(reach_pct = 글 조회 중앙값 ÷ 구독자). 우리 채널(mine=true)과 잘 되는 채널의 차이(시간대·사진·길이·링크·글 수)를 보고, 그 차이를 메우는 쪽으로 글을 고르세요.
- '다른 채널에서 평소보다 잘 나간 글'(S번호)은 소재 후보입니다. 그 채널의 문장을 베끼지 말고, 사실·숫자만 가져와 우리 말투로 새로 쓰세요.
  다른 채널 이름은 본문에 쓰지 않습니다. 쓴 소재의 S번호는 based_on 에 남기세요.
- '우리 채널 최근'의 잘 된 글 형식을 따르고, 최근 3일 올린 것·오늘 자동 글과 같은 주제는 피하세요.
- 숫자는 '시세'와 S번호 원문에 있는 것만. 없으면 [확인] 으로 남기고 check 에 적으세요. 날짜·시각 기준(장중/종가)을 붙이세요.

출력
- insights: 우리 방과 잘 되는 채널의 차이 3줄(숫자 포함, 무엇을 바꾸면 되는지까지).
- items: 말희아빠 채널 {n_ch}개 + 트레이더스 {n_tr}개. time 은 올리기 좋은 시각(HH:MM, 지금 이후).
  why 는 '왜 이 글·이 시각인지'를 비교 숫자로 한 줄. 서로 다른 소재로.
- 본문(text)에는 올릴 글만. '캡처 첨부' 같은 안내는 본문에 넣지 말고 photo 에 '붙일 사진'을 한 줄로(없으면 빈칸)."""


def load_old():
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def is_due(now):
    passed = [h for h in SLOTS if now.hour >= h]
    if not passed:
        return False
    made = load_old().get("made_at", "")
    return not made or datetime.fromisoformat(made) < now.replace(hour=passed[-1], minute=0, second=0, microsecond=0)


def send(items, insights, now):
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return print("⚠️ 봇 설정이 없어 보내지 않았어요.")

    def msg(text):
        data = urllib.parse.urlencode({"chat_id": chat, "text": text[:4000], "disable_web_page_preview": "true"}).encode()
        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=20)

    head = [f"📥 올릴 자료 {len(items)}개 ({now:%m/%d %H:%M})", "검토하고 고쳐서 직접 올려 주세요. 방에는 아무것도 올리지 않았어요.", ""]
    head += [f"· {i}" for i in insights]
    msg("\n".join(head))
    for n, it in enumerate(items, 1):
        where = it["room"] + (f" › {it['folder']}" if it.get("folder") else "")
        meta = [f"[{n}] {where} · 추천 {it['time']}", f"💡 {it['why']}"]
        if it.get("photo"):
            meta.append("📷 사진: " + it["photo"])
        if it["check"]:
            meta.append("✔️ 확인: " + " / ".join(it["check"]))
        if it["sources"]:
            meta.append("📎 근거: " + " ".join(s["link"] for s in it["sources"] if s["link"]))
        msg("\n".join(meta))
        msg(it["text"])   # 본문만 따로 — 길게 눌러 복사하거나 그대로 전달
    print(f"📨 봇으로 {len(items)}개 보냄")


def main():
    ap = argparse.ArgumentParser()
    for f in ("send", "due", "stats", "dry-run"):
        ap.add_argument(f"--{f}", action="store_true")
    a = ap.parse_args()
    now = datetime.now(KST)
    if a.due:
        sys.exit(0 if is_due(now) else 3)
    db = history_db()
    ps = posts(db, (now - timedelta(days=DAYS)).astimezone(timezone.utc).isoformat())
    table = compare(ps)
    meds = {r["chat"]: r["views_med"] for r in table}
    if a.stats:
        for r in table:
            print(("★ " if r["mine"] else "  ") + json.dumps({k: v for k, v in r.items() if k not in ("chat", "user", "mine")}, ensure_ascii=False))
        return
    hs = hot(ps, meds, now)
    src = {f"S{i}": x for i, x in enumerate(hs, 1)}
    load_env()
    from tg_analyze import news_context
    from trd_posts import market
    old = load_old()
    keep = ("title", "posts_day", "views_med", "reach_pct", "react_1k", "fwd_1k", "photo_pct", "link_pct", "len_med", "best_hours", "mine")
    ctx = {"now": now.strftime("%Y-%m-%d (%a) %H:%M KST"),
           "채널 비교(30일, reach 높은 순 상위 8 + 우리)": [{k: r[k] for k in keep} for r in table[:8] + [r for r in table if r["mine"] and r not in table[:8]]],
           "다른 채널에서 평소보다 잘 나간 글(36시간)": [{"no": k, "채널": x["title"], "시각": at(x).strftime("%m/%d %H:%M"), "평소 대비": x["ratio"],
                                                "형식": x["media"], "글": (x["text"] or "")[:380]} for k, x in src.items()],
           "우리 채널 최근(14일)": ours(ps, meds, now), "트레이더스": traders(),
           "시세": market(), "오늘 뉴스": news_context(),
           "최근 만든 자료(겹치지 않게)": [x["title"] for x in old.get("log", [])][-30:]}
    prompt = "자료:\n" + json.dumps(ctx, ensure_ascii=False, indent=1)
    from feedback import feedback_prompt
    prompt += feedback_prompt(["텔레그램 문구", "트레이더스 글", "올릴 자료함"])
    system = SYSTEM.replace("{n_ch}", str(N_CHANNEL)).replace("{n_tr}", str(N_TRADERS))
    if a.dry_run:
        return print(system + "\n\n" + prompt[:9000])
    import llm as anthropic   # 내 PC Claude Code(Max 구독) — API 요금 없음
    if not anthropic.ready():
        return print("Claude Code(Max) 가 없는 곳이라 건너뛰어요.")
    from pydantic import BaseModel

    class Item(BaseModel):
        room: str          # '말희아빠 채널' 또는 '트레이더스'
        folder: str        # 트레이더스면 올릴 폴더 이름, 채널이면 빈칸
        time: str          # 올리기 좋은 시각 HH:MM
        title: str         # 10~20자
        text: str          # 그대로 붙여 넣을 본문
        why: str           # 비교 숫자로 한 줄
        based_on: List[str]  # 쓴 소재의 S번호
        check: List[str]   # 올리기 전 확인할 것
        photo: str         # 같이 붙일 사진·캡처 (없으면 빈칸)

    class Out(BaseModel):
        insights: List[str]
        items: List[Item]

    try:
        r = anthropic.Anthropic().messages.parse(model=MODEL, max_tokens=12000, system=system,
                                                 messages=[{"role": "user", "content": prompt}], output_format=Out)
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
        return print(f"⚠️ Claude 오류: {e} — 지난 자료를 유지해요.")
    if r.parsed_output is None:
        return print(f"⚠️ 결과를 받지 못했어요(stop_reason={r.stop_reason}) — 지난 자료를 유지해요.")
    o = r.parsed_output
    items = []
    for i, it in enumerate(sorted(o.items, key=lambda x: x.room), 1):
        d = it.model_dump(exclude={"based_on"})
        d["room"] = "트레이더스" if "트레이더" in d["room"] else "말희아빠 채널"
        if d["room"] != "트레이더스":
            d["folder"] = ""
        d["id"] = f"{now:%m%d%H}-{i}"
        d["sources"] = [{"no": k, "chat": src[k]["title"], "link": link(src[k]), "ratio": src[k]["ratio"]} for k in it.based_on if k in src]
        items.append(d)
    log = [x for x in old.get("log", []) if x["at"] >= (now - timedelta(days=LOG_DAYS)).isoformat()]
    log += [{"at": now.isoformat(timespec="seconds"), "room": x["room"], "title": x["title"]} for x in items]
    OUT.write_text(json.dumps({"made_at": now.isoformat(timespec="seconds"), "insights": o.insights, "items": items,
                               "compare": [{k: r[k] for k in keep + ("members",)} for r in table], "log": log},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ 올릴 자료 {len(items)}개 · 입력 {r.usage.input_tokens:,} / 출력 {r.usage.output_tokens:,} 토큰")
    if a.send:
        send(items, o.insights, now)


if __name__ == "__main__":
    main()
