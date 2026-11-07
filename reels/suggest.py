"""영상 추천 주제: '지금 쓸 거리'(hot_now.json, 30분마다 Claude 가 고른 글감)와 구글 기회 주제에서 고른다.

    python reels/suggest.py      # 추천 목록을 찍어 본다 (Claude 호출 없음)

- 뉴스 검색이 잘 되게 주제를 짧은 검색어로 줄이고, 글감의 출처 기사 주소를 함께 넘겨 보드 재료로 쓴다.
- 오늘 이미 보드를 만든 주제는 뺀다.
"""
import json
import pathlib
import re
import sys
from datetime import datetime, timedelta

HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
import make_reel as mr  # noqa: E402

SITE = mr.OUTPUT_DIR / "site"
FILE = mr.REELS_DIR / "suggest.json"
HOURS = 8
LIMIT = 6


def keyword(topic):
    """'아시아 반도체 급락: TSMC 한때…' → '아시아 반도체 급락'. 숫자 낱말은 빼고 앞의 세 낱말만."""
    head = re.split(r"[:：…]|\s[-—]\s", re.sub(r"[\[\]【】\"'‘’“”]", " ", topic))[0]
    words = [w for w in re.split(r"\s+", head) if w and not re.search(r"\d", w)]
    return " ".join(words[:3]).strip(" ,·")


def boarded_today():
    today = datetime.now(mr.KST).strftime("%Y%m%d")
    out = []
    for d in mr.REELS_DIR.glob(f"{today}_*"):
        try:
            out.append(json.loads((d / "대본.json").read_text(encoding="utf-8"))["topic"])
        except (OSError, ValueError, KeyError):
            continue
    return out


def same(a, b):
    ta, tb = set(mr.tokens(a)), set(mr.tokens(b))
    return bool(ta) and len(ta & tb) >= max(1, min(len(ta), len(tb)) - 1)


def build():
    now = datetime.now(mr.KST)
    rows = []
    try:
        hot = json.loads((SITE / "hot_now.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        hot = []
    for slot in hot:
        try:
            at = datetime.fromisoformat(slot["at"])
        except (KeyError, ValueError):
            continue
        if now - at > timedelta(hours=HOURS):
            continue
        for p in slot.get("picks", []):
            kw = keyword(p.get("topic", ""))
            if len(kw) < 2:
                continue
            links = p.get("sources") or []
            links = [x for x in (links if isinstance(links, list) else []) if isinstance(x, str) and x.startswith("https://")][:6]
            rows.append({"keyword": kw, "title": p.get("title") or p.get("topic", ""), "why": (p.get("why_now") or "")[:160], "at": slot.get("time", ""), "links": links, "from": "지금 쓸 거리"})
    try:
        opp = json.loads((SITE / "google_opportunities.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        opp = []
    for o in sorted(opp, key=lambda x: -(x.get("press_kr_24h") or 0))[:3]:
        kw = keyword(o.get("topic", "").split("·")[0])
        if kw:
            rows.append({"keyword": kw, "title": f"{kw}: 오늘 기사 {o.get('press_kr_24h', 0)}건", "why": "검색·기사 관심이 꾸준한 주제", "at": "", "links": [], "from": "꾸준한 관심"})
    done, out = boarded_today(), []
    for r in rows:
        if any(same(r["keyword"], x["keyword"]) for x in out) or any(same(r["keyword"], t) for t in done):
            continue
        out.append(r)
        if len(out) >= LIMIT:
            break
    return out


def save():
    rows = build()
    FILE.parent.mkdir(parents=True, exist_ok=True)
    old = FILE.read_text(encoding="utf-8") if FILE.exists() else ""
    new = json.dumps({"updated": datetime.now(mr.KST).strftime("%m/%d %H:%M"), "items": rows}, ensure_ascii=False, indent=1)
    changed = [r["keyword"] for r in json.loads(old).get("items", [])] != [r["keyword"] for r in rows] if old else True
    FILE.write_text(new, encoding="utf-8")
    return rows, changed


def seed_for(topic):
    """사이트에서 추천 주제를 누르면 그 글감의 출처 기사를 재료로 함께 쓴다."""
    try:
        items = json.loads(FILE.read_text(encoding="utf-8")).get("items", [])
    except (OSError, ValueError):
        return []
    hit = next((r["links"] for r in items if topic in (r["keyword"], r.get("title"))), None)
    if hit is not None:
        return hit
    norm = lambda s: " ".join(str(s or "").split())[:60].strip()
    try:   # 지금 쓸 거리 카드에서 누른 제목 (추천 목록에서 빠진 지난 글감도)
        hot = json.loads((SITE / "hot_now.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    for slot in hot:
        for p in slot.get("picks", []):
            if norm(p.get("title")) == norm(topic):
                links = p.get("sources") if isinstance(p.get("sources"), list) else []
                return [x for x in links if isinstance(x, str) and x.startswith("https://")][:6]
    return []


if __name__ == "__main__":
    for r in build():
        print(f"{r['keyword']:<20} | {r['from']} {r['at']} | {r['title'][:50]} | 출처 {len(r['links'])}")
