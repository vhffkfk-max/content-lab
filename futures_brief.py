#!/usr/bin/env python3
"""비트코인·이더리움 선물 브리핑 — 바이낸스 USDT 무기한 시세로 4시간봉·1시간봉을 작도하고 펀딩·미결제약정·롱숏 비율과 시나리오 글을 만든다.

    python futures_brief.py --send       # 만들고 봇으로 보냄 (PC가 매일 08:30·21시, 사이트 '선물 브리핑 만들기' 버튼)
    python futures_brief.py --no-ai --no-save   # 시험: Claude·사이트 저장 없이 이미지와 글만
"""
import argparse
import json
import sys
from datetime import datetime

import requests

from common import OUTPUT_DIR, load_env
import chart_report as cr

KST = cr.KST
API = "https://fapi.binance.com"
COINS = (("BTC", "BTC 선물"), ("ETH", "ETH 선물"))
FRAMES = (("4h", 14400, 180), ("1h", 3600, 220))   # 봉, 초, 화면에 보일 봉 수 (미결제약정 내역이 30일까지라 4시간봉은 30일치)
SITE = OUTPUT_DIR / "site"
WEB = SITE / "futures"                # 사이트용 JPG (커밋)
RAW = OUTPUT_DIR / "charts"           # 봇으로 보낼 원본 PNG (커밋 안 함)
REPORT = SITE / "futures_brief.json"


def get(path, **params):
    r = requests.get(API + path, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def stats_of(symbol):
    """펀딩·OI·롱숏 — 일부를 못 받아도 나머지로 글을 쓴다 (못 받은 값은 None)."""
    s = symbol + "USDT"

    def safe(fn):
        try:
            return fn()
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError, ZeroDivisionError) as e:
            print(f"⚠️ {symbol} 선물 수치 일부 실패:", str(e)[:100])
            return None
    oi = safe(lambda: get("/futures/data/openInterestHist", symbol=s, period="1h", limit=25))
    taker = safe(lambda: get("/futures/data/takerlongshortRatio", symbol=s, period="1h", limit=24))
    return {
        "chg24": safe(lambda: float(get("/fapi/v1/ticker/24hr", symbol=s)["priceChangePercent"])),
        "funding": safe(lambda: float(get("/fapi/v1/premiumIndex", symbol=s)["lastFundingRate"]) * 100),
        "oi_chg": safe(lambda: (float(oi[-1]["sumOpenInterest"]) / float(oi[0]["sumOpenInterest"]) - 1) * 100),
        "oi_usd": safe(lambda: float(oi[-1]["sumOpenInterestValue"])),
        "long": safe(lambda: float(get("/futures/data/globalLongShortAccountRatio", symbol=s, period="1h", limit=1)[-1]["longAccount"]) * 100),
        "top_long": safe(lambda: float(get("/futures/data/topLongShortAccountRatio", symbol=s, period="1h", limit=1)[-1]["longAccount"]) * 100),
        "taker": safe(lambda: sum(float(x["buyVol"]) for x in taker) / sum(float(x["sellVol"]) for x in taker)),
    }


def read_position(st):
    """수치 해석 — 단정하지 않고 '쪽'으로만."""
    out = []
    if st["chg24"] is not None and st["oi_chg"] is not None:
        up, oi = st["chg24"], st["oi_chg"]
        if abs(oi) < 0.3:
            out.append("OI 변화가 작아 포지션이 크게 움직이지는 않았습니다.")
        elif up >= 0:
            out.append("가격이 오르며 OI도 늘어 새 롱이 들어오는 쪽으로 읽힙니다." if oi > 0 else "가격은 오르는데 OI가 줄어 숏 정리 쪽으로 읽힙니다.")
        else:
            out.append("가격이 내리며 OI가 늘어 새 숏이 들어오는 쪽으로 읽힙니다." if oi > 0 else "가격이 내리며 OI도 줄어 롱 정리 쪽으로 읽힙니다.")
    if st["funding"] is not None:
        if st["funding"] >= 0.03:
            out.append("펀딩이 높아 롱 쪽이 뜨거운 편입니다.")
        elif st["funding"] < 0:
            out.append("펀딩이 마이너스라 숏 쪽 비용이 더 드는 상황입니다.")
    if st["long"] is not None and st["long"] >= 65:
        out.append("계정 수로는 롱에 쏠려 있습니다.")
    return out


