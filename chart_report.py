"""텔레그램 '차트리포트' 글에 붙일 차트 분석 이미지 + 본문을 만든다.

    python chart_report.py IONQ 비트코인 SK하이닉스   # 종목마다 PC(가로)·모바일(세로) PNG + 본문
    python chart_report.py 아이온큐 --send             # 봇으로도 보냄 (TELEGRAM_BOT_TOKEN·CHAT_ID)
    python chart_report.py --from-tg                 # 오늘 문구의 다음 차트 글 종목 하나로 만들고 봇으로 보냄 (PC가 매일 아침 08시에 --force 로)
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
# 지수·선물·환율·원자재 (트레이딩뷰 이름과 한글 이름 → 야후 코드, 표시 티커, 이름, 단위)
WORLD = [
    (("나스닥", "나스닥지수", "나스닥종합", "IXIC", "NASDAQ", "COMP"), "^IXIC", "IXIC", "나스닥 종합", "pt"),
    (("나스닥100", "NDX", "NAS100", "US100", "NASDAQ100"), "^NDX", "NDX", "나스닥100", "pt"),
    (("S&P500", "SP500", "에스앤피", "에스앤피500", "SPX", "US500", "GSPC"), "^GSPC", "SPX", "S&P500", "pt"),
    (("다우", "다우지수", "DJI", "US30", "DOW"), "^DJI", "DJI", "다우존스", "pt"),
    (("러셀", "러셀2000", "RUT", "US2000"), "^RUT", "RUT", "러셀2000", "pt"),
    (("필라델피아반도체", "반도체지수", "SOX"), "^SOX", "SOX", "필라델피아 반도체", "pt"),
    (("코스피", "KOSPI", "KS11"), "^KS11", "KOSPI", "코스피", "pt"),
    (("코스닥", "KOSDAQ", "KQ11"), "^KQ11", "KOSDAQ", "코스닥", "pt"),
    (("코스피200", "KOSPI200", "KS200"), "^KS200", "KOSPI200", "코스피200", "pt"),
    (("닛케이", "니케이", "NI225", "N225", "JP225"), "^N225", "NI225", "닛케이225", "pt"),
    (("항셍", "HSI", "HK50"), "^HSI", "HSI", "항셍", "pt"),
    (("VIX", "공포지수", "빅스"), "^VIX", "VIX", "VIX", "pt"),
    (("미국10년물", "미국채10년", "10년물", "US10Y", "TNX"), "^TNX", "US10Y", "미국 10년물 금리", "%"),
    (("달러인덱스", "DXY", "DX"), "DX-Y.NYB", "DXY", "달러인덱스", "pt"),
    (("환율", "원달러", "달러원", "원달러환율", "USDKRW"), "KRW=X", "USDKRW", "원/달러 환율", "원"),
    (("엔달러", "달러엔", "USDJPY"), "JPY=X", "USDJPY", "달러/엔", "엔"),
    (("유로달러", "EURUSD"), "EURUSD=X", "EURUSD", "유로/달러", ""),
    (("금", "금값", "금선물", "GOLD", "XAUUSD", "GC", "GC1!"), "GC=F", "GC1!", "금 선물", "달러"),
    (("은", "은선물", "SILVER", "XAGUSD", "SI", "SI1!"), "SI=F", "SI1!", "은 선물", "달러"),
    (("유가", "WTI", "국제유가", "원유", "USOIL", "CL", "CL1!"), "CL=F", "CL1!", "WTI 원유 선물", "달러"),
    (("브렌트", "브렌트유", "UKOIL", "BRENT", "BRN1!", "BZ1!"), "BZ=F", "BRN1!", "브렌트유 선물", "달러"),
    (("천연가스", "NATGAS", "NG", "NG1!"), "NG=F", "NG1!", "천연가스 선물", "달러"),
    (("구리", "COPPER", "HG", "HG1!"), "HG=F", "HG1!", "구리 선물", "달러"),
    (("나스닥선물", "NQ", "NQ1!", "NQ=F"), "NQ=F", "NQ1!", "나스닥100 선물", "pt"),
    (("S&P선물", "에스앤피선물", "ES", "ES1!", "ES=F"), "ES=F", "ES1!", "S&P500 선물", "pt"),
    (("다우선물", "YM", "YM1!"), "YM=F", "YM1!", "다우 선물", "pt"),
    (("러셀선물", "RTY", "RTY1!"), "RTY=F", "RTY1!", "러셀2000 선물", "pt"),
]
WORLD_KEY = {k.upper().replace(" ", ""): (yf, sym, name, unit) for keys, yf, sym, name, unit in WORLD for k in keys}
WORLD_YF = {yf: (yf, sym, name, unit) for keys, yf, sym, name, unit in WORLD}
CUR = {"USD": "달러", "KRW": "원", "JPY": "엔", "HKD": "홍콩달러", "EUR": "유로", "CNY": "위안", "GBP": "파운드", "TWD": "대만달러"}
FIB = [(0, "#9598a1"), (0.236, "#c9716e"), (0.382, "#c9a35a"), (0.5, "#7fae7a"), (0.618, "#4f9e93"), (0.786, "#6a9fc9"), (1, "#9598a1")]
MA = [(20, "#d9a441"), (240, "#4c8bf5")]   # 추세는 20선·240선으로 봄
# 봉 종류: name 글에 쓰는 이름 · short 차트 머리글 · show 화면에 보일 봉 수 (일봉은 코인 365 · 주식 260)
TF = {"1m": {"name": "1분봉", "short": "1분", "show": 240}, "15m": {"name": "15분봉", "short": "15분", "show": 220}, "1h": {"name": "1시간봉", "short": "1시간", "show": 220},
      "4h": {"name": "4시간봉", "short": "4시간", "show": 220}, "1d": {"name": "일봉", "short": "1일", "show": None},
      "1w": {"name": "주봉", "short": "1주", "show": 156}}
INTRADAY = ("1m", "15m", "1h", "4h")
SCALP = {"1m": 60, "15m": 900}   # 단타용 봉: RSI·볼린저밴드·거래량 칸을 함께 보여 줌 (값은 봉 길이, 초)


# ── 종목 찾기·시세 ──
def world(yf, sym, name, unit):
    return {"kind": "us", "yf": yf, "symbol": sym, "name": name, "unit_fixed": unit, "exchange": ""}


def resolve(q):
    key = q.strip()
    if ":" in key:   # 트레이딩뷰식 'NASDAQ:TSLA' · 'KRX:000660' · 'UPBIT:BTCKRW' · 'TVC:DXY' → 거래소 떼고 종목만
        ex, key = (x.strip() for x in key.split(":", 1))
        m = re.fullmatch(r"([A-Z0-9]{2,10})(KRW|USDT|USDC|USD|BUSD)", key.upper())
        if ex.upper() in ("UPBIT", "BITHUMB", "BINANCE", "BYBIT", "OKX", "COINBASE", "BITGET") and m and not key.upper().endswith(".P"):
            key = m[1].lower() if m[1].lower() in COINS else key   # 현물 코인은 바이낸스 현물로
    w = WORLD_KEY.get(key.upper().replace(" ", ""))
    if w:
        return world(*w)
    if re.fullmatch(r"\^[A-Za-z0-9.]{1,10}|[A-Za-z0-9]{1,6}=[FX]|[A-Za-z]{2,6}1!|[A-Za-z0-9]{1,6}\.[A-Za-z]{1,3}", key) and not re.fullmatch(r"[A-Za-z]{1,5}\.[AB]", key):
        yf = re.sub(r"1!$", "=F", key.upper())   # 야후 코드 그대로 (^GSPC · GC=F · KRW=X · 7203.T · 0700.HK), 트레이딩뷰 연속선물 XX1! → XX=F
        if yf in WORLD_YF:
            return world(*WORLD_YF[yf])
        return {"kind": "us", "yf": yf, "symbol": key.upper(), "name": key.upper(), "exchange": "", **({"unit_fixed": "pt"} if yf.startswith("^") else {})}
    m = re.fullmatch(r"(?:BINANCE:)?([A-Z0-9]{1,16})USDT(?:\.P|PERP)?", key.upper())   # 바이낸스 무기한 선물 (AAPLUSDT.P · BTCUSDT · BINANCE:ETHUSDT.P)
    if m:
        return {"kind": "coin", "perp": True, "symbol": m[1] + "USDT", "name": f"{m[1]} 선물", "exchange": "BINANCE PERP"}
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
        raise SystemExit(f"'{q}' 종목을 찾지 못했어요 — 티커(IONQ), 6자리 코드(000660), 바이낸스 선물(AAPLUSDT.P), 지수·선물(나스닥, GC1!, ^GSPC)로 넣어 주세요.")
    it = items[0]
    if it.get("nationCode") == "KOR":
        return {"kind": "kr", "symbol": it["code"], "name": it["name"], "exchange": it.get("typeName") or "KRX"}
    return {"kind": "us", "symbol": it["code"], "name": it["name"], "exchange": it.get("typeCode") or ""}


def naver_ac(q):
    r = requests.get("https://ac.stock.naver.com/ac", params={"q": q, "target": "stock"}, headers=UA, timeout=20)
    return r.json().get("items", [])


def bar(t, o, h, l, c, v, tf, off):
    """봉 하나. time 은 차트 값(분봉은 한국시간으로 옮긴 초, 일·주봉은 날짜), d 는 글에 쓰는 시각."""
    if tf in INTRADAY:
        at = datetime.fromtimestamp(t, KST)
        return {"time": int(t) + 32400, "ts": int(t), "day": at.strftime("%Y-%m-%d"), "d": at.strftime("%m/%d %H:%M"),
                "open": o, "high": h, "low": l, "close": c, "volume": v or 0}
    day = datetime.fromtimestamp(t + off, timezone.utc).strftime("%Y-%m-%d")
    return {"time": day, "day": day, "d": day[5:].replace("-", "/"), "open": o, "high": h, "low": l, "close": c, "volume": v or 0}


def to_4h(rows):
    """1시간봉 → 4시간봉 (야후에 4시간봉이 없어 장 시작부터 4시간씩 묶음)."""
    out, start = [], None
    for r in rows:
        if start is None or r["ts"] - prev > 3 * 3600:   # 3시간 넘게 비면 새 장
            start, key = r["ts"], None
        prev = r["ts"]
        k = (start, (r["ts"] - start) // 14400)
        if k != key:
            out.append(dict(r))
            key = k
        else:
            x = out[-1]
            x["high"], x["low"], x["close"] = max(x["high"], r["high"]), min(x["low"], r["low"]), r["close"]
            x["volume"] += r["volume"]
    return out


def yahoo_rows(symbol, tf, a=None):
    rng, iv = {"1m": ("5d", "1m"), "15m": ("60d", "15m"), "1h": ("2y", "60m"), "4h": ("2y", "60m"), "1d": ("3y", "1d"), "1w": ("10y", "1wk")}[tf]
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}", params={"range": rng, "interval": iv},
                     headers=UA, timeout=30).json()["chart"]["result"][0]
    meta, q = r["meta"], r["indicators"]["quote"][0]
    if a is not None:
        a["exchange"] = a["exchange"] or meta.get("fullExchangeName", "")
        a["currency"] = meta.get("currency") or "USD"
    off = meta.get("gmtoffset", 0)
    src = [list(x) for x in zip(r["timestamp"], q["open"], q["high"], q["low"], q["close"], q["volume"])]
    last = src[-1]
    if last[1] is not None and last[4] is None and meta.get("regularMarketPrice"):   # 야후가 막 끝난(진행 중인) 봉의 종가를 비워 줄 때가 있음 → 시세 값으로 채움
        last[4] = meta["regularMarketPrice"]
        last[2] = max(x for x in (last[2], meta.get("regularMarketDayHigh"), last[1], last[4]) if x is not None)
        last[3] = min(x for x in (last[3], meta.get("regularMarketDayLow"), last[1], last[4]) if x is not None)
    rows = [bar(t, o, h, l, c, v, tf, off) for t, o, h, l, c, v in src if None not in (o, h, l, c)]
    rows = list({x["time"]: x for x in rows}.values())
    if tf in INTRADAY and rows and not rows[-1]["volume"] and rows[-1]["high"] == rows[-1]["low"]:   # 장 마감 순간의 거래 없는 봉은 뺌
        rows.pop()
    return to_4h(rows) if tf == "4h" else rows


def fetch(a, tf="1d"):
    """봉 [{time, day, d, open, high, low, close, volume}] — 오래된 것부터."""
    if a.get("perp"):
        k = requests.get("https://fapi.binance.com/fapi/v1/klines", params={"symbol": a["symbol"], "interval": tf, "limit": 1000}, timeout=30)
        if k.status_code == 400:
            raise SystemExit(f"바이낸스 선물에 {a['symbol']} 종목이 없어요.")
        k.raise_for_status()
        rows = [bar(x[0] / 1000, float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5]), tf, 0) for x in k.json()]
        a["unit"], a["src"] = "달러", "바이낸스 USDT 무기한"
    elif a["kind"] == "us":
        try:
            rows = yahoo_rows(a.get("yf") or a["symbol"].replace(".", "-"), tf, a)   # BRK.B → 야후 BRK-B
        except (KeyError, IndexError, TypeError, ValueError):
            raise SystemExit(f"야후 파이낸스에서 '{a['symbol']}' 시세를 못 찾았어요 — 티커나 코드를 다시 확인해 주세요.")
        a["unit"] = a["unit_fixed"] if "unit_fixed" in a else CUR.get(a.get("currency"), a.get("currency") or "달러")
        a["src"] = "야후 파이낸스"
    elif a["kind"] == "kr" and tf in INTRADAY:   # 네이버는 분봉을 길게 안 줌 → 야후 (국내 분봉은 조금 늦음)
        rows = []
        for suffix in (".KQ", ".KS") if "코스닥" in (a.get("exchange") or "") else (".KS", ".KQ"):
            try:
                rows = yahoo_rows(a["symbol"] + suffix, tf)
            except (requests.RequestException, KeyError, IndexError, TypeError, ValueError):
                rows = []
            if rows:
                break
        a["unit"], a["src"] = "원", "야후 파이낸스(지연 시세)"
    elif a["kind"] == "kr":
        now = datetime.now(KST)
        t = requests.get("https://api.finance.naver.com/siseJson.naver", headers=UA, timeout=30,
                         params={"symbol": a["symbol"], "requestType": 1, "startTime": (now - timedelta(days=3650 if tf == "1w" else 1100)).strftime("%Y%m%d"),
                                 "endTime": now.strftime("%Y%m%d"), "timeframe": "week" if tf == "1w" else "day"}).text
        rows = [{"time": f"{d[:4]}-{d[4:6]}-{d[6:]}", "day": f"{d[:4]}-{d[4:6]}-{d[6:]}", "d": f"{d[4:6]}/{d[6:]}", "open": float(o), "high": float(h), "low": float(l), "close": float(c), "volume": float(v)}
                for d, o, h, l, c, v in re.findall(r'\["(\d{8})",\s*([\d.]+),\s*([\d.]+),\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)', t)]
        rows = [r for r in rows if r["open"] > 0]   # 거래정지일
        a["unit"], a["src"] = "원", "네이버 금융"
    else:
        try:
            k = requests.get("https://api.binance.com/api/v3/klines", params={"symbol": a["symbol"] + "USDT", "interval": tf, "limit": 1000},
                             timeout=30)
            k.raise_for_status()
            rows = [bar(x[0] / 1000, float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5]), tf, 0) for x in k.json()]
            a["unit"], a["src"], a["exchange"] = "달러", "바이낸스 USDT", "BINANCE"
        except requests.RequestException:
            rows, to = [], None
            path = {"1m": "minutes/1", "15m": "minutes/15", "1h": "minutes/60", "4h": "minutes/240", "1d": "days", "1w": "weeks"}[tf]
            for _ in range(4):   # 업비트는 한 번에 200개
                p = {"market": "KRW-" + a["symbol"], "count": 200, **({"to": to} if to else {})}
                xs = requests.get(f"https://api.upbit.com/v1/candles/{path}", params=p, headers=UA, timeout=30).json()
                if not xs:
                    break
                rows += [bar(datetime.fromisoformat(x["candle_date_time_utc"] + "+00:00").timestamp(), x["opening_price"], x["high_price"], x["low_price"],
                             x["trade_price"], x["candle_acc_trade_volume"], tf, 32400) for x in xs]
                to = xs[-1]["candle_date_time_utc"].replace("T", " ")
            rows.sort(key=lambda r: r["ts"] if tf in INTRADAY else r["time"])
            a["unit"], a["src"], a["exchange"] = "원", "업비트 KRW", "UPBIT"
    if len(rows) < 60:
        raise SystemExit(f"{a['name']} {TF[tf]['name']} 시세가 너무 적어요({len(rows)}개).")
    return rows


def live_of(a, rows, tf="1d"):
    """지금 시세 상태 — label: 장중·실시간·종가, ext: 미국 프리마켓·시간외 가격. 장중 일봉의 마지막 값은 이미 지금 가격이다."""
    now = datetime.now(KST)
    live = {"label": "종가", "at": now, "ext": None}
    if a["kind"] == "coin":
        live["label"] = "실시간"
    elif a["kind"] == "kr":
        if now.weekday() < 5 and (tf == "1w" or rows[-1]["day"] == now.strftime("%Y-%m-%d")) and "0900" <= now.strftime("%H%M") < "1530":
            live["label"] = "장중"
    else:
        try:
            r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{a.get('yf') or a['symbol'].replace('.', '-')}", headers=UA, timeout=30,
                             params={"range": "1d", "interval": "5m", "includePrePost": "true"}).json()["chart"]["result"][0]
            meta, per = r["meta"], r["meta"]["currentTradingPeriod"]
            ts = now.timestamp()
            if per["regular"]["start"] <= ts < per["regular"]["end"]:
                if tf != "1d" or rows[-1]["time"] == datetime.fromtimestamp(ts + meta.get("gmtoffset", 0), timezone.utc).strftime("%Y-%m-%d"):
                    live["label"], live["at"] = "장중", datetime.fromtimestamp(meta["regularMarketTime"], KST)
            else:
                t, c = [(t, c) for t, c in zip(r["timestamp"], r["indicators"]["quote"][0]["close"]) if c is not None][-1]
                if t > meta["regularMarketTime"] + 60:   # 정규장이 끝난 뒤 체결이 있으면
                    live["ext"] = {"label": "프리마켓" if per["pre"]["start"] <= t < per["pre"]["end"] else "시간외", "price": c,
                                   "at": datetime.fromtimestamp(t, KST)}
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as e:
            print("⚠️ 시간외 시세 확인 실패 — 일봉 값만 써요:", str(e)[:100])
    return live


def apply_live(f, a, live):
    """f 에 시세 상태를 붙인다: px(현재가/종가), basis(글·이미지에 쓰는 기준 문구)."""
    P, U = f["P"], f["U"]
    at = live["at"].strftime("%m/%d %H:%M")
    f["live"], f["px"] = live, "종가" if live["label"] == "종가" else "현재가"
    last = f["rows"][-1]["d"]
    if f["tf"] in INTRADAY:
        f["basis"] = f"{last} 봉 · {at} 조회" + (f" ({live['label']})" if live["label"] != "종가" else "")
    elif live["label"] == "종가":
        f["basis"] = f"{last} 종가 · {at} 조회"
    else:
        f["basis"] = f"{at} 시세 ({live['label']})"
    if live["ext"]:
        e = live["ext"]
        e["chg"] = (e["price"] / f["close"] - 1) * 100
        e["text"] = f"{e['label']} {P(e['price'])}{U} (종가 대비 {e['chg']:+.2f}%)"
        f["basis"] += f" · {e['text']}"


# ── 계산 ──
def sma(xs, n):
    out, s = [], 0.0
    for i, x in enumerate(xs):
        s += x
        if i >= n:
            s -= xs[i - n]
        out.append(s / n if i >= n - 1 else None)
    return out


def rsi_of(xs, n=14):
    """RSI (와일더 평균)."""
    out, up, dn = [None] * len(xs), 0.0, 0.0
    for i in range(1, len(xs)):
        d = xs[i] - xs[i - 1]
        if i <= n:
            up += max(d, 0) / n
            dn += max(-d, 0) / n
        else:
            up = (up * (n - 1) + max(d, 0)) / n
            dn = (dn * (n - 1) + max(-d, 0)) / n
        if i >= n:
            out[i] = 100.0 if dn == 0 else 100 - 100 / (1 + up / dn)
    return out


def indicators(rows, tf, P):
    """단타용 RSI(14)·볼린저밴드(20, 2)·거래량 — 글과 차트가 같은 값을 쓴다."""
    closes = [r["close"] for r in rows]
    mid = sma(closes, 20)
    up, lo = [None] * len(rows), [None] * len(rows)
    for i in range(19, len(rows)):
        w = closes[i - 19:i + 1]
        sd = (sum((x - mid[i]) ** 2 for x in w) / 20) ** 0.5
        up[i], lo[i] = mid[i] + 2 * sd, mid[i] - 2 * sd
    rsi = rsi_of(closes)
    close, u, l = closes[-1], up[-1], lo[-1]
    pb = (close - l) / (u - l) if u > l else 0.5
    bb = ("상단 돌파" if close > u else "하단 이탈" if close < l else "상단 근처" if pb >= 0.8 else "하단 근처" if pb <= 0.2
          else "중단 위" if pb >= 0.5 else "중단 아래")
    widths = [(a - b) / m for a, b, m in zip(up[-120:], lo[-120:], mid[-120:]) if a is not None and m]
    squeeze = len(widths) >= 40 and sum(w <= widths[-1] for w in widths) / len(widths) <= 0.2   # 최근 120봉 중 폭이 좁은 편
    # 거래량은 진행 중인 봉을 빼고 완성된 봉으로 비교
    last = -1 if rows[-1]["ts"] + SCALP[tf] <= datetime.now(KST).timestamp() else -2
    base = [r["volume"] for r in rows[last - 20:last]]
    ratio = rows[last]["volume"] / (sum(base) / len(base)) if sum(base) else None
    now = rsi[-1]
    return {"rsi": rsi, "up": up, "lo": lo, "rsi_now": now, "rsi_word": "과매수권" if now >= 70 else "과매도권" if now <= 30 else "중립 위" if now >= 50 else "중립 아래",
            "pb": pb, "bb_word": bb, "squeeze": squeeze, "up_now": u, "lo_now": l, "up_label": P(u), "lo_label": P(l), "vol": ratio,
            "vol_word": None if ratio is None else "급증" if ratio >= 2 else "평균 이상" if ratio >= 1.3 else "한산" if ratio <= 0.6 else "평균 수준"}


def ind_line(f):
    """RSI·볼밴·거래량 한 줄."""
    x = f["ind"]
    out = [f"RSI {x['rsi_now']:.1f}({x['rsi_word']})", f"볼밴 {x['bb_word']}" + (" · 밴드 좁음" if x["squeeze"] else "")]
    if x["vol"] is not None:
        out.append(f"거래량 평균의 {x['vol']:.1f}배({x['vol_word']})")
    return " · ".join(out)


def ha_of(rows):
    """하이킨아시 캔들과 지금 흐름 (같은 색이 몇 개째인지, 꼬리로 본 힘)."""
    out = []
    for i, r in enumerate(rows):
        c = (r["open"] + r["high"] + r["low"] + r["close"]) / 4
        o = (out[-1]["open"] + out[-1]["close"]) / 2 if out else (r["open"] + r["close"]) / 2
        out.append({"time": r["time"], "open": o, "high": max(r["high"], o, c), "low": min(r["low"], o, c), "close": c})
    last = out[-1]
    up = last["close"] >= last["open"]
    streak = 0
    for x in reversed(out):
        if (x["close"] >= x["open"]) != up:
            break
        streak += 1
    body, span = abs(last["close"] - last["open"]), last["high"] - last["low"]
    word = f"하이킨아시 {'양봉' if up else '음봉'} " + (f"{streak}연속" if streak > 1 else "전환")
    if span and body <= span * 0.25:
        word += " · 몸통 작음(힘 약해짐)"
    elif up and last["low"] >= min(last["open"], last["close"]):
        word += " · 아래꼬리 없음(상승 힘 강함)"
    elif not up and last["high"] <= max(last["open"], last["close"]):
        word += " · 위꼬리 없음(하락 힘 강함)"
    return {"rows": out, "up": up, "streak": streak, "word": word}


def atr_of(rows, P, U, n=14, back=20):
    """ATR(n): 그 봉 기준 평균 진폭 (와일더 방식, 트레이딩뷰 기본값과 같음). back 봉 전과 비교해 변동성 방향도 본다."""
    if len(rows) <= n:
        return None
    tr = [max(b["high"] - b["low"], abs(b["high"] - a["close"]), abs(b["low"] - a["close"])) for a, b in zip(rows, rows[1:])]
    atr = sum(tr[:n]) / n
    series = [atr]
    for x in tr[n:]:
        atr = (atr * (n - 1) + x) / n
        series.append(atr)
    pct = atr / rows[-1]["close"] * 100
    word = None
    if len(series) > back and series[-1 - back]:
        ratio = atr / series[-1 - back]
        word = "변동성 커지는 중" if ratio >= 1.15 else "변동성 줄어드는 중" if ratio <= 0.85 else "변동성 비슷함"
    return {"atr": atr, "pct": pct, "label": f"{P(atr)} ({pct:.2f}%)", "word": word,
            "text": f"ATR({n}) {P(atr)}{U} · 가격의 {pct:.2f}%" + (f" · {word}" if word else "")}


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


def analyze(rows, a, show, tf="1d"):
    """화면에 보일 마지막 show 개 봉 기준으로 고점·저점·피보나치·이평선·지지선·추세선을 계산한다."""
    n = len(rows)
    closes = [r["close"] for r in rows]
    mas = {p: sma(closes, p) for p, _ in MA}
    v0 = max(0, n - show)
    view = range(v0, n)
    P = lambda p: fmt_price(p, a)
    U = a["unit"]
    md = lambda i: rows[i]["d"]
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
    m20, m240 = (ma_now[p] for p, _ in MA)
    if m240 and close > m20 > m240:
        order = "정배열"
    elif m240 and close < m20 < m240:
        order = "역배열"
    else:
        order = "섞여 있음"
    cross = None
    if m240:
        sign = lambda i: (mas[20][i] or 0) > (mas[240][i] or 0)
        for i in range(n - 1, max(n - 400, 240), -1):
            if mas[240][i - 1] is not None and sign(i) != sign(i - 1):
                cross = {"kind": "골든크로스" if sign(i) else "데드크로스", "date": md(i)}
                break
    if close < m20 and (m240 is None or m20 < m240):
        trend, tcolor = "하락추세", "#ef5350"
    elif close > m20 and (m240 is None or m20 > m240):
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
    # 1년(코인 365일, 주식 252일, 주봉 52주) 고저 — 분봉은 화면 구간
    yr = rows[v0:] if tf in INTRADAY else rows[-(52 if tf == "1w" else 365 if a["kind"] == "coin" else 252):]
    y_hi, y_lo = max(r["high"] for r in yr), min(r["low"] for r in yr)
    return {"rows": rows, "mas": mas, "v0": v0, "n": n, "P": P, "U": U, "md": md, "tf": tf, "ind": indicators(rows, tf, P) if tf in SCALP else None, "ha": ha_of(rows), "atr": atr_of(rows, P, U),
            "ma_nm": lambda p: f"{p}일선" if tf == "1d" else f"{p}주선" if tf == "1w" else f"{p}이평",
            "chg_word": "하루" if tf == "1d" else "이번 주" if tf == "1w" else "직전 봉 대비", "y_word": "구간" if tf in INTRADAY else "1년",
            "date": last["day"], "close": close, "chg": chg, "open": last["open"], "high": last["high"], "low": last["low"],
            "hi": {"i": hi_i, "price": hi, "date": md(hi_i), "label": P(hi)}, "lo": {"i": lo_i, "price": lo, "date": md(lo_i), "label": P(lo)},
            "drop": (lo / hi - 1) * 100, "rise": (hi / lo - 1) * 100, "fib": fib, "zone": zone, "zone_short": zone_short, "sup": below[:2], "res": above[-2:][::-1] if above else [],
            "ma": ma_txt, "order": order, "cross": cross, "trend": trend, "tcolor": tcolor, "swing": swing,
            "hsup": hsup, "hres": hres, "rsup": rsup, "tline": tline, "y_hi": y_hi, "y_lo": y_lo}


def facts_of(f, a):
    """본문용 사실 목록 — 단위까지 붙인 글자로 (Claude 는 이 숫자만 쓴다)."""
    P, U = f["P"], f["U"]
    ma = {f["ma_nm"](p): (f"{f['ma'][p]['label']}{U} ({f['px']}가 {f['ma'][p]['pos']}, 차이 {f['ma'][p]['gap_pct']:+.1f}%)" if f["ma"][p] else "데이터 부족")
          for p, _ in MA}
    return {
        "종목": a["name"], "봉": TF[f["tf"]]["name"], "기준일": f["date"], "시세 기준": f["basis"], f"{f['px']}({f['live']['label']})": f"{P(f['close'])}{U}", f"{f['chg_word']} 등락": f"{f['chg']:+.2f}%",
        **({f["live"]["ext"]["label"]: f"{P(f['live']['ext']['price'])}{U} (종가 대비 {f['live']['ext']['chg']:+.2f}%)"} if f["live"]["ext"] else {}),
        "차트 구간 고점": f"{f['hi']['label']}{U} ({f['hi']['date']})", "차트 구간 저점": f"{f['lo']['label']}{U} ({f['lo']['date']})",
        **({"고점→저점 낙폭": f"{f['drop']:.0f}%"} if f["lo"]["i"] > f["hi"]["i"] else {"저점→고점 상승폭": f"+{f['rise']:.0f}%"}),
        "피보나치(고점 0 → 저점 1.0)": [x["label"] for x in f["fib"]], "지금 위치": f["zone"],
        "아래 피보 지지": [x["label"] for x in f["sup"]], "위 피보 저항": [x["label"] for x in f["res"]],
        "이동평균선": ma, "이평 배열": f["order"], f"최근 {f['ma_nm'](20)}·{f['ma_nm'](240)} 교차": f"{f['cross']['kind']} ({f['cross']['date']})" if f["cross"] else "없음",
        f"추세 판단({f['px']}·{f['ma_nm'](20)}·{f['ma_nm'](240)} 위치)": f["trend"], "하이킨아시": f["ha"]["word"],
        **({"ATR(14, 이 봉 기준 평균 진폭)": f["atr"]["text"]} if f["atr"] else {}),
        "되돌림": f"{f['swing']['kind']} {P(f['swing']['price'])}{U} ({f['swing']['date']})" if f["swing"] else "없음",
        "수평 지지": f"{f['hsup']['label']}{U} (최근 120봉 저점 {f['hsup']['touch']}번 모임)" if f["hsup"] else "없음",
        "심리적 지지(딱 떨어지는 가격)": f"{f['rsup']['label']}{U} 수평선 (최근 저점 {f['rsup']['low']}{U}, {f['rsup']['date']})" if f["rsup"] else "없음",
        "수평 저항": f"{f['hres']['label']}{U} (최근 120봉 고점 {f['hres']['touch']}번 모임)" if f["hres"] else "없음",
        "추세선": f"{f['tline']['kind']} 추세선 {f['tline']['label']}, 지금 위치 {P(f['tline']['now'])}{U}" if f["tline"] else "없음",
        f"{f['y_word']} 고점": f"{P(f['y_hi'])}{U}", f"{f['y_word']} 저점": f"{P(f['y_lo'])}{U}",
        **({"RSI(14)": f"{f['ind']['rsi_now']:.1f} ({f['ind']['rsi_word']})",
            "볼린저밴드(20, 2)": f"상단 {f['ind']['up_label']}{U}, 하단 {f['ind']['lo_label']}{U}, 위치 {f['ind']['bb_word']}" + (", 밴드 좁음" if f["ind"]["squeeze"] else ""),
            "거래량": f"완성된 마지막 봉이 20봉 평균의 {f['ind']['vol']:.1f}배 ({f['ind']['vol_word']})" if f["ind"]["vol"] is not None else "데이터 없음"} if f["ind"] else {}),
    }


# ── 그림 ──
def spec_of(f, a, mode):
    """트레이딩뷰에 직접 그어 캡처한 화면처럼: 위 범례 + 얇은 선 + 값만 적은 글자 + 거래량. 상자·화살표·요약 패널은 없음."""
    rows, v0, P, U = f["rows"], f["v0"], f["P"], f["U"]
    pc = mode == "pc"
    cut = v0 if pc else max(v0, f["n"] - 160)
    heikin = f["tf"] not in SCALP   # 추세를 보는 봉은 하이킨아시, 단타 봉(1·15분)은 실제 캔들
    candles = (f["ha"]["rows"] if heikin else [{k: r[k] for k in ("time", "open", "high", "low", "close")} for r in rows])[cut:]
    volume = [{"time": r["time"], "value": r["volume"], "color": "rgba(8,153,129,.32)" if r["close"] >= r["open"] else "rgba(242,54,69,.32)"} for r in rows[cut:]]
    mas = [{"color": c, "data": [{"time": rows[i]["time"], "value": f["mas"][p][i]} for i in range(cut, f["n"]) if f["mas"][p][i] is not None]}
           for p, c in MA]
    vis = lambda i: i >= cut
    notes, hlines, tlines = [], [], []
    hi, lo, t = f["hi"], f["lo"], f["tline"]
    if vis(hi["i"]):
        notes.append({"time": rows[hi["i"]]["time"], "price": hi["price"], "side": "high", "text": f"{hi['label']} ({hi['date']})"})
    if vis(lo["i"]):
        notes.append({"time": rows[lo["i"]]["time"], "price": lo["price"], "side": "low", "text": f"{lo['label']} ({lo['date']})"})
    if t and vis(t["i1"]):
        tlines.append({"t1": rows[t["i1"]]["time"], "p1": t["p1"], "t2": rows[-1]["time"], "p2": t["now"], "color": "#d1d4dc"})
    SUP, RES = "#3fa796", "#d9625f"
    if f["rsup"]:
        hlines.append({"price": f["rsup"]["price"], "color": SUP})
        notes.append({"price": f["rsup"]["price"], "color": SUP, "text": f"지지 {f['rsup']['label']}"})
    if f["hsup"]:
        hlines.append({"price": f["hsup"]["price"], "color": SUP})
        notes.append({"price": f["hsup"]["price"], "color": SUP, "text": f"지지 {f['hsup']['label']}"})
    if f["hres"]:
        hlines.append({"price": f["hres"]["price"], "color": RES})
        notes.append({"price": f["hres"]["price"], "color": RES, "text": f"저항 {f['hres']['label']}"})
    first = max(cut, min(hi["i"], lo["i"]))
    fib = {"from": rows[first]["time"], "levels": [{"r": x["r"], "price": x["price"], "color": x["color"], "label": f"{x['name']}  {P(x['price'])}"} for x in f["fib"]],
           **({"a": {"t": rows[hi["i"]]["time"], "p": hi["price"]}, "b": {"t": rows[lo["i"]]["time"], "p": lo["price"]}} if vis(hi["i"]) and vis(lo["i"]) else {})}

    up_cls = "up" if f["chg"] >= 0 else "dn"
    sym = a["name"] if a["kind"] != "us" else a["symbol"]
    tf = TF[f["tf"]]
    ext = f["live"]["ext"]
    legend = (f"<b>{sym}</b> · {tf['short']}{' · 하이킨아시' if heikin else ''} · {a.get('exchange') or ''} &nbsp; 시 {P(f['open'])} 고 {P(f['high'])} 저 {P(f['low'])} "
              f"{f['px'][0]} <span class='{up_cls}'>{P(f['close'])} ({f['chg']:+.2f}%)</span>"
              + (f" &nbsp; {ext['label']} {P(ext['price'])} ({ext['chg']:+.2f}%)" if ext else "") + "<br>"
              + "".join(f"<span class='ma' style='color:{c}'>MA{p} {f['ma'][p]['label'] if f['ma'][p] else '-'}</span>" for p, c in MA)
              + (f"<span class='ma'>ATR14 {f['atr']['label']}</span>" if f["atr"] else "")
              + f"<span class='ma'>{f['ha']['word'].replace('하이킨아시 ', 'HA ').split(' · ')[0]}</span>")
    read = []
    if f["sup"]:
        read.append(f"아래 {P(f['sup'][0]['price'])}")
    if f["res"]:
        read.append(f"위 {P(f['res'][0]['price'])}")
    if t:
        read.append(f"{t['kind']} 추세선 {P(t['now'])}")
    read.append(f["order"] if f["order"] != "섞여 있음" else f["trend"])
    if f["ind"]:
        x = f["ind"]
        read = [f"RSI {x['rsi_now']:.1f}", f"볼밴 {x['bb_word']}"] + ([f"거래량 {x['vol']:.1f}배"] if x["vol"] is not None else []) + read[:2]
    credit = f"{a['src']} · {f['basis'].split(' · 시간외')[0].split(' · 프리마켓')[0]}{' · 캔들은 하이킨아시, 표시 가격은 실제 시세' if heikin else ''} · TradingView Lightweight Charts™ · 투자 판단은 본인 몫"
    if pc:
        layout = {"W": 1280, "H": 720, "chartH": 692, "legendH": 50, "top": .09, "rightOffset": max(18, round(len(candles) * 0.09)), "axisFont": 11, "markFont": 92,
                  "vars": {"--lg": "13px", "--nt": "12px", "--fb": "11px", "--ft": "13px", "--cr": "10.5px"}}
    else:
        layout = {"W": 720, "H": 900, "chartH": 846, "legendH": 54, "top": .07, "rightOffset": 16, "axisFont": 12, "markFont": 64,
                  "vars": {"--lg": "13px", "--nt": "13px", "--fb": "12px", "--ft": "15px", "--cr": "10.5px"}}
    extra = {}
    if f["ind"]:
        x = f["ind"]
        line = lambda k: [{"time": rows[i]["time"], "value": x[k][i]} for i in range(cut, f["n"]) if x[k][i] is not None]
        extra = {"bb": [line("up"), line("lo")], "rsi": line("rsi"), "rsi_label": f"RSI(14) {x['rsi_now']:.1f}"}
        layout.update({"top": .1, "bottom": .32, "oiTop": .70, "oiBottom": .83, "volTop": .86})
    return {**extra, "layout": layout, "krw": U == "원", "intraday": f["tf"] in INTRADAY, "candles": candles, "volume": volume, "mas": mas, "fib": fib,
            "hlines": hlines, "tlines": tlines, "notes": notes, "legend": legend, "heikin": heikin, "last": f["close"], "mark": f"{sym}, {tf['short']}", "read": " · ".join(read), "credit": credit}


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
    m20 = f["ma_nm"](20)
    pos = {"하락추세": f"{m20} 아래에서 내려오는 중", "상승추세": f"{m20} 위에서 올라가는 중",
           "방향 탐색": "이평선 사이에서 방향을 고르는 중"}[f["trend"]]
    s1 = f["sup"][0] if f["sup"] else None
    s2 = f["sup"][1] if len(f["sup"]) > 1 else None
    r1 = f["res"][0] if f["res"] else None
    lines = ["차트리포트 입니다 ^^", f"{a['name']} {TF[f['tf']]['name']} 체크", "", " 지금 위치", pos,
             f"{f['px']} {P(f['close'])}{U} ({f['chg_word']} {f['chg']:+.2f}%)", f"피보나치로는 {f['zone']}", f["ha"]["word"], *([f["atr"]["text"]] if f["atr"] else []), *([ind_line(f)] if f["ind"] else []), "", " 볼 자리"]
    if s1:
        lines.append(f"· 아래: {s1['label']}" + (" (기간 저점)" if s1["r"] == 1 else ""))
    if f["rsup"]:
        lines.append(f"· {f['rsup']['label']}{U} 수평선: {f['rsup']['date']} 저점 {f['rsup']['low']}이 닿은 자리")
    if f["hsup"]:
        lines.append(f"· 수평 지지: {f['hsup']['label']} (최근 저점이 {f['hsup']['touch']}번 모인 자리)")
    if r1:
        lines.append(f"· 위: {r1['label']}")
    if f["ma"][20]:
        lines.append(f"· {m20}: {f['ma'][20]['label']}")
    lines += ["", " 시나리오"]
    # 시나리오는 종가에서 가장 가까운 지지·저항으로 (피보·수평선·20일선 중)
    sups = sorted([(x["price"], P(x["price"])) for x in f["sup"]] +
                  [(x["price"], x["label"]) for x in (f["rsup"], f["hsup"]) if x], reverse=True)
    ress = sorted([(x["price"], P(x["price"])) for x in f["res"]] +
                  ([(f["ma"][20]["price"], f"{m20} {f['ma'][20]['label']}")] if f["ma"][20] and f["ma"][20]["gap"] < 0 else []))
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
(종목) (자료의 봉 이름) 체크

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
- 추세는 20선·240선과 하이킨아시로 설명합니다. 자료의 하이킨아시와 ATR을 지금 위치에 함께 씁니다.
- 자료에 RSI·볼린저밴드·거래량이 있으면 지금 위치에 함께 쓰고, 볼 자리에 볼린저 상단·하단을 넣습니다.
- 이평선 이름과 등락 표현은 자료에 적힌 그대로 씁니다 (20일선·20주선·20이평, 하루·이번 주·직전 봉 대비).
- 자료에 '현재가'가 아니라 '종가'로 나와 있으면 장이 닫힌 상태이니 '현재가 (값)' 줄을 '종가 (값)'로 씁니다. 시세 기준 시각은 쓰지 않습니다 (따로 넣습니다). 프리마켓·시간외 값은 자료에 있을 때만 씁니다.
- 본문만 출력합니다."""


NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
BANNED = ("아니라", "아닌,", "첫째", "둘째", "결론적으로", "핵심은", "주목할", "매수", "매도", "목표가")


def check_text(text, facts):
    """계산에 없는 숫자·금지 표현이 있으면 그 목록을 돌려준다."""
    allowed = {x.replace(",", "") for x in NUM.findall(json.dumps(facts, ensure_ascii=False))}
    allowed |= {str(i) for i in range(0, 11)} | {"20", "240"}
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


def with_basis(text, f):
    """제목 줄 아래에 시세 기준을 넣는다 (언제 값인지 글만 봐도 알게)."""
    lines = text.split("\n")
    i = next((i for i, x in enumerate(lines) if "봉" in x), 0)
    lines.insert(i + 1, f"시세 기준: {f['basis']}")
    return "\n".join(lines)


SCALP_SYSTEM = """텔레그램 채널 '차트보는 말희아빠'의 단타 체크 글 끝에 붙일 코멘트를 씁니다.
규칙:
- 차분한 존댓말로 한두 줄, 합쳐서 80자 안팎. 이모지를 쓰지 않습니다.
- 숫자는 '자료'에 있는 값만 그대로 씁니다. 지어내거나 새로 계산하지 않습니다.
- 15분봉 방향과 1분봉 RSI·볼린저·거래량이 맞는지, 무엇을 보면 판단이 바뀌는지만 씁니다.
- 진입 지시, 레버리지 배수, 목표 수익률, '지금 사라/팔아라' 같은 표현을 쓰지 않습니다.
- '~가 아니라 ~다' 뒤집기, '핵심은', '결론적으로', '주목할' 같은 AI 말투를 쓰지 않습니다.
- 코멘트만 출력합니다."""


