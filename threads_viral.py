"""조회수 10만 이상 경제 쓰레드 모으기 — '터지는 글 공식'을 찾으려는 대량 수집 (가끔 손으로 한 번씩).

    python threads_viral.py              # 대량 수집 + 모음 만들기 (APIFY_TOKEN 필요, 약 15달러 상한)
    python threads_viral.py --export     # 수집 없이 DB에서 10만+ 모음만 다시 만들기 (매일 실행에서 씀)
    python threads_viral.py --dry-run    # 무엇을 수집할지만 출력

수집: 한국어 경제 키워드 60개 × 인기 글 100개, 최근 3개월. 키워드 10개씩 6번 나눠 동시에 돌리고,
  한 번에 MAX_USD_PER_RUN 달러를 넘으면 Apify 가 멈춘다 (비용 상한).
저장: data/insta.db 의 threads_apify (source='대량:키워드') — 매일 수집과 같은 표라 조회수가 계속 갱신된다.
결과: output/site/thx_viral.json (조회수 10만+ 한국어 경제 글), thx_viral_meta.json (공통점 숫자).
"""
import argparse
import json
import os
import re
import statistics
import sys
import time
import urllib.request
from datetime import datetime, timezone

from apify_threads import ACTOR, PRICE_PER_1K, migrate, save
from common import OUTPUT_DIR, connect, load_env
from topics import topics_of

KEYWORDS = ["주식", "미국주식", "국내주식", "코스피", "코스닥", "나스닥", "S&P500", "삼성전자", "SK하이닉스", "엔비디아",
            "테슬라", "애플", "반도체", "AI주식", "ETF", "배당", "배당주", "적금", "예금", "금리",
            "기준금리", "환율", "달러", "엔화", "코인", "비트코인", "이더리움", "부동산", "아파트", "청약",
            "전세", "월세", "대출", "주담대", "재테크", "월급", "연봉", "부업", "N잡", "절약",
            "가계부", "짠테크", "연금", "ISA", "IRP", "연말정산", "세금", "경제", "경기침체", "물가",
            "금값", "투자", "주린이", "손절", "익절", "상한가", "공모주", "자산", "부자", "파이어족"]
PER_KEYWORD = 100
PERIOD = "3 months"
PER_RUN = 10
MAX_USD_PER_RUN = 2.6
VIRAL = 100_000
SITE = OUTPUT_DIR / "site"


