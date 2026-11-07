"""트레이더스 폴더(토픽) 8개 연구 — 크롤링한 다른 방 글로 '폴더별 넣을 것·이유·근거·오늘 소재'를 계속 갱신한다.

tg_live.py 가 30분마다 build() 로 output/site/trd_folders.json 을 만들고, 하루 한 번 refresh_own() 으로 우리 방 성적을 읽는다.
Claude 를 부르지 않는다. trd_posts.py 가 이 파일을 재료로 폴더별 글을 쓴다.
다른 방은 채널 글만 소재로 쓰고(그룹 회원 글 제외), 우리 방은 숫자만 남긴다 (회원 이름·원문 저장 안 함).

  python trd_research.py          # 지금 DB 로 trd_folders.json 만들기 (우리 방 성적은 지난 값)
"""
import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from common import DATA_DIR, OUTPUT_DIR
from tg_collect import link_of

KST = timezone(timedelta(hours=9))
OWN = DATA_DIR / "trd_own.json"
OUT = OUTPUT_DIR / "site" / "trd_folders.json"
RESEARCH_DAYS, SOURCE_HOURS, CAP_X = 30, 48, 20

FORMATS = {
    "수익 인증·익절": r"익절|수익\s*인증|수익 ?실현|수익률|매매일지",
    "복기·원칙·멘탈": r"복기|멘탈|원칙|뇌동|손실 ?관리",
    "미장 종목·실적": r"실적|가이던스|엔비디아|테슬라|마이크론|나스닥|s&p|하이닉스|삼성전자",
    "주식토큰": r"[a-z]{2,}usdt|주식\s*토큰|토큰화",
    "코인 시황": r"비트코인|\bbtc\b|이더리움|\beth\b|알트|도미넌스|김프",
    "포지션 공유": r"\b(long|short)\b|진입|\btp\b|\bsl\b|손절가",
    "차트·수급": r"차트|지지|저항|이평|추세|매물대|돌파|눌림|수급",
    "속보·뉴스": r"속보|breaking|단독|발표|연준|관세",
    "일정·체크리스트": r"일정|캘린더|체크리스트|오늘의 주요|이번 주",
    "시황 정리": r"시황|마감|장 시작|개장",
    "개념 설명": r"이란\?|뜻은|쉽게|개념|용어|원리",
    "질문·참여": r"\?\s*$|어떻게 보|의견|투표|여러분",
    "공지·안내": r"공지|이벤트|안내|참여 방법",
}
ADS = re.compile(r"에어드랍|레퍼럴|페이백|수수료 할인|무료방|입장 링크|가입하|광고|리딩방|상담|보고서명:|기업명:", re.I)   # 광고·자동 공시
MARKET = re.compile(r"시장|증시|비트|코인|\bbtc\b|\beth\b|이더|금리|연준|나스닥|코스피|코스닥|환율|주식|달러|관세|실적|반도체|매매|차트|손절|익절", re.I)
MIN_BASE = 5   # 평소 반응이 거의 0인 채널이 몇 배로 부풀지 않게
MIN_X = 1.2   # 평소보다 커지지 않은 글은 소재로 안 씀
FEEDS = {"COINNESS News Feed (코인니스)"}   # 뉴스만 흘리는 곳 — 복기·공부 소재로는 안 씀