def scalp_levels(f15, f1):
    """15분봉 자리 + 1분봉 볼린저밴드를 지금 가격 아래·위로 가까운 순서대로 (1분봉 평균 변동폭보다 가까운 자리는 뺌)."""
    pts = [(x["price"], f"15분 피보 {x['name']}") for x in f15["fib"]]
    pts += [(f15["ind"]["up_now"], "15분 볼밴 상단"), (f15["ind"]["lo_now"], "15분 볼밴 하단"), (f1["ind"]["up_now"], "1분 볼밴 상단"), (f1["ind"]["lo_now"], "1분 볼밴 하단")]
    pts += [(f15[k]["price"], "15분 수평선") for k in ("hsup", "rsup", "hres") if f15[k]]
    if f15["ma"][20]:
        pts.append((f15["ma"][20]["price"], "15분 20이평"))
    if f15["tline"]:
        pts.append((f15["tline"]["now"], "15분 추세선"))
    now = f1["close"]
    r = f1["rows"][-15:]
    atr = sum(max(b["high"] - b["low"], abs(b["high"] - a["close"]), abs(b["low"] - a["close"])) for a, b in zip(r, r[1:])) / 14

    def pick(side):
        out = []
        for p in sorted((p for p in pts if side * (p[0] - now) >= atr), key=lambda p: abs(p[0] - now)):
            if not out or abs(p[0] - out[-1][0]) >= atr:
                out.append(p)
        return out
    return pick(-1), pick(1)


