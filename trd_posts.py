"""트레이더스 방(토픽)별 '오늘 올릴 글' 자동 작성 → output/site/trd_posts.json → 사이트 텔레그램 > 트레이더스 방.

재료: 오늘 뉴스 헤드라인·구글 이슈·X/트루스 브리핑(tg_analyze 와 같은 것) + 폴더별 크롤링 소재·연구 근거(trd_research.py)
     + 실제 시세(야후 차트·업비트, 키 필요 없음) + 방별 통계(trd_rooms.json).
숫자는 코드가 가져온 시세만 쓰고, 없는 숫자는 [확인] 으로 남긴다. 회원 이름·원문은 넣지 않는다.

  python trd_posts.py            # 지금 이후 시각의 글만 새로 씀 (같은 날 앞선 글은 그대로 둠)
  python trd_posts.py --force    # 오늘 글 전부 다시 (사이트 '오늘 글 전부 새로 만들기')
  python trd_posts.py --room coin --room talk   # 그 폴더 글만 지금 다시 (사이트 '이 폴더 글 새로 만들기'), 자동 작성 차례는 그대로
  python trd_posts.py --due      # 07·18시 차례면 0, 아니면 3 (워크플로용)
  python trd_posts.py --dry-run  # Claude 없이 재료만 출력
"""
import argparse
import hashlib
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import List

from common import OUTPUT_DIR, load_env

KST = timezone(timedelta(hours=9))
MODEL = "claude-opus-5-5"   # 텔레그램 문구 = Opus (2026-10-26 대표 결정)
SITE = OUTPUT_DIR / "site"
OUT = SITE / "trd_posts.json"
REFRESH_HOURS = (7, 18)   # 07시: 하루 글 전부 · 18시: 저녁 글만 최신 뉴스로 (tg_analyze 뉴스 갱신 시각과 맞춤)

# 방별로 올릴 글 — (방 이름, 시각, 종류, 쓰는 법)
SLOTS = [
    ("중요 뉴스 및 중요 한마디", "08:00", "아침 뉴스", "밤사이·오늘 아침 핵심 뉴스 3~5줄(한 줄에 하나, 왜 중요한지 짧게) + 오늘 시간대별 일정 + 운영자 한마디 1줄"),
    ("공지사항", "08:30", "오늘 운영 안내", "오늘 라이브 시간은 [확인]으로 비워 두고, 이번 주 미션·이달 왕 선정 남은 기간(이름 없이)을 3~4줄로. 월요일이면 이번 주 안내 형식"),
    ("주식토큰방", "08:50", "오늘 볼 토큰", "이 방은 주식을 USDT 토큰(예: SKHYNIXUSDT, NVDAUSDT)으로 매매하는 사람들 방. 오늘 재료가 있는 토큰 3개: 왜 움직이는지 + 위험 한 줄. 진입가·목표가는 쓰지 말고 회원 의견을 묻기"),
    ("코인 관점 공유방", "10:00", "오전 코인", "비트코인·이더리움 흐름, 김치프리미엄, 오늘 볼 가격대, 일정(FOMC·CPI 등) + 회원 의견을 묻는 질문 1개"),
    ("소통방", "10:30", "오늘의 질문", "기여왕 연결: 초보도 답할 수 있는 오늘의 질문 1개를 던지고 '답장 기능으로 답해 주시면 기여왕 점수' 안내. 짧고 가볍게"),
    ("트레이더 관점 공유방", "11:00", "시나리오 초안", "트레이더가 고쳐 쓸 초안: 상승이면 / 하락이면 대응 원칙 (가격대는 받은 시세 기준) + 라이브에서 다룰 질문 1개"),
    ("주식토큰방", "15:40", "장 마감 토큰 정리", "오늘 국내장 마감에서 움직인 종목을 토큰 관점으로 3줄 + 오늘 밤 미장에서 볼 것. 주말·휴장이면 미장·코인 주말 체크"),
    ("수익 인증방", "16:00", "매매일지 미션", "성장왕 연결: 오늘 일지 양식(티커/포지션, 레버리지, 평단가, 비중, 진입 근거, 손실 대응, 결과와 복기) + 손절도 복기하면 인정된다는 한 줄. 지어낸 수익·회원 사례 금지"),
    ("중요 뉴스 및 중요 한마디", "18:00", "저녁 관전 포인트", "오늘 밤 미장·코인에서 볼 일정·뉴스 3개 + 한마디"),
    ("소통방", "20:00", "저녁 토론거리", "소통방 소재 중 오늘 가장 큰 화제 하나를 쉽게 풀고 '어떻게 보시나요'로 끝내기. 3~5줄"),
    ("기초가이드 & 공부방", "21:00", "오늘의 개념", "회원이 자주 묻는 비중·평단·추매·손절 또는 오늘 뉴스 용어 중 하나를 초보도 알게 쉽게, 오늘 시세를 예시로 + '궁금한 점은 답장으로'"),
    ("코인 관점 공유방", "22:00", "밤 코인", "미장 개장 뒤 코인 흐름, 밤사이 볼 가격대·일정 + 질문 1개"),
]