def levels_of(frames):
    """4시간봉·1시간봉의 피보·수평선·20이평·추세선을 모아 지금 가격 아래·위로 가까운 순서대로."""
    pts = []
    for tf, f in frames.items():
        for x in f["fib"]:
            if 0 < x["r"] < 1:
                pts.append((x["price"], f"{tf} 피보 {x['name']}"))
            elif tf == "4h":
                pts.append((x["price"], "4h 고점" if x["r"] == 0 else "4h 저점"))
        for key, name in (("hsup", "수평선"), ("rsup", "수평선"), ("hres", "수평선")):
            if f[key]:
                pts.append((f[key]["price"], f"{tf} {name}"))
        if f["ma"][20]:
            pts.append((f["ma"][20]["price"], f"{tf} 20이평"))
        if f["tline"]:
            pts.append((f["tline"]["now"], f"{tf} 추세선"))
    now = frames["4h"]["close"]
    # 간격 기준: 1시간봉 평균 변동폭(14봉). 이보다 가까운 자리는 시나리오로 쓰기엔 흔들림 안에 있음
    r1 = frames["1h"]["rows"][-15:]
    atr = sum(max(b["high"] - b["low"], abs(b["high"] - a["close"]), abs(b["low"] - a["close"])) for a, b in zip(r1, r1[1:])) / 14

    def pick(side):
        side_pts = sorted((p for p in pts if side * (p[0] - now) >= atr), key=lambda p: abs(p[0] - now))
        out = []
        for p in side_pts:
            if not out or abs(p[0] - out[-1][0]) >= atr:   # 붙어 있는 자리는 하나로
                out.append(p)
        return out
    return pick(-1), pick(1)


def brief_text(a, frames, st, comment=None):
    f4, f1 = frames["4h"], frames["1h"]
    P, U = f4["P"], f4["U"]
    lab = lambda p: f"{P(p[0])}({p[1]})"
    bar_of = lambda p: "1시간봉" if p[1].startswith("1h") else "4시간봉"
    then = lambda xs: f" → 다음 {lab(xs[1])}" if len(xs) > 1 else ""
    sups, ress = levels_of(frames)
    now = f4["live"]["at"].strftime("%m/%d %H:%M")
    head = f"현재가 {P(f4['close'])}{U}" + (f" (24시간 {st['chg24']:+.2f}%)" if st["chg24"] is not None else "")
    same = f4["trend"] == f1["trend"]
    pos1 = []
    if st["funding"] is not None:
        pos1.append(f"펀딩 {st['funding']:+.3f}%")
    if st["oi_chg"] is not None:
        pos1.append(f"OI 24시간 {st['oi_chg']:+.1f}%")
    if st["long"] is not None:
        pos1.append(f"전체 롱 {st['long']:.0f}%")
    pos2 = []
    if st["top_long"] is not None:
        pos2.append(f"상위 계정 롱 {st['top_long']:.0f}%")
    if st["taker"] is not None:
        pos2.append(f"테이커 비율 {st['taker']:.2f}")
    lines = [f"{a['symbol']} 선물 체크 · 4시간봉 / 1시간봉", f"시세 기준: {now} · 바이낸스 무기한", "", " 지금 위치", head,
             f"4시간봉 {f4['trend']} · 1시간봉 {f1['trend']}" + ("" if same else " (서로 어긋남)"),
             f"4시간봉 {f4['ha']['word']}", *([f"4시간봉 {f4['atr']['text']}"] if f4["atr"] else []),
             f"1시간봉 {f1['ha']['word']}", *([f"1시간봉 {f1['atr']['text']}"] if f1["atr"] else []), "", " 포지션 상황"]
    lines += [" · ".join(x) for x in (pos1, pos2) if x] + read_position(st)
    lines += ["", " 롱 시나리오"]
    if sups and ress:
        lines += [f"{lab(sups[0])} 지지 확인 → {lab(ress[0])} 확인{then(ress)}", f"무효화: {P(sups[0][0])} {bar_of(sups[0])} 종가 이탈"]
    else:
        lines += ["가까운 지지·저항이 뚜렷하지 않아 새 자리가 잡힐 때까지 확인"]
    lines += ["", " 숏 시나리오"]
    if sups and ress:
        lines += [f"{lab(ress[0])} 저항 실패 → {lab(sups[0])} 확인{then(sups)}", f"무효화: {P(ress[0][0])} {bar_of(ress[0])} 종가 돌파"]
    else:
        lines += ["가까운 지지·저항이 뚜렷하지 않아 새 자리가 잡힐 때까지 확인"]
    if comment:
        lines += ["", comment]
    lines += ["", "투자 판단은 본인 몫입니다. 선물은 손실이 크게 날 수 있습니다."]
    return "\n".join(lines)