def scalp_text(a, f15, f1, comment=None):
    P, U = f15["P"], f15["U"]
    lab = lambda p: f"{P(p[0])}({p[1]})"
    sups, ress = scalp_levels(f15, f1)
    same = f15["trend"] == f1["trend"]
    lines = ["차트리포트 입니다 ^^", f"{a['name']} 단타 체크 · 15분봉 / 1분봉", "", " 지금 위치", f"{f1['px']} {P(f1['close'])}{U}",
             f"15분봉 {f15['trend']} · 1분봉 {f1['trend']}" + ("" if same else " (서로 어긋남)"),
             "", " 15분봉", f15["ha"]["word"], *([f15["atr"]["text"]] if f15["atr"] else []), ind_line(f15),
             "", " 1분봉", f1["ha"]["word"], *([f1["atr"]["text"]] if f1["atr"] else []), ind_line(f1), "", " 볼 자리"]
    lines += [f"· 아래: {' / '.join(lab(p) for p in sups[:2])}"] if sups else []
    lines += [f"· 위: {' / '.join(lab(p) for p in ress[:2])}"] if ress else []
    lines += ["", " 시나리오"]
    if sups and ress:
        lines += [f"A. {lab(sups[0])} 지키면 → {lab(ress[0])} 확인", f"B. {lab(sups[0])} 깨면 → " + (f"{lab(sups[1])}에서 받는지 확인" if len(sups) > 1 else "새 저점 만드는지 확인")]
    else:
        lines += ["가까운 자리가 뚜렷하지 않아 새 자리가 잡힐 때까지 확인"]
    lines += [*(["", comment] if comment else []), "", "투자 판단은 본인 몫입니다."]
    return "\n".join(lines)