# 폴더 = 텔레그램 토픽과 같은 이름·순서. items 는 (넣을 것, 이유). 근거 숫자는 build() 가 research 로 매번 새로 계산한다
FOLDERS = [
    dict(id="notice", room="공지사항", icon="📌", access="운영진만 올림", role="회원이 놓치면 안 되는 것만 남기는 곳",
         items=[("오늘 라이브 시간과 이번 주 미션", "회원 글에 '오늘도 라방인가요'처럼 시간을 묻는 말이 나와요. 시간을 정해 두면 놓치는 사람이 줄어요."),
                ("테더 이벤트 중간 체크 (활동왕·수익왕·정보왕, 이름 빼고 기준·남은 기간)", "상품이 걸린 경쟁은 진행 상황을 볼 때 움직여요."),
                ("규칙과 인증 양식 고정", "처음 들어온 회원이 물어보지 않아도 되게 해 줘요.")],
         formats=["공지·안내", "일정·체크리스트"], pattern=None),
    dict(id="coin", room="코인 관점 공유방", icon="🪙", access="회원도 올림", role="오늘 코인을 어떻게 볼지 나누는 곳",
         items=[("비트·이더 오전·밤 시나리오와 볼 가격대", "회원 대화와 질문이 비트·이더에 가장 많이 몰려요."),
                ("김프·도미넌스처럼 판단에 쓰는 지표 한 줄", "운영진도 도미넌스 분석을 올리고 있고, 숫자를 실제 시세로 넣을 수 있어요."),
                ("끝에 의견을 묻는 질문", "회원이 관점을 올리게 해야 트레이더만 말하는 방이 안 돼요.")],
         formats=["코인 시황", "포지션 공유", "차트·수급"],
         pattern=r"비트코인|\bbtc\b|이더리움|\beth\b|알트|도미넌스|김프|솔라나|\bxrp\b|청산"),
    dict(id="stock", room="주식토큰방", icon="📈", access="회원도 올림", role="미국·한국 주식을 USDT 토큰으로 매매하는 사람의 방",
         items=[("오늘 볼 토큰 3개 (왜 움직이는지 + 위험)", "이 방은 SKHYNIXUSDT처럼 토큰 티커로 대화해요. 국내장 요약보다 토큰으로 바로 이어지는 글이 맞아요."),
                ("미장 실적·공시와 토큰 연결", "토큰을 움직이는 재료가 바로 실적과 공시예요."),
                ("장 마감 뒤 오늘 움직인 토큰 정리", "주식 시장이 닫힌 뒤에도 토큰은 거래되니 이 방만의 차별점이 돼요.")],
         formats=["미장 종목·실적", "주식토큰", "포지션 공유"],
         pattern=r"실적|가이던스|엔비디아|테슬라|마이크론|하이닉스|삼성전자|반도체|공시|[a-z]{2,}usdt|토큰화"),
    dict(id="trader", room="트레이더 관점 공유방", icon="🎯", access="운영진만 올림", role="트레이더 글이 나오는 곳 — 연구소는 재료를 대요",
         items=[("상승·하락 시나리오 초안", "트레이더가 처음부터 쓰지 않고 고쳐 쓰면 매일 글이 끊기지 않아요."),
                ("수급·포지션 소재 (다른 방에서 크는 분석)", "'라이브 안 봤으면 청산'이란 말이 나올 만큼 회원은 트레이더 분석에 크게 반응해요."),
                ("라이브에서 다룰 질문 모음", "라이브와 이 방이 이어지면 다시 보기와 참여가 함께 늘어요.")],
         formats=["차트·수급", "코인 시황", "시황 정리"],
         pattern=r"시나리오|지지|저항|수급|매물대|추세|옵션|눌림|미결제|포지션"),
    dict(id="talk", room="소통방", icon="💬", access="회원 대화 중심", role="회원 글이 거의 다 모이는 곳",
         items=[("오전 오늘의 질문 (답장 유도)", "회원 글 대부분이 여기 있어서 여기서 답장을 끌어내면 활동왕 점수와 바로 이어져요."),
                ("저녁 토론거리 (오늘 다른 방에서 가장 큰 화제)", "활동 인원이 줄고 있어서 말 걸 이유를 매일 줘야 해요."),
                ("초보도 답할 수 있는 쉬운 질문", "늘 말하던 사람만 말하는 걸 막아요."),
                ("정보왕 안내: 퍼온 정보는 출처와 한 줄 의견 붙이기", "정보왕은 퍼오기도 인정돼요. 반응과 답글이 붙는 글이 점수가 높아서 양질의 글이 앞서요.")],
         formats=["질문·참여", "속보·뉴스", "코인 시황"], pattern=r"."),
    dict(id="proof", room="수익 인증방", icon="🏆", access="회원도 올림", role="수익왕이 갈리는 곳 — 꾸준히 인증한 날로 뽑는 방",
         items=[("오늘의 수익 인증 미션과 양식", "수익왕은 한 달 동안 꾸준히 인증한 사람이라, 매일 올릴 이유와 양식이 있으면 인증한 날이 쌓여요."),
                ("인증에 붙이는 복기 한 줄 예시 (이름 없이)", "사진만 있으면 다른 회원이 배울 게 없어요. 근거 한 줄을 붙이면 수익 자랑방이 아니라 배우는 방이 돼요."),
                ("이번 달 인증한 사람 수 알리기", "다른 사람도 쓴다는 걸 보여 주면 따라 쓰게 돼요.")],
         formats=["수익 인증·익절", "복기·원칙·멘탈"], pattern=r"익절|복기|원칙|손절|멘탈|수익 ?실현|매매일지"),
    dict(id="news", room="중요 뉴스 및 중요 한마디", icon="📰", access="운영진만 올림", role="이것만 봐도 오늘 시장을 아는 곳",
         items=[("아침: 밤사이 핵심 뉴스 3~5줄 + 왜 중요한지", "속보는 어디에나 있어요. '그래서 뭐가 중요한지'가 이 방의 값어치예요."),
                ("오늘 시간대별 일정", "지금도 이 방에 일정 글을 올리고 있고, 매일 볼 이유가 돼요."),
                ("저녁: 오늘 밤 미장·코인 관전 포인트", "회원이 밤에도 매매하니 그 전에 필요해요.")],
         formats=["속보·뉴스", "일정·체크리스트", "시황 정리"], pattern=r"속보|breaking|연준|fomc|cpi|관세|트럼프|금리|발표|일정"),
    dict(id="study", room="기초가이드 & 공부방", icon="🎓", access="운영진·회원", role="회원이 매일 하나씩 공부하는 곳, 실제로 물어본 것을 쌓는 곳",
         items=[("매일 '오늘 꼭 공부해볼 것' 하나", "날마다 개념 하나와 직접 해볼 것을 올려 공부 습관을 만들어요."),
                ("회원이 자주 묻는 비중·평단·추매·손절 답변", "회원 글에서 자주 나오는 고민이에요."),
                ("오늘 뉴스에 나온 용어 하나", "뉴스방 글을 이해하는 데 바로 쓸 수 있어요."),
                ("차트 개념을 오늘 실제 차트로 설명", "'적삼병이 나오나요' 같은 질문이 있어요. 사례 없는 개념 글보다 오늘 차트로 보여 주는 게 와닿아요.")],
         formats=["개념 설명", "차트·수급", "복기·원칙·멘탈"], pattern=r"이란\?|뜻은|쉽게|개념|용어|원리|초보|공부|설명"),
]