SYSTEM = """텔레그램 채널 '차트보는 말희아빠'의 선물 브리핑 끝에 붙일 코멘트를 씁니다.
규칙:
- 차분한 존댓말로 한두 줄, 합쳐서 80자 안팎. 이모지를 쓰지 않습니다.
- 숫자는 '자료'에 있는 값만 그대로 씁니다. 지어내거나 새로 계산하지 않습니다.
- 어느 쪽 시나리오를 먼저 확인할지, 무엇을 보면 판단이 바뀌는지만 씁니다.
- 진입 지시, 레버리지 배수, 목표 수익률, '지금 사라/팔아라' 같은 표현을 쓰지 않습니다.
- '~가 아니라 ~다' 뒤집기, '핵심은', '결론적으로', '주목할' 같은 AI 말투를 쓰지 않습니다.
- 코멘트만 출력합니다."""


def write_comment(text, a):
    import llm
    if not llm.ready():
        return None
    try:
        r = llm.Anthropic().messages.create(model=cr.MODEL, max_tokens=500, system=SYSTEM,
                                            messages=[{"role": "user", "content": "자료:\n" + text}], output_config={"effort": "low"})
        c = r.content[0].text.strip().strip("`").strip()
    except (llm.APIStatusError, llm.APIConnectionError) as e:
        print("⚠️ Claude 코멘트 실패 — 코멘트 없이 보내요:", str(e)[:200])
        return None
    banned = ("진입하", "레버리지", "배 레버", "사세요", "파세요", "목표가", "수익률")
    if cr.check_text(c, {"자료": text}) or any(w in c for w in banned) or len(c) > 200:
        print("⚠️ Claude 코멘트에 없는 숫자·금지 표현 — 코멘트 없이 보내요:", c[:120])
        return None
    return c


def oi_series(symbol, tf, sec, candles):
    """미결제약정 → 그 시각이 들어 있는 봉에 맞춤."""
    try:
        xs = get("/futures/data/openInterestHist", symbol=symbol + "USDT", period=tf, limit=500)
    except requests.RequestException as e:
        print("⚠️ 미결제약정 내역 실패:", str(e)[:100])
        return []
    times = {c["time"] for c in candles}
    out = {}
    for x in xs:
        t = int(x["timestamp"] / 1000) // sec * sec + 32400
        if t in times:
            out[t] = float(x["sumOpenInterest"])
    return [{"time": t, "value": v} for t, v in sorted(out.items())]


def stat_line(st):
    parts = []
    if st["funding"] is not None:
        parts.append(f"펀딩 {st['funding']:+.3f}%")
    if st["oi_chg"] is not None:
        parts.append(f"OI 24h {st['oi_chg']:+.1f}%")
    if st["long"] is not None:
        parts.append(f"롱 {st['long']:.0f}%")
    if st["taker"] is not None:
        parts.append(f"테이커 {st['taker']:.2f}")
    return " · ".join(parts)