def scalp_comment(text):
    import llm
    if not llm.ready():
        return None
    try:
        r = llm.Anthropic().messages.create(model=MODEL, max_tokens=500, system=SCALP_SYSTEM, messages=[{"role": "user", "content": "자료:\n" + text}], output_config={"effort": "low"})
        c = r.content[0].text.strip().strip("`").strip()
    except (llm.APIStatusError, llm.APIConnectionError) as e:
        print("⚠️ Claude 코멘트 실패 — 코멘트 없이 보내요:", str(e)[:200])
        return None
    if check_text(c, {"자료": text}) or any(w in c for w in ("진입하", "레버리지", "사세요", "파세요", "수익률")) or len(c) > 200:
        print("⚠️ Claude 코멘트에 없는 숫자·금지 표현 — 코멘트 없이 보내요:", c[:120])
        return None
    return c


def make_scalp(query, use_ai=True):
    """단타: 15분봉·1분봉 이미지 두 장 + 한 글."""
    a = resolve(query)
    frames, files, web = {}, {}, {}
    s = slug(a)
    RAW.mkdir(parents=True, exist_ok=True)
    WEB.mkdir(parents=True, exist_ok=True)
    for tf, key in (("15m", ""), ("1m", "2")):
        rows = fetch(a, tf)
        f = analyze(rows, a, TF[tf]["show"], tf)
        apply_live(f, a, live_of(a, rows, tf))
        frames[tf] = f
        for mode, scale, width, name in (("pc", 1.5, 1600, "pc"), ("m", 1.5, 1080, "mobile")):
            png = RAW / f"{s}_{tf}_{mode}.png"
            png.unlink(missing_ok=True)
            render(spec_of(f, a, "pc" if mode == "pc" else "mobile"), png, scale)
            to_jpg(png, WEB / f"{s}_{tf}_{mode}.jpg", width)
            files[mode + key] = png
            web[name + key] = f"charts/{s}_{tf}_{mode}.jpg"
    f15, f1 = frames["15m"], frames["1m"]
    text = scalp_text(a, f15, f1)
    comment = scalp_comment(text) if use_ai else None
    if comment:
        text = scalp_text(a, f15, f1, comment)
    text = with_basis(text, f1)
    item = {"query": query, "tf": "scalp", "tf_name": "단타 15분+1분", "name": a["name"], "symbol": a["symbol"], "kind": a["kind"], "date": f1["date"], "basis": f1["basis"], "px": f1["px"],
            "close": f"{f1['P'](f1['close'])}{f1['U']}", "chg": round(f1["chg"], 2), "trend": f15["trend"], **web, "text": text, "text_by": "claude" if comment else "template",
            "made_at": datetime.now(KST).isoformat(timespec="seconds")}
    return item, files


