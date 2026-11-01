"""텔레그램 '차트리포트' 글에 붙일 차트 분석 이미지 + 본문을 만든다.

    python chart_report.py IONQ 비트코인 SK하이닉스   # 종목마다 PC(가로)·모바일(세로) PNG + 본문
    python chart_report.py 아이온큐 --send             # 봇으로도 보냄 (TELEGRAM_BOT_TOKEN·CHAT_ID)
    python chart_report.py --from-tg                 # 오늘 문구의 다음 차트 글 종목 하나로 만들고 봇으로 보냄 (PC가 하루 2번 08·19시)
    python chart_report.py --from-tg --force         # 이미 만든 칸이어도 다시 (사이트 '차트 만들기' 빈칸 요청)
    python chart_report.py IONQ --no-ai              # Claude 없이 정해진 문장으로 본문
시세(무료 공개): 미국 주식 야후 파이낸스 차트 주소(yfinance 가 쓰는 곳), 국내 네이버 금융, 코인 바이낸스(안 되면 업비트).
그림: TradingView Lightweight Charts(Apache 2.0, assets/vendor)로 그린 화면을 PC Chrome(헤드리스)로 캡처.
결과: output/charts/<종목>_pc.png·_m.png (봇용 원본, 저장소에 안 올림)
      output/site/charts/<종목>_pc.jpg·_m.jpg + output/site/chart_reports.json (사이트 텔레그램 '오늘 올릴 문구'에 붙음)
본문 숫자는 계산한 값만 쓴다. Claude 가 쓴 본문에 계산에 없는 숫자나 반전 문구가 있으면 정해진 문장으로 바꾼다.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from common import OUTPUT_DIR, ROOT, load_env

MODEL = "claude-opus-5-5"
KST = timezone(timedelta(hours=9))
SITE = OUTPUT_DIR / "site"
RAW = OUTPUT_DIR / "charts"            # 봇으로 보낼 원본 PNG (커밋 안 함)
WEB = SITE / "charts"                  # 사이트용 JPG (커밋)
REPORTS = SITE / "chart_reports.json"
TEMPLATE = ROOT / "assets" / "chart_report.html"
LWC = ROOT / "assets" / "vendor" / "lightweight-charts.standalone.production.js"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"}
COINS = {"비트코인": "BTC", "비트": "BTC", "btc": "BTC", "이더리움": "ETH", "이더": "ETH", "eth": "ETH", "리플": "XRP", "xrp": "XRP",
         "솔라나": "SOL", "sol": "SOL", "도지코인": "DOGE", "도지": "DOGE", "doge": "DOGE"}
COIN_NAMES = {"BTC": "비트코인", "ETH": "이더리움", "XRP": "리플", "SOL": "솔라나", "DOGE": "도지코인"}
FIB = [(0, "#9aa3b5"), (0.236, "#ef5350"), (0.382, "#ffa726"), (0.5, "#66bb6a"), (0.618, "#26a69a"), (0.786, "#4fc3f7"), (1, "#5c6bc0")]
MA = [(20, "#4f8cff"), (50, "#7fd3ff"), (200, "#ffa726")]


# ── 종목 찾기·시세 ──
def resolve(q):
    key = q.strip()
    if key.lower() in COINS:
        s = COINS[key.lower()]
        return {"kind": "coin", "symbol": s, "name": COIN_NAMES[s], "exchange": "BINANCE"}
    if re.fullmatch(r"\d{6}", key):
        items = naver_ac(key)
        return {"kind": "kr", "symbol": key, "name": items[0]["name"] if items else key, "exchange": items[0]["typeName"] if items else "KRX"}
    if re.fullmatch(r"[A-Za-z][A-Za-z.\-]{0,6}", key):
        return {"kind": "us", "symbol": key.upper(), "name": key.upper(), "exchange": ""}
    items = naver_ac(key)
    if not items:
        raise SystemExit(f"'{q}' 종목을 찾지 못했어요 — 티커(IONQ)나 6자리 코드(000660)로 넣어 주세요.")
    it = items[0]
    if it.get("nationCode") == "KOR":
        return {"kind": "kr", "symbol": it["code"], "name": it["name"], "exchange": it.get("typeName") or "KRX"}
    return {"kind": "us", "symbol": it["code"], "name": it["name"], "exchange": it.get("typeCode") or ""}


def naver_ac(q):
    r = requests.get("https://ac.stock.naver.com/ac", params={"q": q, "target": "stock"}, headers=UA, timeout=20)
    return r.json().get("items", [])


def fetch(a):
    """일봉 [{time:'YYYY-MM-DD', open, high, low, close}] — 오래된 것부터."""
    if a["kind"] == "us":
        r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{a['symbol']}", params={"range": "3y", "interval": "1d"},
                         headers=UA, timeout=30).json()["chart"]["result"][0]
        meta, q = r["meta"], r["indicators"]["quote"][0]
        a["exchange"] = a["exchange"] or meta.get("fullExchangeName", "")
        off = meta.get("gmtoffset", 0)
        rows = [{"time": datetime.fromtimestamp(t + off, timezone.utc).strftime("%Y-%m-%d"), "open": o, "high": h, "low": l, "close": c}
                for t, o, h, l, c in zip(r["timestamp"], q["open"], q["high"], q["low"], q["close"]) if None not in (o, h, l, c)]
        a["unit"], a["src"] = "달러", "야후 파이낸스"
    elif a["kind"] == "kr":
        start = (datetime.now(KST) - timedelta(days=1100)).strftime("%Y%m%d")
        t = requests.get("https://api.finance.naver.com/siseJson.naver", headers=UA, timeout=30,
                         params={"symbol": a["symbol"], "requestType": 1, "startTime": start,
                                 "endTime": datetime.now(KST).strftime("%Y%m%d"), "timeframe": "day"}).text
        rows = [{"time": f"{d[:4]}-{d[4:6]}-{d[6:]}", "open": float(o), "high": float(h), "low": float(l), "close": float(c)}
                for d, o, h, l, c in re.findall(r'\["(\d{8})",\s*([\d.]+),\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)', t)]
        rows = [r for r in rows if r["open"] > 0]   # 거래정지일
        a["unit"], a["src"] = "원", "네이버 금융"
    else:
        try:
            k = requests.get("https://api.binance.com/api/v3/klines", params={"symbol": a["symbol"] + "USDT", "interval": "1d", "limit": 1000},
                             timeout=30)
            k.raise_for_status()
            rows = [{"time": datetime.fromtimestamp(x[0] / 1000, timezone.utc).strftime("%Y-%m-%d"), "open": float(x[1]),
                     "high": float(x[2]), "low": float(x[3]), "close": float(x[4])} for x in k.json()]
            a["unit"], a["src"], a["exchange"] = "달러", "바이낸스 USDT", "BINANCE"
        except requests.RequestException:
            rows, to = [], None
            for _ in range(4):   # 업비트는 한 번에 200일
                p = {"market": "KRW-" + a["symbol"], "count": 200, **({"to": to} if to else {})}
                xs = requests.get("https://api.upbit.com/v1/candles/days", params=p, headers=UA, timeout=30).json()
                if not xs:
                    break
                rows += [{"time": x["candle_date_time_kst"][:10], "open": x["opening_price"], "high": x["high_price"],
                          "low": x["low_price"], "close": x["trade_price"]} for x in xs]
                to = xs[-1]["candle_date_time_utc"].replace("T", " ")
            rows.sort(key=lambda r: r["time"])
            a["unit"], a["src"], a["exchange"] = "원", "업비트 KRW", "UPBIT"
    if len(rows) < 60:
        raise SystemExit(f"{a['name']} 시세가 너무 적어요({len(rows)}일).")
    return rows


# ── 계산 ──
def sma(xs, n):
    out, s = [], 0.0
    for i, x in enumerate(xs):
        s += x
        if i >= n:
            s -= xs[i - n]
        out.append(s / n if i >= n - 1 else None)
    return out


def pivots(rows, k, key, lo, hi):
    """rows[lo:hi] 안에서 앞뒤 k일 중 가장 높/낮은 날 (인덱스)."""
    out = []
    for i in range(max(lo, k), min(hi, len(rows) - k)):
        win = [r[key] for r in rows[i - k:i + k + 1]]
        if rows[i][key] == (max(win) if key == "high" else min(win)):
            out.append(i)
    return out


def fmt_price(p, a):
    if a["unit"] == "원":   # 호가 단위보다 잘게는 안 씀 (실제 가격은 그대로)
        step = 100 if p >= 100_000 else 10 if p >= 10_000 else 1
        return f"{round(p / step) * step:,}"
    return f"{p:,.0f}" if p >= 1000 else f"{p:,.2f}" if p >= 1 else f"{p:.4f}"


def analyze(rows, a, show):
    """화면에 보일 마지막 show 일 기준으로 고점·저점·피보나치·이평선·지지선·추세선을 계산한다."""
    n = len(rows)
    closes = [r["close"] for r in rows]
    mas = {p: sma(closes, p) for p, _ in MA}
    v0 = max(0, n - show)
    view = range(v0, n)
    P = lambda p: fmt_price(p, a)
    U = a["unit"]
    md = lambda i: rows[i]["time"][5:].replace("-", "/")
    last, prev = rows[-1], rows[-2]
    chg = (last["close"] / prev["close"] - 1) * 100
    hi_i = max(view, key=lambda i: rows[i]["high"])
    lo_i = min(view, key=lambda i: rows[i]["low"])
    hi, lo = rows[hi_i]["high"], rows[lo_i]["low"]
    close = last["close"]
    fib = [{"r": r, "price": hi - r * (hi - lo), "color": c} for r, c in FIB]
    for f in fib:
        f["name"] = "0" if f["r"] == 0 else "1.0" if f["r"] == 1 else f"{f['r']:g}"
        f["label"] = f"{f['name']} ({P(f['price'])})"
    above = [f for f in fib if f["price"] > close * 1.003]
    below = [f for f in fib if f["price"] < close * 0.997]
    near = [f for f in fib if abs(f["price"] / close - 1) <= 0.003]
    zone_short = (f"피보 {near[0]['name']} 부근" if near else
                  f"피보 {above[-1]['name']}~{below[0]['name']} 사이" if above and below else
                  "기간 고점 위" if not above else "기간 저점 아래")
    zone = (f"{near[0]['label']} 부근" if near else
            f"{below[0]['label']} ~ {above[-1]['label']} 사이" if above and below else
            "기간 고점 위" if not above else "기간 저점 아래")
    # 이동평균선
    ma_now = {p: mas[p][-1] for p, _ in MA}
    ma_txt = {}
    for p, v in ma_now.items():
        if v is None:
            ma_txt[p] = None
            continue
        gap = close - v
        ma_txt[p] = {"price": v, "label": P(v), "gap": gap, "gap_pct": gap / v * 100,
                     "pos": "위" if gap > 0 else "아래"}
    m20, m50, m200 = (ma_now[p] for p, _ in MA)
    if m200 and m20 > m50 > m200:
        order = "정배열"
    elif m200 and m20 < m50 < m200:
        order = "역배열"
    else:
        order = "섞여 있음"
    cross = None
    if m200:
        sign = lambda i: (mas[50][i] or 0) > (mas[200][i] or 0)
        for i in range(n - 1, max(n - 400, 200), -1):
            if mas[200][i - 1] is not None and sign(i) != sign(i - 1):
                cross = {"kind": "골든크로스" if sign(i) else "데드크로스", "date": md(i)}
                break
    if close < m20 and m20 < m50:
        trend, tcolor = "하락추세", "#ef5350"
    elif close > m20 and m20 > m50:
        trend, tcolor = "상승추세", "#26a69a"
    else:
        trend, tcolor = "방향 탐색", "#ffa726"
    # 반등 고점 / 조정 저점 (고점·저점 이후 되돌림)
    swing = None
    if lo_i > hi_i and lo_i < n - 6:
        j = max(range(lo_i + 1, n), key=lambda i: rows[i]["high"])
        if j < n - 10 and rows[j]["high"] < hi * 0.97 and close < rows[j]["high"] * 0.95:
            swing = {"kind": "반등 고점", "i": j, "price": rows[j]["high"], "date": md(j)}
    elif hi_i > lo_i and hi_i < n - 6:
        j = min(range(hi_i + 1, n), key=lambda i: rows[i]["low"])
        if j < n - 10 and rows[j]["low"] > lo * 1.03 and close > rows[j]["low"] * 1.05:
            swing = {"kind": "조정 저점", "i": j, "price": rows[j]["low"], "date": md(j)}
    # 수평 지지·저항: 최근 120일 저점·고점이 2번 이상 모인 가격대
    def cluster(idx, key, side):
        pts = sorted(rows[i][key] for i in idx)
        best = None
        for p in pts:
            grp = [q for q in pts if abs(q / p - 1) <= 0.025]
            lvl = sum(grp) / len(grp)
            ok = lvl < close * 0.995 if side == "sup" else lvl > close * 1.005
            if len(grp) >= 2 and ok:
                score = (len(grp), -abs(lvl / close - 1))
                if not best or score > best[0]:
                    best = (score, lvl, len(grp))
        return {"price": best[1], "label": P(best[1]), "touch": best[2]} if best else None
    recent = max(v0, n - 120)
    hsup = cluster(pivots(rows, 4, "low", recent, n), "low", "sup")
    hres = cluster(pivots(rows, 4, "high", recent, n), "high", "res")
    # 추세선: 하락이면 최근 큰 고점 두 개, 상승이면 저점 두 개를 잇는다 (최근 70일 단기 추세선 먼저, 없으면 150일)
    def trendline(span, gap):
        start = max(v0, n - span)
        down = trend != "상승추세"
        key = "high" if down else "low"
        pts = pivots(rows, 5 if span > 100 else 3, key, start, n - 2)
        if not pts:
            return None
        # 시작점: 그 뒤로 한 번도 넘지(깨지) 않은 고점(저점) 중 가장 최근 것부터
        top = [i for i in pts if rows[i][key] == (max if down else min)(r[key] for r in rows[i:])]
        for p1 in sorted(top, reverse=True):
            ok = (lambda v: v < rows[p1][key] * 0.96) if down else (lambda v: v > rows[p1][key] * 1.04)
            for p2 in sorted((i for i in pts if i >= p1 + gap and ok(rows[i][key])), reverse=True):
                slope = (rows[p2][key] - rows[p1][key]) / (p2 - p1)
                line = lambda i: rows[p1][key] + slope * (i - p1)
                if all((rows[i]["close"] <= line(i) + 1e-9) if down else (rows[i]["close"] >= line(i) - 1e-9) for i in range(p1, n)):   # 지금까지 안 깨진 선만
                    return {"kind": "하락" if down else "상승", "i1": p1, "i2": p2, "p1": rows[p1][key], "p2": rows[p2][key], "slope": slope}
        return None
    tline = trendline(70, 5) or trendline(150, 15)
    if tline:
        tline["now"] = tline["p1"] + tline["slope"] * (n - 1 - tline["i1"])
        tline["label"] = f"{md(tline['i1'])} {P(tline['p1'])} → {md(tline['i2'])} {P(tline['p2'])}"
        if tline["now"] <= 0:
            tline = None
    # 심리적 지지: 종가 바로 아래 딱 떨어지는 가격(30달러·75,000·1,300,000)에 최근 60일 저점이 2% 안으로 닿았으면
    rsup = None
    digits = len(str(int(close))) if close >= 1 else 0
    if digits:
        lead = int(str(int(close))[0])
        step = 10 ** (digits - 1) if lead < 3 else 5 * 10 ** (digits - 2) if digits >= 2 else 1
        r = (close // step) * step
        if r >= close * 0.9 and r < close:
            near_lows = [i for i in range(max(v0, n - 60), n) if abs(rows[i]["low"] / r - 1) <= 0.02]
            if near_lows:
                j = min(near_lows, key=lambda i: abs(rows[i]["low"] - r))
                rsup = {"price": r, "label": f"{int(r):,}", "date": md(j), "low": P(rows[j]["low"]), "touch": len(near_lows)}
                if hsup and abs(hsup["price"] / r - 1) <= 0.02:   # 같은 자리면 딱 떨어지는 가격 하나로
                    hsup = None
    # 1년(코인 365일, 주식 252일) 고저
    yr = rows[-(365 if a["kind"] == "coin" else 252):]
    y_hi, y_lo = max(r["high"] for r in yr), min(r["low"] for r in yr)
    return {"rows": rows, "mas": mas, "v0": v0, "n": n, "P": P, "U": U, "md": md,
            "date": last["time"], "close": close, "chg": chg, "open": last["open"], "high": last["high"], "low": last["low"],
            "hi": {"i": hi_i, "price": hi, "date": md(hi_i), "label": P(hi)}, "lo": {"i": lo_i, "price": lo, "date": md(lo_i), "label": P(lo)},
            "drop": (lo / hi - 1) * 100, "rise": (hi / lo - 1) * 100, "fib": fib, "zone": zone, "zone_short": zone_short, "sup": below[:2], "res": above[-2:][::-1] if above else [],
            "ma": ma_txt, "order": order, "cross": cross, "trend": trend, "tcolor": tcolor, "swing": swing,
            "hsup": hsup, "hres": hres, "rsup": rsup, "tline": tline, "y_hi": y_hi, "y_lo": y_lo}


def facts_of(f, a):
    """본문용 사실 목록 — 단위까지 붙인 글자로 (Claude 는 이 숫자만 쓴다)."""
    P, U = f["P"], f["U"]
    ma = {f"{p}일선": (f"{f['ma'][p]['label']}{U} (종가가 {f['ma'][p]['pos']}, 차이 {f['ma'][p]['gap_pct']:+.1f}%)" if f["ma"][p] else "데이터 부족")
          for p, _ in MA}
    return {
        "종목": a["name"], "기준일": f["date"], "현재가(마지막 일봉 종가)": f"{P(f['close'])}{U}", "하루 등락": f"{f['chg']:+.2f}%",
        "차트 구간 고점": f"{f['hi']['label']}{U} ({f['hi']['date']})", "차트 구간 저점": f"{f['lo']['label']}{U} ({f['lo']['date']})",
        **({"고점→저점 낙폭": f"{f['drop']:.0f}%"} if f["lo"]["i"] > f["hi"]["i"] else {"저점→고점 상승폭": f"+{f['rise']:.0f}%"}),
        "피보나치(고점 0 → 저점 1.0)": [x["label"] for x in f["fib"]], "지금 위치": f["zone"],
        "아래 피보 지지": [x["label"] for x in f["sup"]], "위 피보 저항": [x["label"] for x in f["res"]],
        "이동평균선": ma, "이평 배열": f["order"], "최근 50·200일선 교차": f"{f['cross']['kind']} ({f['cross']['date']})" if f["cross"] else "없음",
        "추세 판단(종가·20일선·50일선 위치)": f["trend"],
        "되돌림": f"{f['swing']['kind']} {P(f['swing']['price'])}{U} ({f['swing']['date']})" if f["swing"] else "없음",
        "수평 지지": f"{f['hsup']['label']}{U} (최근 120일 저점 {f['hsup']['touch']}번 모임)" if f["hsup"] else "없음",
        "심리적 지지(딱 떨어지는 가격)": f"{f['rsup']['label']}{U} 수평선 (최근 저점 {f['rsup']['low']}{U}, {f['rsup']['date']})" if f["rsup"] else "없음",
        "수평 저항": f"{f['hres']['label']}{U} (최근 120일 고점 {f['hres']['touch']}번 모임)" if f["hres"] else "없음",
        "추세선": f"{f['tline']['kind']} 추세선 {f['tline']['label']}, 오늘 위치 {P(f['tline']['now'])}{U}" if f["tline"] else "없음",
        "1년 고점": f"{P(f['y_hi'])}{U}", "1년 저점": f"{P(f['y_lo'])}{U}",
    }


# ── 그림 ──
def spec_of(f, a, mode):
    rows, v0, P, U, md = f["rows"], f["v0"], f["P"], f["U"], f["md"]
    pc = mode == "pc"
    cut = v0 if pc else max(v0, f["n"] - 160)
    candles = [{k: r[k] for k in ("time", "open", "high", "low", "close")} for r in rows[cut:]]
    mas = [{"color": c, "data": [{"time": rows[i]["time"], "value": f["mas"][p][i]} for i in range(cut, f["n"]) if f["mas"][p][i] is not None]}
           for p, c in MA]
    vis = lambda i: i >= cut
    up = f["chg"] >= 0
    callouts = []
    if vis(f["hi"]["i"]):
        callouts.append({"time": rows[f["hi"]["i"]]["time"], "price": f["hi"]["price"], "title": "기간 고점" if pc else "고점",
                         "value": f"{f['hi']['label']}{U}", "sub": f["hi"]["date"], "color": "#4f8cff", "prefer": [1, 0]})
    if vis(f["lo"]["i"]):
        callouts.append({"time": rows[f["lo"]["i"]]["time"], "price": f["lo"]["price"], "title": "저점",
                         "value": f"{f['lo']['label']}{U}", "color": "#4f8cff", "prefer": [1, 0],
                         "sub": f"고점 대비 {f['drop']:.0f}%" if f["lo"]["i"] > f["hi"]["i"] else f"이후 고점까지 +{f['rise']:.0f}%"})
    if f["swing"] and vis(f["swing"]["i"]) and pc:
        s = f["swing"]
        callouts.append({"time": rows[s["i"]]["time"], "price": s["price"],
                         "title": "반등 후 다시 꺾인 자리" if s["kind"] == "반등 고점" else "조정 후 다시 오른 자리",
                         "value": f"{P(s['price'])}{U}", "sub": s["date"], "color": "#f2f4f8", "optional": True})
    callouts.append({"time": rows[-1]["time"], "price": f["close"], "title": f"종가 ({md(f['n'] - 1)})",
                     "value": f"{P(f['close'])}{U}", "sub": f"하루 {f['chg']:+.2f}%", "color": "#26a69a" if up else "#ef5350", "prefer": [-1, 1]})
    m20 = f["ma"][20]
    if pc and m20:
        callouts.append({"time": rows[-1]["time"], "price": m20["price"], "title": "20일선", "value": f"{m20['label']}{U}",
                         "color": "#4f8cff", "prefer": [-1, -1], "optional": True})
    hlines, tlines = [], []
    if f["hsup"]:
        hlines.append({"price": f["hsup"]["price"], "color": "#ef5350", "width": 1.6})
        callouts.append({"kind": "tag", "x": 0.30, "price": f["hsup"]["price"], "arrow": False, "color": "#ef5350", "prefer": [0, 1],
                         "title": f"수평 지지 {f['hsup']['label']} (저점 {f['hsup']['touch']}번)"})
    if f["rsup"]:
        rs = f["rsup"]
        hlines.append({"price": rs["price"], "color": "#ef5350", "width": 1.8})
        callouts.append({"kind": "tag", "x": 0.30, "price": rs["price"], "arrow": False, "color": "#ef5350", "prefer": [0, 1],
                         "title": f"{rs['label']}{U} 수평선 ({rs['date']} 저점 {rs['low']}, 심리적 지지)"})
    if pc and f["hres"]:
        hlines.append({"price": f["hres"]["price"], "color": "#ffd54f", "width": 1.2, "dash": "6 4"})
        callouts.append({"kind": "tag", "x": 0.30, "price": f["hres"]["price"], "arrow": False, "color": "#ffd54f", "prefer": [0, -1],
                         "title": f"수평 저항 {f['hres']['label']} (고점 {f['hres']['touch']}번)"})
    t = f["tline"]
    if t and vis(t["i1"]):
        tlines.append({"t1": rows[t["i1"]]["time"], "p1": t["p1"], "t2": rows[-1]["time"], "p2": t["now"], "color": "#f2f4f8"})
        if pc:
            mid = (t["i1"] + t["i2"]) // 2
            callouts.append({"time": rows[mid]["time"], "price": t["p1"] + t["slope"] * (mid - t["i1"]), "color": "#f2f4f8",
                             "title": f"단기 {t['kind']} 추세선", "sub": t["label"], "prefer": [1, -1], "optional": True})
    fib = {"levels": [{"price": x["price"], "color": x["color"], "label": x["label"]} for x in f["fib"]]}

    sec = lambda title, color, items, area=None: {"title": title, "color": color, "items": items, **({"area": area} if area else {})}
    b = lambda x: f"<b>{x}</b>"
    core = [f"지금 위치: {b(f['zone_short'])}"]
    if f["sup"]:
        core.append(f"바로 아래: {b(f['sup'][0]['label'])}" + (" = 기간 저점" if f["sup"][0]["r"] == 1 else ""))
    if len(f["sup"]) > 1:
        core.append(f"그다음: {b(f['sup'][1]['label'])}" + (" = 기간 저점" if f["sup"][1]["r"] == 1 else ""))
    if f["res"]:
        core.append(f"위로는: {b(f['res'][0]['label'])}")
    core.append(f"1년 범위: {P(f['y_lo'])} ~ {P(f['y_hi'])}")
    mal = []
    for p, _ in MA:
        m = f["ma"][p]
        mal.append(f"{p}일선 {b(m['label'])} · 종가 {m['pos']} {abs(m['gap_pct']):.1f}%" if m else f"{p}일선 · 데이터 부족")
    mal.append(f"배열: {b(f['order'])}" + (f" · {f['cross']['kind']}({f['cross']['date']})" if f["cross"] else ""))
    chk = [f"고점 {f['hi']['label']} → 저점 {f['lo']['label']} ({f['drop']:.0f}%)" if f["lo"]["i"] > f["hi"]["i"]
           else f"저점 {f['lo']['label']} → 고점 {f['hi']['label']} (+{f['rise']:.0f}%)"]
    if f["swing"]:
        chk.append(f"{f['swing']['kind']} {P(f['swing']['price'])} ({f['swing']['date']})")
    if f["rsup"]:
        chk.append(f"{f['rsup']['label']}{U} 수평선 지키는지")
    elif f["hsup"]:
        chk.append(f"수평 지지 {f['hsup']['label']} 지키는지")
    if t:
        chk.append(f"{t['kind']} 추세선 오늘 {P(t['now'])} {'돌파' if t['kind'] == '하락' else '이탈'} 여부")
    if m20:
        chk.append(f"20일선 {m20['label']} {'회복' if m20['gap'] < 0 else '유지'} 여부")
    note = (f"20일선 아래 {abs(m20['gap']):,.{0 if U == '원' or abs(m20['gap']) >= 1000 else 2}f}{U}" if m20 and m20["gap"] < 0
            else f"20일선 위 {abs(m20['gap']):,.{0 if U == '원' or abs(m20['gap']) >= 1000 else 2}f}{U}" if m20 else "")
    badge = {"badge": True, "k": "이 기준이면", "w": f["trend"], "n": note, "color": f["tcolor"]}
    exch = a.get("exchange") or ""
    up_cls = "up" if up else "dn"
    header = (f"<b>{a['name'] if a['kind'] != 'us' else a['symbol']}</b>· 1일 · {exch} &nbsp; 시 {P(f['open'])} 고 {P(f['high'])} "
              f"저 {P(f['low'])} 종 <span class='{up_cls}'>{P(f['close'])} ({f['chg']:+.2f}%)</span>")
    credit = f"데이터: {a['src']} · {f['date']} 기준 · 차트: TradingView Lightweight Charts™ · 투자 판단은 본인 몫"
    title = f"{a['name']} 일봉 분석"
    if pc:
        W, H = 1280, 720
        layout = {"W": W, "H": H, "chart": {"x": 0, "y": 34, "w": W, "h": H - 34}, "margins": {"top": 0.12, "bottom": 0.27},
                  "rightOffset": max(24, round(len(candles) * 0.12)), "axisFont": 11, "titleTop": 30, "titleFont": 30,
                  "panel": {"x": 14, "y": H - 196, "w": 1200, "h": 158, "cols": "1.15fr 1.1fr 1.3fr .75fr", "pad": "14px 6px"},
                  "credit": {"right": "86px", "top": "13px"},
                  "vars": {"--fs1": "14px", "--fs2": "18px", "--fs3": "12px", "--ph": "17px", "--pf": "14px", "--bw": "26px"}}
        panel = [sec("핵심 구간 정리", "#4fc3f7", core), sec("이동평균선", "#4f8cff", mal), {**sec("체크포인트", "#ffd54f", chk[:4]), "check": True}, badge]
        blocked = ["title", ".panel"]
    else:
        W, H = 720, 900
        layout = {"W": W, "H": H, "chart": {"x": 0, "y": 100, "w": W, "h": 462}, "margins": {"top": 0.08, "bottom": 0.06},
                  "rightOffset": 20, "axisFont": 11, "titleTop": 34, "titleFont": 28,
                  "panel": {"x": 14, "y": 574, "w": W - 28, "h": 298, "cols": "1fr 1fr", "rows": "auto auto",
                            "pad": "14px 4px"},
                  "credit": {"left": "16px", "top": f"{H - 22}px"},
                  "vars": {"--fs1": "13px", "--fs2": "16px", "--fs3": "11.5px", "--ph": "17px", "--pf": "14.5px", "--bw": "24px"}}
        panel = [sec("핵심 구간 정리", "#4fc3f7", core[:4]), badge, sec("이동평균선", "#4f8cff", mal),
                 {**sec("체크포인트", "#ffd54f", chk[:4]), "check": True}]
        blocked = ["title"]
        callouts = [c for c in callouts if c.get("kind") != "tag" or "지지" in c["title"]]
        for c in callouts:
            if c.get("kind") == "tag":
                c["x"] = 0.05
    return {"layout": layout, "krw": U == "원", "candles": candles, "mas": mas, "fib": fib, "hlines": hlines, "tlines": tlines,
            "callouts": callouts, "panel": panel, "blocked": blocked, "header": header, "title": title, "credit": credit}


def chrome():
    for p in (shutil.which("chrome"), shutil.which("google-chrome"), r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe", os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"):
        if p and os.path.exists(p):
            return p
    raise SystemExit("Chrome 을 찾지 못했어요.")


def render(spec, out_png, scale):
    """HTML 을 만들어 헤드리스 Chrome 으로 캡처 (그리는 동안 창 크기 고정, 사용 중인 Chrome 과 분리된 임시 프로필)."""
    html = TEMPLATE.read_text(encoding="utf-8")
    html = html.replace("__LWC__", LWC.read_text(encoding="utf-8")).replace("__SPEC__", json.dumps(spec, ensure_ascii=False))
    W, H = spec["layout"]["W"], spec["layout"]["H"]
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "chart.html"
        page.write_text(html, encoding="utf-8")
        cmd = [chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--no-default-browser-check",
               f"--user-data-dir={Path(tmp) / 'profile'}", f"--force-device-scale-factor={scale}", f"--window-size={W},{H}",
               "--virtual-time-budget=5000", f"--screenshot={out_png}", page.as_uri()]
        subprocess.run(cmd, capture_output=True, timeout=120)
    if not Path(out_png).exists():
        raise SystemExit("차트 캡처에 실패했어요 (Chrome).")
    return html


def to_jpg(png, jpg, width):
    from PIL import Image
    im = Image.open(png).convert("RGB")
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    im.save(jpg, "JPEG", quality=84, optimize=True, progressive=True)


# ── 본문 ──
def template_text(f, a):
    P, U = f["P"], f["U"]
    pos = {"하락추세": "20일선 아래에서 내려오는 중", "상승추세": "20일선 위에서 올라가는 중",
           "방향 탐색": "이평선 사이에서 방향을 고르는 중"}[f["trend"]]
    s1 = f["sup"][0] if f["sup"] else None
    s2 = f["sup"][1] if len(f["sup"]) > 1 else None
    r1 = f["res"][0] if f["res"] else None
    lines = ["차트리포트 입니다 ^^", f"{a['name']} 일봉 체크", "", " 지금 위치", pos,
             f"현재가 {P(f['close'])}{U} (하루 {f['chg']:+.2f}%)", f"피보나치로는 {f['zone']}", "", " 볼 자리"]
    if s1:
        lines.append(f"· 아래: {s1['label']}" + (" (기간 저점)" if s1["r"] == 1 else ""))
    if f["rsup"]:
        lines.append(f"· {f['rsup']['label']}{U} 수평선: {f['rsup']['date']} 저점 {f['rsup']['low']}이 닿은 자리")
    if f["hsup"]:
        lines.append(f"· 수평 지지: {f['hsup']['label']} (최근 저점이 {f['hsup']['touch']}번 모인 자리)")
    if r1:
        lines.append(f"· 위: {r1['label']}")
    if f["ma"][20]:
        lines.append(f"· 20일선: {f['ma'][20]['label']}")
    lines += ["", " 시나리오"]
    # 시나리오는 종가에서 가장 가까운 지지·저항으로 (피보·수평선·20일선 중)
    sups = sorted([(x["price"], P(x["price"])) for x in f["sup"]] +
                  [(x["price"], x["label"]) for x in (f["rsup"], f["hsup"]) if x], reverse=True)
    ress = sorted([(x["price"], P(x["price"])) for x in f["res"]] +
                  ([(f["ma"][20]["price"], f"20일선 {f['ma'][20]['label']}")] if f["ma"][20] and f["ma"][20]["gap"] < 0 else []))
    if sups:
        lo1 = sups[0][1]
        lo2 = next((l for p, l in sups[1:] if p < sups[0][0] * 0.99), None)
        lines.append(f"A. {lo1} 지키면 → " + (f"{ress[0][1]}까지 되돌림 확인" if ress else "고점 다시 시도하는지 확인"))
        lines.append(f"B. {lo1} 깨면 → " + (f"다음 지지 {lo2}에서 받는지 확인" if lo2 else "새 저점 만드는지 확인"))
    lines += ["", "차트는 모바일·PC 버전 같이 올려 드립니다.", "투자 판단은 본인 몫입니다."]
    return "\n".join(lines)


SYSTEM = """당신은 텔레그램 채널 '차트보는 말희아빠' 운영자 대신 '차트리포트' 글을 씁니다.
형식은 아래 예시를 그대로 따릅니다 (빈 줄·앞 공백 포함):
차트리포트 입니다 ^^
(종목) 일봉 체크

 지금 위치