def make(symbol, name, use_ai=True):
    a = {"kind": "coin", "symbol": symbol, "name": name, "unit": "달러", "src": "바이낸스 USDT 무기한", "exchange": "BINANCE PERP"}
    st = stats_of(symbol)
    frames, files, web = {}, {}, {}
    now = datetime.now(KST)
    RAW.mkdir(parents=True, exist_ok=True)
    WEB.mkdir(parents=True, exist_ok=True)
    for tf, sec, show in FRAMES:
        k = get("/fapi/v1/klines", symbol=symbol + "USDT", interval=tf, limit=1000)
        rows = [cr.bar(x[0] / 1000, float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5]), tf, 0) for x in k]
        f = cr.analyze(rows, a, show, tf)
        cr.apply_live(f, a, {"label": "실시간", "at": now, "ext": None})
        frames[tf] = f
        for mode, scale, width in (("pc", 1.5, 1600), ("m", 1.5, 1080)):
            spec = cr.spec_of(f, a, "pc" if mode == "pc" else "mobile")
            spec["oi"] = oi_series(symbol, tf, sec, spec["candles"])
            spec["oi_label"] = "미결제약정 (OI)" + (f" {st['oi_usd'] / 1e9:.2f}B 달러" if st["oi_usd"] else "")
            spec["mark"] = f"{symbol}USDT.P, {cr.TF[tf]['short']}"
            spec["legend"] += f"<br><span>{stat_line(st)}</span>"
            spec["layout"].update({"top": .14, "bottom": .32, "oiTop": .70, "oiBottom": .83, "volTop": .86, "legendH": spec["layout"]["legendH"] + 20})
            png = RAW / f"futures_{symbol}_{tf}_{mode}.png"
            png.unlink(missing_ok=True)
            cr.render(spec, png, scale)
            cr.to_jpg(png, WEB / f"{symbol}_{tf}_{mode}.jpg", width)
            files[f"{tf}_{mode}"] = png
            web[f"{tf}_{mode}"] = f"futures/{symbol}_{tf}_{mode}.jpg"
    text = brief_text(a, frames, st)
    comment = write_comment(text, a) if use_ai else None
    if comment:
        text = brief_text(a, frames, st, comment)
    f4, f1 = frames["4h"], frames["1h"]
    item = {"symbol": symbol, "name": name, "close": f"{f4['P'](f4['close'])}{f4['U']}", "chg24": st["chg24"], "funding": st["funding"], "oi_chg": st["oi_chg"],
            "trend_4h": f4["trend"], "trend_1h": f1["trend"], "pc": web["4h_pc"], "mobile": web["4h_m"], "pc_1h": web["1h_pc"], "mobile_1h": web["1h_m"],
            "text": text, "text_by": "claude" if comment else "template", "made_at": now.isoformat(timespec="seconds")}
    return item, files


def send(item, files):
    from publish.notify import send as send_text, send_photos
    ok = send_photos([files["4h_pc"], files["1h_pc"], files["4h_m"], files["1h_m"]], f"📊 {item['name']} 4시간봉·1시간봉 (PC용·모바일용)")
    ok = send_text(item["text"]) and ok
    print("📨 봇으로 보냄" if ok else "⚠️ 봇 보내기 실패/미설정", item["name"])
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="봇으로도 보내기")
    ap.add_argument("--no-ai", action="store_true", help="Claude 코멘트 없이")
    ap.add_argument("--no-save", action="store_true", help="사이트 목록에 넣지 않음")
    args = ap.parse_args()
    load_env()
    items = []
    for symbol, name in COINS:
        try:
            item, files = make(symbol, name, not args.no_ai)
        except (SystemExit, requests.RequestException, KeyError, ValueError, IndexError) as e:
            print(f"⚠️ {name} 브리핑 실패: {e}")
            continue
        print(f"\n✅ {name} · {item['close']} · 4시간봉 {item['trend_4h']} · 1시간봉 {item['trend_1h']} ({item['text_by']})\n" + item["text"])
        if args.send:
            item["sent"] = send(item, files)
        items.append(item)
    if items and not args.no_save:
        old = json.loads(REPORT.read_text(encoding="utf-8")).get("items", []) if REPORT.exists() else []
        kept = [x for x in old if x["symbol"] not in {i["symbol"] for i in items}]   # 한 종목이 실패하면 지난 카드를 남김
        REPORT.write_text(json.dumps({"updated_at": datetime.now(KST).isoformat(timespec="seconds"), "items": sorted(items + kept, key=lambda x: x["symbol"])},
                                     ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if items else 1


if __name__ == "__main__":
    sys.exit(main())