def fmt_of(text):
    return [k for k, p in FORMATS.items() if re.search(p, text or "", re.I)]


def _channel_posts(conn, chats, days):
    """다른 방 '채널' 글만 — {chat, id, date, text, x}. x 는 그 채널 평소(중앙값) 대비 배수."""
    by_id = {c["id"]: c for c in chats if "내" not in c["분석"] and c["종류"] == "채널"}
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = [r for r in conn.execute("SELECT chat_id, id, date, text, reactions, forwards FROM msgs WHERE date >= ? AND length(text) >= 40", (since,))
            if r[0] in by_id and not ADS.search(r[3])]
    base = defaultdict(list)
    for r in rows:
        base[r[0]].append((r[4] or 0) + 2 * (r[5] or 0))
    med = {k: max(MIN_BASE, statistics.median(v)) for k, v in base.items()}
    return [{"chat": by_id[r[0]], "id": r[1], "date": r[2], "text": r[3],
             "x": min(CAP_X, ((r[4] or 0) + 2 * (r[5] or 0)) / med[r[0]])} for r in rows]


def _research(f, posts, own):
    lines, stats = [], []
    for k in f["formats"]:
        hit = [p["x"] for p in posts if k in p["fmts"]]
        if hit:
            stats.append((k, sum(hit) / len(hit), sum(x >= 3 for x in hit) * 100 / len(hit), len(hit)))
    for k, avg, big, n in sorted(stats, key=lambda s: -s[1]):
        lines.append(f"다른 채널 {RESEARCH_DAYS}일: {k} {n:,}개 — 평소의 {avg:.1f}배, 3배 넘게 터진 글 {big:.0f}%")
    per = defaultdict(list)
    for p in posts:
        if set(f["formats"]) & set(p["fmts"]):
            per[p["chat"]["이름"]].append(p["x"])
    top = sorted(((sum(x >= 3 for x in v) * 100 / len(v), k) for k, v in per.items() if len(v) >= 10), reverse=True)[:3]
    if top:
        lines.append("이 소재를 잘 쓰는 곳: " + ", ".join(f"{k}({r:.0f}%)" for r, k in top))
    o = own.get(f["room"])
    if o:
        best = sorted(((v["react"] / v["n"], k) for k, v in o["formats"].items() if v["n"] >= 3), reverse=True)[:1]
        lines.append(f"우리 방 {RESEARCH_DAYS}일: 운영진 글 {o['admin']:,}개, 회원 글 {o['member']:,}개, 글당 반응 {o['react_avg']}"
                     + (f" · 반응이 가장 큰 형식 {best[0][1]}(글당 {best[0][0]:.1f}개)" if best else ""))
    return lines