TICKERS = {"^KS11": "코스피", "^KQ11": "코스닥", "005930.KS": "삼성전자", "000660.KS": "SK하이닉스", "KRW=X": "원/달러 환율",
           "^GSPC": "S&P500", "^IXIC": "나스닥", "NVDA": "엔비디아", "TSLA": "테슬라", "MU": "마이크론", "SOXL": "SOXL", "COIN": "코인베이스", "^TNX": "미국 10년물 금리",
           "DX-Y.NYB": "달러 인덱스", "GC=F": "금 선물", "BTC-USD": "비트코인(달러)", "ETH-USD": "이더리움(달러)",
           "SOL-USD": "솔라나(달러)", "XRP-USD": "리플(달러)"}

SYSTEM = """당신은 텔레그램 투자 커뮤니티 '트레이더스'(포럼형 그룹, 주제방 여러 개)의 운영자 글을 대신 쓰는 카피라이터입니다.
운영자가 각 주제방에 그대로 복사해 올릴 글을 씁니다.

규칙:
- 숫자(지수·가격·등락률·김프)는 '시세' 자료에 있는 값만 쓰세요. 자료에 없는 숫자가 필요하면 [확인] 이라고 쓰고, check 에 무엇을 확인할지 적으세요.
- 뉴스는 '자료'의 헤드라인·브리핑에 있는 것만. 지어내지 마세요. 날짜·요일을 확인해 이미 지난 일정을 앞으로 할 일처럼 쓰지 마세요.
- 회원 이름·아이디·회원 글 인용 금지.
- 매수·매도 권유, 목표가 단정, 수익 보장 표현 금지. '볼 가격대', '이렇게 대응' 같은 관점으로. 코인·주식 관점 글 끝에는 '※ 정보 제공용이며 투자 판단은 본인 책임입니다.' 한 줄.
- 텔레그램에 바로 붙여 넣는 글: 이모지는 줄 머리에 1개 정도, 줄바꿈으로 읽기 쉽게, 마크다운(**, #) 쓰지 말 것. 길이는 3~10줄.
- 방마다 성격이 다르니 같은 뉴스를 반복하지 말고 각 방에 맞는 각도로.
- '폴더 자료'의 소재는 다른 채널 글이에요. 문장을 베끼지 말고 자기 말로 쓰세요. 소재에만 나온 숫자·사실은 check 에 '원문 확인'으로 남기세요. 연구 근거에서 반응이 큰 형식을 참고하세요.
- 방 통계(많이 쓰는 시각, 답장 없는 질문 등)와 지난 피드백을 참고해 회원이 답장하고 싶어지게 끝내세요."""