def make(query, use_ai=True, style="", tf="1d"):
    query, _, at = query.partition("@")   # '테슬라@4h' 처럼 종목마다 봉을 붙일 수 있음
    tf = at.strip() or tf
    if tf == "scalp":
        return make_scalp(query, use_ai)
    if tf not in TF:
        raise SystemExit(f"봉 종류 '{tf}' 를 모르겠어요 ({', '.join(TF)} 중 하나).")
    a = resolve(query)
    rows = fetch(a, tf)
    f = analyze(rows, a, TF[tf]["show"] or (365 if a["kind"] == "coin" else 260), tf)
    apply_live(f, a, live_of(a, rows, tf))
    RAW.mkdir(parents=True, exist_ok=True)
    WEB.mkdir(parents=True, exist_ok=True)
    s = slug(a) + ("" if tf == "1d" else f"_{tf}")
    files = {}
    for mode, scale, width in (("pc", 1.5, 1600), ("m", 1.5, 1080)):
        png = RAW / f"{s}_{mode}.png"
        png.unlink(missing_ok=True)
        render(spec_of(f, a, "pc" if mode == "pc" else "mobile"), png, scale)
        to_jpg(png, WEB / f"{s}_{mode}.jpg", width)
        files[mode] = png
    text, by = write_text(f, a, use_ai, style)
    text = with_basis(text, f)
    item = {"query": query, "tf": tf, "tf_name": TF[tf]["name"], "name": a["name"], "symbol": a["symbol"], "kind": a["kind"], "date": f["date"], "basis": f["basis"], "px": f["px"],
            "close": f"{f['P'](f['close'])}{f['U']}", "chg": round(f["chg"], 2), "trend": f["trend"],
            "pc": f"charts/{s}_pc.jpg", "mobile": f"charts/{s}_m.jpg", "text": text, "text_by": by,
            "made_at": datetime.now(KST).isoformat(timespec="seconds")}
    return item, files


