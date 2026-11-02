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


def _eye(paths, about):
    """후보 사진을 한 장에 모아 Claude(Max)에게 보여 주고 번호를 받는다. 검색어만으론 엉뚱한 사진이 나와서(2026-11-02). 1부터, 0이면 맞는 게 없음, None 이면 못 물어봄."""
    import tempfile
    import llm
    from PIL import Image, ImageDraw
    if not llm.ready():
        return None
    sheet = Image.new("RGB", (340 * len(paths), 460), "white")
    d = ImageDraw.Draw(sheet)
    for i, p in enumerate(paths):
        im = Image.open(p).convert("RGB")
        im.thumbnail((330, 430))
        sheet.paste(im, (i * 340 + 5, 28))
        d.text((i * 340 + 8, 8), str(i + 1), fill="black")
    with tempfile.TemporaryDirectory() as tmp:
        f = f"{tmp}/candidates.jpg"
        sheet.save(f, quality=80)
        try:
            ans = llm.look("claude-haiku-5-5", f"경제 카드뉴스 배경 사진을 고릅니다. 카드 내용: {about}\n"
                           "번호가 붙은 후보 중 이 내용을 가장 바로 보여 주는 사진 번호 하나만 답하세요. 사람 이야기면 그 사람 얼굴이 크고 선명한 것. "
                           "글자가 많은 것, 흑백 옛날 사진, 흐린 것, 내용과 상관없는 것은 고르지 마세요. 맞는 게 없으면 0.", f)
        except Exception as e:
            print("⚠️ 사진 고르기 실패 (검색 순서대로):", e)
            return None
    m = re.search(r"\d+", ans)
    return int(m.group()) if m else None


def find(query, used=(), about=""):
    """검색어에 가장 맞는 큰 사진 하나 (이미 쓴 사진은 건너뜀). 세로 카드라 너무 납작한 사진은 뒤로. about 을 주면 후보를 눈으로 보고 고른다."""
    words = query.split()
    found = search(query) or (search(" ".join(words[-2:])) if len(words) > 2 else [])   # 너무 구체적이면 뒤 두 단어로 다시
    rows = [r for r in found if r["url"] and r["width"] >= 1000 and r["height"] >= 700 and r["url"] not in used
            and OK_LICENSE.match(r["license"].strip()) and not SKIP_TITLE.search(r["title"])]
    rows.sort(key=lambda r: r["width"] / r["height"] > 2.2)   # 그 밖엔 검색 순서(관련도) 그대로
    got = [(r, p) for r in rows[:6 if about else 4] if (p := _save(r["url"]))]
    if not got:
        return None
    pick = _eye([p for _, p in got], about) if about and len(got) > 1 else None
    if pick == 0:
        return None
    r, p = got[pick - 1] if pick and pick <= len(got) else got[0]
    return {"uri": p.as_uri(), "url": r["url"], "credit": credit(r), "page": r["page"]}