(한두 줄)
현재가 (값)

 볼 자리
· 아래: (값)
· 위: (값)

 시나리오
A. (지지)를 지키면 → (저항)까지 되돌림 확인
B. (지지)를 깨면 → 다음 지지 (값)에서 받는지 확인

(한두 줄 코멘트)

차트는 모바일·PC 버전 같이 올려 드립니다.
투자 판단은 본인 몫입니다.

규칙:
- 숫자는 '자료'에 있는 값만 그대로 씁니다. 새로 계산하거나 반올림하거나 지어내지 않습니다. 자료에 없는 숫자(목표가·확률·날짜)는 쓰지 않습니다.
- 말투는 차분한 존댓말, 짧은 줄. 이모지는 쓰지 않습니다. 400자 안팎.
- '~가 아니라 ~다' 같은 뒤집기 문장, '첫째·둘째' 나열, '핵심은', '결론적으로', '주목할 점' 같은 AI 말투를 쓰지 않습니다.
- 매수·매도 권유, 목표가, '지금 사라' 같은 표현을 쓰지 않습니다.
- 본문만 출력합니다."""


NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
BANNED = ("아니라", "아닌,", "첫째", "둘째", "결론적으로", "핵심은", "주목할", "매수", "매도", "목표가")


def check_text(text, facts):
    """계산에 없는 숫자·금지 표현이 있으면 그 목록을 돌려준다."""
    allowed = {x.replace(",", "") for x in NUM.findall(json.dumps(facts, ensure_ascii=False))}
    allowed |= {str(i) for i in range(0, 11)} | {"20", "50", "200"}
    bad = [x for x in NUM.findall(text) if x.replace(",", "") not in allowed]
    bad += [w for w in BANNED if w in text]
    return bad


def write_text(f, a, use_ai, style=""):
    base = template_text(f, a)
    if not use_ai:
        return base, "template"
    import llm
    if not llm.ready():
        return base, "template"
    facts = facts_of(f, a)
    prompt = "자료:\n" + json.dumps(facts, ensure_ascii=False, indent=1)
    if style:
        prompt += "\n\n우리 채널 최근 글 (말투만 참고):\n" + style
    prompt += "\n\n참고용 기본 문안 (숫자는 이대로 맞음, 문장은 더 자연스럽게 다듬어도 됨):\n" + base
    try:
        r = llm.Anthropic().messages.create(model=MODEL, max_tokens=2000, system=SYSTEM,
                                            messages=[{"role": "user", "content": prompt}], output_config={"effort": "low"})
        text = r.content[0].text.strip().strip("`").strip()
    except (llm.APIStatusError, llm.APIConnectionError) as e:
        print("⚠️ Claude 본문 실패 — 기본 문안을 써요:", str(e)[:200])
        return base, "template"
    bad = check_text(text, facts)
    if bad or "차트리포트" not in text:
        print("⚠️ Claude 본문에 계산에 없는 숫자·표현", bad[:6], "— 기본 문안을 써요")
        return base, "template"
    return text, "claude"


# ── 실행 ──
def slug(a):
    return re.sub(r"[^A-Za-z0-9]", "", a["symbol"]) or "chart"


def make(query, use_ai=True, style=""):
    a = resolve(query)
    rows = fetch(a)
    f = analyze(rows, a, 365 if a["kind"] == "coin" else 260)
    RAW.mkdir(parents=True, exist_ok=True)
    WEB.mkdir(parents=True, exist_ok=True)
    s = slug(a)
    files = {}
    for mode, scale, width in (("pc", 1.5, 1600), ("m", 1.5, 1080)):
        png = RAW / f"{s}_{mode}.png"
        png.unlink(missing_ok=True)
        render(spec_of(f, a, "pc" if mode == "pc" else "mobile"), png, scale)
        to_jpg(png, WEB / f"{s}_{mode}.jpg", width)
        files[mode] = png
    text, by = write_text(f, a, use_ai, style)
    item = {"query": query, "name": a["name"], "symbol": a["symbol"], "kind": a["kind"], "date": f["date"],
            "close": f"{f['P'](f['close'])}{f['U']}", "chg": round(f["chg"], 2), "trend": f["trend"],
            "pc": f"charts/{s}_pc.jpg", "mobile": f"charts/{s}_m.jpg", "text": text, "text_by": by,
            "made_at": datetime.now(KST).isoformat(timespec="seconds")}
    return item, files


def load_reports():
    return json.loads(REPORTS.read_text(encoding="utf-8")) if REPORTS.exists() else {"items": []}


def save_reports(d, new):
    keep = [x for x in d["items"] if not any(x["symbol"] == y["symbol"] and x.get("slot") == y.get("slot") for y in new)]
    d["items"] = (new + keep)[:12]
    d["updated_at"] = datetime.now(KST).isoformat(timespec="seconds")
    REPORTS.parent.mkdir(parents=True, exist_ok=True)
    REPORTS.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    used = {Path(x[k]).name for x in d["items"] for k in ("pc", "mobile")}
    for p in WEB.glob("*.jpg"):   # 목록에서 빠진 그림은 지움 (저장소가 커지지 않게)
        if p.name not in used:
            p.unlink()


def send(item, files):
    """PC·모바일 이미지 두 장을 먼저, 그 아래에 설명 글(그대로 복사해 올릴 본문)을 따로 보낸다."""
    from publish.notify import send as send_text, send_photos
    ok = send_photos([files["pc"], files["m"]], f"📈 {item['name']} 일봉 분석 · {item['date']} 종가 {item['close']} (PC용·모바일용)")
    ok = send_text(item["text"]) and ok
    print("📨 봇으로 보냄" if ok else "⚠️ 봇 보내기 실패/미설정", item["name"])
    return ok


def guess_symbol(t):
    """옛 tg_ai.json 처럼 chart 칸이 없을 때 본문에서 코인을 찾는다 (주식 티커는 chart 칸으로만)."""
    text = f"{t.get('type', '')} {t.get('text', '')}"
    for k in sorted(COINS, key=len, reverse=True):
        if len(k) > 2 and k in text:
            return k
    return "비트코인" if "코인" in text or "비트" in text else None


def chart_posts(ai):
    """오늘 문구 중 차트 글 → (글, 종목). 'A 칸 → B' 처럼 바뀐 칸은 바뀐 쪽(B)을 본다."""
    out = []
    for t in ai.get("today", []):
        kind = t.get("type", "").split("→")[-1]
        q = (t.get("chart") or "").strip() or (guess_symbol(t) if "차트" in kind else None)
        if q:
            out.append((t, q))
    return out


def from_tg(use_ai, notify=True, force=False):
    """오늘 문구의 차트 글 중 다음 차례(지금 이후 가장 가까운 칸) 하나를 만든다. 하루 2번(08·19시) 자동 + 수동 버튼."""
    p = SITE / "tg_ai.json"
    ai = json.loads(p.read_text(encoding="utf-8") or "{}") if p.exists() else {}
    posts = chart_posts(ai)
    now = datetime.now(KST).strftime("%H:%M")
    hhmm = lambda t: (re.match(r"\d{1,2}:\d{2}", t.get("time", "")) or [""])[0].zfill(5)
    nxt = [x for x in posts if hhmm(x[0]) >= now]
    t, q = nxt[0] if nxt else posts[-1] if posts else ({"time": now, "type": "차트리포트"}, "비트코인")
    d = load_reports()
    slot = f"{ai.get('analyzed_at', '')}|{t['time']}"
    if not force and slot in ({x.get("slot") for x in d["items"]} | set(d.get("failed", []))):
        return print(f"이번 차트 글({t['time']} {q})은 이미 만들었어요.")
    mine = SITE / "tg_mine.json"
    style = "\n---\n".join(m["text"][:300] for m in json.loads(mine.read_text(encoding="utf-8"))[:5]) if mine.exists() else ""
    try:
        item, files = make(q, use_ai, style)
    except (SystemExit, requests.RequestException, KeyError, ValueError, IndexError) as e:
        print(f"⚠️ {q} 차트 실패: {e}")
        d["failed"] = (d.get("failed", []) + [slot])[-30:]   # 같은 칸을 다시 시도하지 않게
        return save_reports(d, [])
    item.update(slot=slot, slot_time=t["time"], slot_type=t.get("type", ""))
    item["sent"] = send(item, files) if notify else False
    save_reports(d, [item])
    print(f"✅ 차트리포트 {item['name']} ({t['time']})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="*", help="종목 (IONQ, 비트코인, SK하이닉스, 000660 … 쉼표로 여러 개도 됨)")
    ap.add_argument("--from-tg", action="store_true", help="tg_ai.json 오늘 문구의 차트 글 종목으로 만들고 봇으로 보냄")
    ap.add_argument("--send", action="store_true", help="봇으로도 보내기")
    ap.add_argument("--no-ai", action="store_true", help="Claude 없이 정해진 문장으로 본문")
    ap.add_argument("--no-send", action="store_true", help="--from-tg 때 봇으로 보내지 않음 (시험용)")
    ap.add_argument("--force", action="store_true", help="--from-tg 때 이미 만든 칸이어도 다시 (수동 버튼)")
    ap.add_argument("--no-save", action="store_true", help="사이트 목록(chart_reports.json)에 넣지 않음")
    args = ap.parse_args()
    load_env()
    if args.from_tg:
        return from_tg(not args.no_ai, not args.no_send, args.force)
    if not args.symbols:
        ap.error("종목을 넣거나 --from-tg 를 쓰세요")
    d, new = load_reports(), []
    qs = [q.strip() for x in args.symbols for q in re.split(r"[,\n]", x) if q.strip()]
    for q in qs[:5]:
        try:
            item, files = make(q, not args.no_ai)
        except (SystemExit, requests.RequestException, KeyError, ValueError, IndexError) as e:
            msg = f"'{q}' 차트를 못 만들었어요: {e}"
            print("⚠️", msg)
            if args.send:
                from publish.notify import send as send_text
                send_text(msg + "\n티커(TSLA)·종목명(삼성전자)·6자리 코드(005930)·코인 이름(이더리움)으로 다시 넣어 주세요.")
            continue
        print(f"\n✅ {item['name']} · {item['date']} 종가 {item['close']} ({item['chg']:+.2f}%) · {item['trend']}")
        print(f"   PC {files['pc']}\n   모바일 {files['m']}\n   본문({item['text_by']}):\n" + item["text"])
        if args.send:
            item["sent"] = send(item, files)
        new.append(item)
    if not args.no_save:
        save_reports(d, new)


if __name__ == "__main__":
    sys.exit(main())