def start(token, kws):
    body = {"mode": "search", "keywords": kws, "search_filter": "top", "start_date": PERIOD, "max_posts": PER_KEYWORD}
    req = urllib.request.Request(f"https://api.apify.com/v2/acts/{ACTOR}/runs?token={token}&maxTotalChargeUsd={MAX_USD_PER_RUN}",
                                 data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["data"]


def get(token, path):
    with urllib.request.urlopen(f"https://api.apify.com/v2/{path}{'&' if '?' in path else '?'}token={token}", timeout=120) as r:
        return json.load(r)


def collect(token, conn):
    runs = {}
    for i in range(0, len(KEYWORDS), PER_RUN):
        kws = KEYWORDS[i:i + PER_RUN]
        try:
            runs[start(token, kws)["id"]] = kws
            print(f"▶ 시작: {', '.join(kws)}")
        except Exception as e:
            print(f"⚠️ 시작 실패 ({kws[0]}~): {e}")
    now, total = datetime.now(timezone.utc).isoformat(timespec="seconds"), 0
    while runs:
        time.sleep(30)
        for rid, kws in list(runs.items()):
            run = get(token, f"actor-runs/{rid}")["data"]
            if run["status"] in ("READY", "RUNNING"):
                continue
            items = get(token, f"datasets/{run['defaultDatasetId']}/items?clean=true&format=json")
            items = [p for p in items if p.get("post_code") or p.get("post_url")]
            # 키워드별 출처를 붙이려고 본문에 키워드가 있는 첫 키워드를 쓴다 (없으면 묶음 첫 키워드)
            for kw in kws:
                mine = [p for p in items if kw.lower() in (p.get("text_content") or p.get("text") or "").lower()]
                total += save(conn, mine, f"대량:{kw}", now)
                items = [p for p in items if p not in mine]
            total += save(conn, items, f"대량:{kws[0]}", now)
            conn.commit()
            print(f"✅ {run['status']}: {kws[0]}~{kws[-1]} → 지금까지 {total}개")
            del runs[rid]
    conn.execute("INSERT INTO threads_cost VALUES (?, ?) ON CONFLICT(date) DO UPDATE SET results = results + excluded.results",
                 (datetime.now(timezone.utc).date().isoformat(), total))
    conn.commit()
    print(f"완료: {total}개 저장 (예상 비용 약 ${total * PRICE_PER_1K / 1000:.2f})")


def korean(text):
    return len(re.findall(r"[가-힣]", text)) >= max(10, len(text) * 0.3)


def first_line(text):
    return next((ln.strip() for ln in text.splitlines() if ln.strip()), "")


def export(conn):
    rows = conn.execute("SELECT url, username, display_name, followers, text, posted_at, views, likes, replies, reposts, "
                        "quotes, shares, has_media, media_type, source FROM threads_apify WHERE views >= ? "
                        "AND COALESCE(is_reply, 0) = 0 ORDER BY views DESC", (VIRAL,)).fetchall()
    out = []
    for (url, user, name, fol, text, posted, views, likes, replies, reposts, quotes, shares, media, mtype, src) in rows:
        text = text or ""
        if not korean(text):
            continue
        tps = [t for t in topics_of(text) if t != "기타"]
        if not tps:
            continue          # 경제 주제로 안 잡히는 글(일상·연애 등)은 뺀다
        fl = first_line(text)
        out.append({"url": url, "username": user, "name": name, "followers": fol, "views": views, "likes": likes,
                    "replies": replies, "reposts": reposts, "quotes": quotes, "shares": shares,
                    "spread": round(views / max(fol or 0, 300), 1), "rate": round((likes + 2 * (replies or 0) + 3 * (reposts or 0)) / views * 100, 2),
                    "time": (posted or "")[:10], "topics": ", ".join(tps), "text": text[:600], "first": fl,
                    "len": len(text), "lines": len([l for l in text.splitlines() if l.strip()]), "media": bool(media),
                    "question": "?" in fl, "number": bool(re.search(r"\d", fl)), "source": src})
    (SITE / "thx_viral.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    meta = []
    if out:
        pct = lambda k: round(sum(1 for p in out if p[k]) / len(out) * 100)
        top = {}
        for p in out:
            for t in p["topics"].split(", "):
                top[t] = top.get(t, 0) + 1
        meta = [{"n": len(out), "median_views": int(statistics.median(p["views"] for p in out)),
                 "median_len": int(statistics.median(p["len"] for p in out)), "median_first": int(statistics.median(len(p["first"]) for p in out)),
                 "median_lines": int(statistics.median(p["lines"] for p in out)), "median_followers": int(statistics.median(p["followers"] or 0 for p in out)),
                 "small_acc": round(sum(1 for p in out if (p["followers"] or 0) < 5000) / len(out) * 100),
                 "media": pct("media"), "question": pct("question"), "number": pct("number"),
                 "topics": sorted(top.items(), key=lambda x: -x[1])[:8], "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")}]
    (SITE / "thx_viral_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ 조회수 {VIRAL:,}+ 한국어 경제 글 {len(out)}개 → output/site/thx_viral.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    load_env()
    conn = connect()
    migrate(conn)
    if a.dry_run:
        print(f"키워드 {len(KEYWORDS)}개 × {PER_KEYWORD}개, {PERIOD}, {PER_RUN}개씩 묶어 {-(-len(KEYWORDS) // PER_RUN)}번 "
              f"(한 번 상한 ${MAX_USD_PER_RUN}, 최대 약 ${len(KEYWORDS) * PER_KEYWORD * PRICE_PER_1K / 1000:.0f})")
        return
    if not a.export:
        token = os.environ.get("APIFY_TOKEN")
        if not token:
            print("APIFY_TOKEN 이 없어요 — 깃허브 Actions 의 threads-viral 로 실행하세요.")
            return 1
        collect(token, conn)
    export(conn)


if __name__ == "__main__":
    sys.exit(main())
