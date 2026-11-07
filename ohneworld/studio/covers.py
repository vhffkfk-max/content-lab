"""표지 사진. 순서: 재료 폴더의 표지.* → 위키미디어 공용(자유 이용 사진) → 없으면 어두운 기본 배경.

재사용 조건은 파일 정보로 거르고 출처를 남긴다. 캔바에서 사진만 갈아 끼울 수 있다.
"""
import json
import pathlib
import re

import requests

API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "malhee-studio/0.1 (cover photo lookup)"}
FREE = re.compile(r"^(cc0|public domain|pd\b|cc by(-sa)?( |$))", re.I)


def search(query, limit=12):
    r = requests.get(API, headers=UA, timeout=25, params={
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6, "gsrsearch": f"{query} filetype:bitmap", "gsrlimit": limit,
        "prop": "imageinfo", "iiprop": "url|size|extmetadata|mime", "iiurlwidth": 1600})
    r.raise_for_status()
    pages = (r.json().get("query") or {}).get("pages", {})
    out = []
    for p in sorted(pages.values(), key=lambda x: x.get("index", 0)):
        info = (p.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        lic = (meta.get("LicenseShortName") or {}).get("value", "")
        if not FREE.match(lic) or info.get("mime") not in ("image/jpeg", "image/png") or info.get("width", 0) < 900:
            continue
        artist = re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value", "")).strip()
        out.append({"title": p.get("title", ""), "url": info.get("thumburl") or info.get("url"), "page": info.get("descriptionurl", ""), "license": lic, "artist": artist, "w": info["width"], "h": info["height"]})
    return out


def find(queries, folder):
    """고른 사진을 folder 에 저장하고 출처 정보를 돌려준다. 어떤 후보를 썼는지 표지_출처.json 에 남긴다."""
    folder = pathlib.Path(folder)
    for q in queries:
        try:
            rows = search(q)
        except (requests.RequestException, ValueError):
            continue
        word = q.split()[0].lower()
        for row in rows:
            if word not in row["title"].lower():   # 검색어의 첫 낱말(회사·제품명)이 파일 이름에 있는 사진만. 경쟁사 사진이 끼는 것을 막는다
                continue
            try:
                g = requests.get(row["url"], headers=UA, timeout=30)
            except requests.RequestException:
                continue
            if g.status_code == 200 and g.headers.get("content-type", "").startswith("image/"):
                ext = ".png" if "png" in g.headers["content-type"] else ".jpg"
                f = folder / f"표지_위키미디어{ext}"
                f.write_bytes(g.content)
                (folder / "표지_출처.json").write_text(json.dumps({**row, "query": q}, ensure_ascii=False, indent=1), encoding="utf-8")
                return f, {**row, "query": q}
    return None, None
