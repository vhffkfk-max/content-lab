"""카드뉴스 배경 사진 찾기 — 위키미디어 공용(키 필요 없음)에서 상업적 이용이 되는 사진만.

    from publish.photos import find
    p = find("Tesla car driving highway")   # → {"uri": file:// 주소, "url", "credit": "사진 이름 / CC BY 2.0", "page"} 또는 None
라이선스: CC BY·BY-SA·CC0·퍼블릭 도메인만 (ND·NC 는 뺌 — 어둡게 덮고 자르는 게 2차 가공이라). 장마다 작게 출처를 적는다.
Openverse 도 시험했지만 응답 없이 멈춰서(2026-11-01) 위키미디어로 함.
받은 사진은 output/cardnews/photos/ 에 모아 두고 같은 주소는 다시 받지 않는다.
"""
import hashlib
import html
import io
import json
import re
import urllib.parse
import urllib.request

from common import OUTPUT_DIR

API = "https://commons.wikimedia.org/w/api.php"
CACHE = OUTPUT_DIR / "cardnews" / "photos"
UA = {"User-Agent": "hotconomy-cardnews/1.0 (github.com/vhffkfk-max/content-lab)"}
OK_LICENSE = re.compile(r"^(cc[ -]by(-sa)?([ -][\d.]+.*)?|cc0.*|public domain.*|pd.*)$", re.I)
SKIP_TITLE = re.compile(r"\b(map|logo|flag|coat of arms|diagram|chart|graph|icon|seal|screenshot|signature)\b|\b1[89]\d\d\b", re.I)   # 옛날 사진(1940년 지프 등)도 뺌


def _get(url, timeout=25):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def search(query, n=20):
    """검색 순서(관련도)대로 [{url, width, height, license, artist, page, title}]."""
    q = urllib.parse.urlencode({"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6, "gsrlimit": n,
                                "gsrsearch": f"{query} filetype:bitmap", "prop": "imageinfo", "iiprop": "url|size|extmetadata", "iiurlwidth": 1400,
                                "iiextmetadatafilter": "LicenseShortName|Artist"})
    try:
        pages = json.loads(_get(f"{API}?{q}")).get("query", {}).get("pages", {})
    except Exception as e:
        print("⚠️ 사진 검색 실패:", query, e)
        return []
    rows = []
    for p in sorted(pages.values(), key=lambda p: p.get("index", 0)):
        i = (p.get("imageinfo") or [{}])[0]
        m = i.get("extmetadata") or {}
        artist = re.sub(r"<[^>]+>", "", html.unescape((m.get("Artist") or {}).get("value", ""))).strip()
        rows.append({"url": i.get("thumburl") or i.get("url"), "width": i.get("width") or 0, "height": i.get("height") or 0,
                     "license": (m.get("LicenseShortName") or {}).get("value", ""), "artist": artist,
                     "page": i.get("descriptionurl", ""), "title": p.get("title", "")})
    return rows


def _save(url):
    """사진 받기 → JPG. 그림이 아니거나 너무 작으면 None."""
    from PIL import Image
    path = CACHE / f"{hashlib.sha1(url.encode()).hexdigest()[:16]}.jpg"
    if path.exists():
        return path
    try:
        img = Image.open(io.BytesIO(_get(url, 40))).convert("RGB")
    except Exception as e:
        print("⚠️ 사진 받기 실패:", url[:80], e)
        return None
    if min(img.size) < 600:
        return None
    CACHE.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=88)
    return path


def credit(r):
    who = r["artist"][:30]
    return f"사진 {who + ' / ' if who else ''}{r['license']} (위키미디어 공용)"


def find(query, used=()):
    """검색어에 가장 맞는 큰 사진 하나 (이미 쓴 사진은 건너뜀). 세로 카드라 너무 납작한 사진은 뒤로."""
    words = query.split()
    found = search(query) or (search(" ".join(words[-2:])) if len(words) > 2 else [])   # 너무 구체적이면 뒤 두 단어로 다시
    rows = [r for r in found if r["url"] and r["width"] >= 1000 and r["height"] >= 700 and r["url"] not in used
            and OK_LICENSE.match(r["license"].strip()) and not SKIP_TITLE.search(r["title"])]
    rows.sort(key=lambda r: r["width"] / r["height"] > 2.2)   # 그 밖엔 검색 순서(관련도) 그대로
    for r in rows[:4]:
        p = _save(r["url"])
        if p:
            return {"uri": p.as_uri(), "url": r["url"], "credit": credit(r), "page": r["page"]}
    return None