def build(conn, chats):
    """폴더별 넣을 것·이유 + 연구 근거 + 최근 48시간 소재."""
    own = json.loads(OWN.read_text(encoding="utf-8")) if OWN.exists() else {}
    posts = _channel_posts(conn, chats, RESEARCH_DAYS)
    for p in posts:
        p["fmts"] = fmt_of(p["text"])
    recent = (datetime.now(timezone.utc) - timedelta(hours=SOURCE_HOURS)).isoformat()
    fresh = sorted((p for p in posts if p["date"] >= recent), key=lambda p: -p["x"])
    used, out = set(), []
    for f in sorted(FOLDERS, key=lambda f: f["pattern"] == "."):   # 소통방은 남은 화제에서 고름
        src, per = [], Counter()
        if f["pattern"]:
            for p in fresh:
                key = (p["chat"]["id"], p["id"])
                if p["x"] < MIN_X or key in used or per[p["chat"]["이름"]] >= 2 or not re.search(f["pattern"], p["text"], re.I) or not MARKET.search(p["text"]):
                    continue
                if f["id"] in ("proof", "study") and p["chat"]["이름"] in FEEDS:
                    continue
                used.add(key)
                per[p["chat"]["이름"]] += 1
                src.append({"chat": p["chat"]["이름"], "x": round(p["x"], 1), "text": p["text"][:400], "link": link_of(p["chat"], p["id"]),
                            "time": datetime.fromisoformat(p["date"]).astimezone(KST).strftime("%m/%d %H:%M")})
                if len(src) == 6:
                    break
        out.append({"id": f["id"], "room": f["room"], "icon": f["icon"], "access": f["access"], "role": f["role"],
                    "items": [{"what": w, "why": y} for w, y in f["items"]], "research": _research(f, posts, own), "sources": src})
    order = {f["id"]: i for i, f in enumerate(FOLDERS)}
    out.sort(key=lambda f: order[f["id"]])
    last = conn.execute("SELECT MAX(date) FROM msgs").fetchone()[0]
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    return {"updated_at": datetime.now(KST).isoformat(timespec="seconds"),
            "crawl": {"chats": len(chats), "last_at": datetime.fromisoformat(last).astimezone(KST).isoformat(timespec="minutes") if last else "",
                      "day": conn.execute("SELECT COUNT(*) FROM msgs WHERE date >= ?", (since,)).fetchone()[0],
                      "total": conn.execute("SELECT COUNT(*) FROM msgs").fetchone()[0], "research_posts": len(posts)},
            "folders": out}


async def refresh_own(client):
    """우리 방 30일 성적을 방·형식별 숫자로만 저장 — 어떤 글이 먹히는지 매일 다시 배운다."""
    from telethon.tl.functions.messages import GetForumTopicsRequest
    from telethon.tl.types import ChannelParticipantsAdmins
    from tg_traders import CHAT_ID, topic_of
    chat = await client.get_entity(CHAT_ID)
    res = await client(GetForumTopicsRequest(peer=chat, offset_date=None, offset_id=0, offset_topic=0, limit=100))
    topics = {t.id: t.title for t in res.topics}
    admins = {u.id async for u in client.iter_participants(chat, filter=ChannelParticipantsAdmins)}
    since = datetime.now(timezone.utc) - timedelta(days=RESEARCH_DAYS)
    R = defaultdict(lambda: {"admin": 0, "member": 0, "react": 0, "formats": defaultdict(lambda: {"n": 0, "react": 0})})
    async for m in client.iter_messages(chat):
        if m.date < since:
            break
        if m.action or not m.sender_id or m.id in topics:
            continue
        r = R[topics.get(topic_of(m), "")]
        react = sum(x.count for x in m.reactions.results) if m.reactions else 0
        r["react"] += react
        if m.sender_id in admins:
            r["admin"] += 1
            for k in fmt_of(m.message):
                r["formats"][k]["n"] += 1
                r["formats"][k]["react"] += react
        else:
            r["member"] += 1
    out = {k: {"admin": v["admin"], "member": v["member"], "react_avg": round(v["react"] / max(1, v["admin"] + v["member"]), 2),
               "formats": {a: dict(b) for a, b in v["formats"].items()}} for k, v in R.items() if k}
    OWN.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def main():
    import csv
    import sqlite3
    from tg_login import CHATS
    with open(CHATS, encoding="utf-8-sig", newline="") as f:
        chats = [r for r in csv.DictReader(f) if (r["분석"] or "").strip()]
    conn = sqlite3.connect(f"file:{DATA_DIR / 'telegram_history.db'}?mode=ro", uri=True)
    OUT.write_text(json.dumps(build(conn, chats), ensure_ascii=False, indent=1), encoding="utf-8")
    print("✅", OUT)


if __name__ == "__main__":
    main()