def market():
    """실제 시세 — {이름: {close, d1(%), date}} + 비트코인 김치프리미엄. 못 가져온 건 뺀다."""
    out = {}
    for t, name in TICKERS.items():
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(t)}?range=10d&interval=1d"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            r = json.load(urllib.request.urlopen(req, timeout=20))["chart"]["result"][0]
        except Exception as e:
            print("⚠️ 시세 못 가져옴:", t, e)
            continue
        rows = [(c, ts) for c, ts in zip(r["indicators"]["quote"][0]["close"], r["timestamp"]) if c is not None]
        if len(rows) < 2:
            continue
        price = r["meta"].get("regularMarketPrice") or rows[-1][0]
        at = r["meta"].get("regularMarketTime") or rows[-1][1]
        # 마지막 일봉이 지금 거래일이면 그 전날 종가와, 아니면 마지막 일봉과 비교
        prev = rows[-2][0] if abs(rows[-1][1] - at) < 86400 else rows[-1][0]
        out[name] = {"close": round(price, 2), "d1": round((price / prev - 1) * 100, 2),
                     "date": datetime.fromtimestamp(at, KST).strftime("%m/%d %H:%M")}
    try:
        req = urllib.request.Request("https://api.upbit.com/v1/ticker?markets=KRW-BTC,KRW-ETH", headers={"User-Agent": "Mozilla/5.0"})
        for u in json.load(urllib.request.urlopen(req, timeout=20)):
            coin = "비트코인" if u["market"] == "KRW-BTC" else "이더리움"
            out[f"{coin}(업비트 원화)"] = {"close": u["trade_price"], "d1": round(u["signed_change_rate"] * 100, 2), "date": "지금"}
        usd, fx = out.get("비트코인(달러)"), out.get("원/달러 환율")
        if usd and fx:
            out["비트코인 김치프리미엄(%)"] = {"close": round((out["비트코인(업비트 원화)"]["close"] / (usd["close"] * fx["close"]) - 1) * 100, 2)}
    except Exception as e:
        print("⚠️ 업비트 시세 못 가져옴:", e)
    return out


def rooms_context():
    p = SITE / "trd_rooms.json"
    if not p.exists():
        return {}
    d = json.loads(p.read_text(encoding="utf-8"))
    fb = {r["title"]: r for r in ((d.get("ai") or {}).get("rooms") or [])}
    keys = ("msgs", "per_day", "last7", "trend", "peak_hours", "questions", "unanswered", "react_avg", "closed")
    return {r["title"]: {**{k: r.get(k) for k in keys}, "지난 피드백": (fb.get(r["title"]) or {}).get("problem", "")}
            for r in d.get("rooms", [])}