def load_reports():
    return json.loads(REPORTS.read_text(encoding="utf-8")) if REPORTS.exists() else {"items": []}


def save_reports(d, new):
    # 종목·봉당 최신 1개만 (이미지 파일을 종목별로 덮어쓰니 옛 카드를 두면 글과 그림이 어긋남). 어느 칸에 쓰였는지는 slots 로 이어 받는다
    items = []
    for x in new + d["items"]:
        same = next((y for y in items if y["symbol"] == x["symbol"] and y.get("tf", "1d") == x.get("tf", "1d")), None)
        slots = [s for s in [x.get("slot"), *x.get("slots", [])] if s]
        if same:
            same["slots"] = list(dict.fromkeys(same["slots"] + slots))[:10]
        else:
            items.append({**x, "slots": list(dict.fromkeys(slots))})
    d["items"] = items[:12]
    d["updated_at"] = datetime.now(KST).isoformat(timespec="seconds")
    REPORTS.parent.mkdir(parents=True, exist_ok=True)
    REPORTS.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    used = {Path(x[k]).name for x in d["items"] for k in ("pc", "mobile", "pc2", "mobile2") if x.get(k)}
    for p in WEB.glob("*.jpg"):   # 목록에서 빠진 그림은 지움 (저장소가 커지지 않게)
        if p.name not in used:
            p.unlink()