def is_due(now):
    passed = [h for h in REFRESH_HOURS if now.hour >= h]
    if not passed:
        return False
    if not OUT.exists():
        return True
    last = json.loads(OUT.read_text(encoding="utf-8") or "{}").get("generated_at", "")
    slot_start = now.replace(hour=passed[-1], minute=0, second=0, microsecond=0)
    return not last or datetime.fromisoformat(last).astimezone(KST) < slot_start


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--due", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--room", action="append", help="trd_folders.json 의 폴더 id")
    args = ap.parse_args()
    now = datetime.now(KST)
    if args.due:
        sys.exit(0 if is_due(now) else 3)
    load_env()
    from tg_analyze import news_context
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    today = now.strftime("%Y-%m-%d")
    same_day = old.get("date") == today
    written_today = old.get("generated_at", "").startswith(today)   # 폴더만 다시 쓴 건 generated_at 을 안 바꿔서, 그날 자동 첫 작성이 그대로 돈다
    hm = now.strftime("%H:%M")
    fp = SITE / "trd_folders.json"
    folder_rows = json.loads(fp.read_text(encoding="utf-8")).get("folders", []) if fp.exists() else []
    rooms = None
    if args.room:
        ids = {f["id"]: f["room"] for f in folder_rows}
        if not set(args.room) <= set(ids):
            sys.exit(f"없는 폴더: {sorted(set(args.room) - set(ids))}")
        rooms = {ids[i] for i in args.room}
    manual = args.force or bool(rooms)
    # 지금 이후 시각만 새로 (오늘 앞선 글은 이미 올렸을 수 있으니 그대로). --force 나 새 날 첫 실행(07시 전 수동 포함)은 전부
    todo = [s for s in SLOTS if s[0] in rooms] if rooms else SLOTS if args.force or not written_today or hm < "07:00" else [s for s in SLOTS if s[1] > hm]
    if not todo:
        return print("오늘 남은 올릴 시각이 없어요 — 내일 07시에 새로 써요.")

    news = news_context()
    folders = {f["room"]: {"역할": f["role"], "넣을 것": [i["what"] for i in f["items"]], "연구 근거": f["research"],
                           "소재": [{"채널": x["chat"], "평소 대비": x["x"], "글": x["text"][:220]} for x in f["sources"][:4]]}
               for f in folder_rows if not rooms or f["room"] in rooms}
    news_key = hashlib.sha1(json.dumps([news["headlines"][:10], news["x_truth_briefing"], [s[1] for s in todo], today],
                                       ensure_ascii=False).encode()).hexdigest()
    if not manual and old.get("news_key") == news_key:
        return print("뉴스가 지난번과 같아 트레이더스 글을 다시 쓰지 않아요 (비용 절약).")
    quotes = market()
    ctx = {"now": now.strftime("%Y-%m-%d (%a) %H:%M KST"), "시세": quotes, "오늘 뉴스": news, "폴더 자료": folders,
           "방 통계": {k: v for k, v in rooms_context().items() if not rooms or k in rooms},
           "써야 할 글": [{"no": i, "room": r, "time": t, "kind": k, "how": how} for i, (r, t, k, how) in enumerate(todo, 1)]}
    prompt = "자료:\n" + json.dumps(ctx, ensure_ascii=False, indent=1) + "\n\n'써야 할 글'의 no 마다 하나씩, 빠짐없이 쓰세요."
    if manual:
        prompt += "\n운영자가 버튼을 눌러 지금 바로 쓰는 글이에요. time 이 now 보다 지난 글은 지금 올려도 맞도록 지금 시점 기준으로 쓰세요."
    from feedback import feedback_prompt
    prompt += feedback_prompt(["트레이더스", "트레이더스 글"])
    if args.dry_run:
        return print(prompt[:6000])
    if not __import__("llm").ready():
        return print("Claude Code(Max) 가 없는 곳이라 트레이더스 글을 건너뛰어요 — 지난 결과를 유지해요.")

    import llm as anthropic   # 내 PC Claude Code(Max 구독)로 실행 — API 요금 없음
    from pydantic import BaseModel

    class Post(BaseModel):
        no: int
        title: str        # 사이트 카드 제목 (10~20자)
        text: str         # 그대로 붙여 넣을 글
        check: List[str]  # 올리기 전 확인할 것 ([확인] 자리 등). 없으면 빈 목록
        based_on: str     # 어떤 뉴스·시세를 썼는지 한 줄

    class Out(BaseModel):
        theme: str        # 오늘 그룹 전체를 꿰는 한 줄 테마
        posts: List[Post]

    try:
        r = anthropic.Anthropic().messages.parse(model=MODEL, max_tokens=12000, system=SYSTEM,
                                                 messages=[{"role": "user", "content": prompt}], output_format=Out)
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
        return print(f"⚠️ Claude API 오류: {e} — 지난 결과를 유지해요.")
    if r.stop_reason != "end_turn" or r.parsed_output is None:
        return print(f"⚠️ 결과를 받지 못했어요(stop_reason={r.stop_reason}) — 지난 결과를 유지해요.")
    a = r.parsed_output
    new = [{"room": todo[p.no - 1][0], "time": todo[p.no - 1][1], "kind": todo[p.no - 1][2], **p.model_dump(exclude={"no"}),
            **({"made_at": now.isoformat(timespec="seconds")} if manual else {})}
           for p in a.posts if 1 <= p.no <= len(todo)]
    if rooms:
        keep = [p for p in old.get("posts", []) if same_day and p["room"] not in rooms]
    else:
        keep = [p for p in old.get("posts", []) if written_today and not args.force and p["time"] <= hm and hm >= "07:00"]
    posts = sorted(keep + new, key=lambda p: p["time"])
    OUT.write_text(json.dumps({"date": today, "generated_at": old.get("generated_at", "") if rooms else now.isoformat(timespec="seconds"),
                               "theme": old.get("theme", a.theme) if rooms and same_day else a.theme,
                               "market": {k: v for k, v in quotes.items()}, "posts": posts, "news_key": old.get("news_key", "") if rooms else news_key},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ 트레이더스 올릴 글 {len(new)}개 새로 (유지 {len(keep)}개) · 입력 {r.usage.input_tokens:,} / 출력 {r.usage.output_tokens:,} 토큰")


if __name__ == "__main__":
    main()