def send(item, files):
    """PC·모바일 이미지 두 장을 먼저, 그 아래에 설명 글(그대로 복사해 올릴 본문)을 따로 보낸다."""
    from publish.notify import send as send_text, send_photos
    ok = send_photos([files[k] for k in ("pc", "pc2", "m", "m2") if k in files], f"📈 {item['name']} {item['tf_name']} 분석 · {item['px']} {item['close']} · {item['basis']} (PC용·모바일용)")
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


def from_tg(use_ai, notify=True, force=False, tf="1d"):
    """오늘 문구의 차트 글 중 다음 차례(지금 이후 가장 가까운 칸) 하나를 만든다. 매일 08시 자동 + 수동 버튼."""
    p = SITE / "tg_ai.json"
    ai = json.loads(p.read_text(encoding="utf-8") or "{}") if p.exists() else {}
    posts = chart_posts(ai)
    now = datetime.now(KST).strftime("%H:%M")
    hhmm = lambda t: (re.match(r"\d{1,2}:\d{2}", t.get("time", "")) or [""])[0].zfill(5)
    nxt = [x for x in posts if hhmm(x[0]) >= now]
    t, q = nxt[0] if nxt else posts[-1] if posts else ({"time": now, "type": "차트리포트"}, "비트코인")
    d = load_reports()
    slot = f"{ai.get('analyzed_at', '')}|{t['time']}"
    if not force and slot in ({s for x in d["items"] for s in x.get("slots", [])} | set(d.get("failed", []))):
        return print(f"이번 차트 글({t['time']} {q})은 이미 만들었어요.")
    mine = SITE / "tg_mine.json"
    style = "\n---\n".join(m["text"][:300] for m in json.loads(mine.read_text(encoding="utf-8"))[:5]) if mine.exists() else ""
    try:
        item, files = make(q, use_ai, style, tf)
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
    ap.add_argument("--tf", default="1d", choices=[*TF, "scalp"], help="봉 종류 (종목마다 '테슬라@4h' 로 붙여도 됨)")
    ap.add_argument("--no-ai", action="store_true", help="Claude 없이 정해진 문장으로 본문")
    ap.add_argument("--no-send", action="store_true", help="--from-tg 때 봇으로 보내지 않음 (시험용)")
    ap.add_argument("--force", action="store_true", help="--from-tg 때 이미 만든 칸이어도 다시 (수동 버튼)")
    ap.add_argument("--no-save", action="store_true", help="사이트 목록(chart_reports.json)에 넣지 않음")
    args = ap.parse_args()
    load_env()
    if args.from_tg:
        return from_tg(not args.no_ai, not args.no_send, args.force, args.tf)
    if not args.symbols:
        ap.error("종목을 넣거나 --from-tg 를 쓰세요")
    d, new = load_reports(), []
    qs = [q.strip() for x in args.symbols for q in re.split(r"[,\n]", x) if q.strip()]
    for q in qs[:5]:
        try:
            item, files = make(q, not args.no_ai, tf=args.tf)
        except (SystemExit, requests.RequestException, KeyError, ValueError, IndexError) as e:
            msg = f"'{q}' 차트를 못 만들었어요: {e}"
            print("⚠️", msg)
            if args.send:
                from publish.notify import send as send_text
                send_text(msg + "\n티커(TSLA)·종목명(삼성전자)·6자리 코드(005930)·코인 이름(이더리움)으로 다시 넣어 주세요.")
            continue
        print(f"\n✅ {item['name']} {item['tf_name']} · {item['px']} {item['close']} ({item['chg']:+.2f}%) · {item['basis']} · {item['trend']}")
        print(f"   PC {files['pc']}\n   모바일 {files['m']}\n   본문({item['text_by']}):\n" + item["text"])
        if args.send:
            item["sent"] = send(item, files)
        new.append(item)
    if not args.no_save:
        save_reports(d, new)


if __name__ == "__main__":
    sys.exit(main())
