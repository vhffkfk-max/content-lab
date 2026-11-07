"""새 글 입력: 공개 RSS(제목·요약 최대 50개) + 바레이션 결과. 본문·사진을 긁지 않는다.

RSS 는 약 15일 치만 준다. 지난 글은 공식 백업으로 받는다.
바레이션 파일은 연구소가 만든다. 파일이 없으면 RSS 만 쓴다 (config.json 의 variation_json).
"""
import html
import json
import pathlib
import re
import xml.etree.ElementTree as ET

import requests

from studio.backup_common import parse_date
from studio.paths import CONFIG, DATA, load_json, save_json

UA = {"User-Agent": "Mozilla/5.0"}


def parse_rss(xml_text):
    root = ET.fromstring(xml_text)
    out = []
    for it in root.iter("item"):
        guid = (it.findtext("guid") or it.findtext("link") or "").strip()
        post_id = guid.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
        desc = html.unescape(re.sub(r"<[^>]+>", " ", it.findtext("description") or ""))
        out.append({"key": f"blog:{post_id}", "source": "블로그", "title": (it.findtext("title") or "").strip(), "date": parse_date(it.findtext("pubDate")),
                    "url": f"https://blog.naver.com/{CONFIG['blog_id']}/{post_id}", "category": it.findtext("category") or "",
                    "summary": re.sub(r"\s+", " ", desc).strip()})
    return out


def fetch_rss():
    r = requests.get(f"https://rss.blog.naver.com/{CONFIG['blog_id']}.xml", headers=UA, timeout=25)
    r.raise_for_status()
    r.encoding = "utf-8"
    return parse_rss(r.text)


def load_variations(path=None):
    path = pathlib.Path(path or CONFIG["variation_json"])
    rows = load_json(path, None)
    return rows if isinstance(rows, list) else None


def merge(rss, variations):
    """같은 글은 한 줄로. 바레이션은 사실 확인 항목(check)까지 같이 가져온다."""
    items = {x["key"]: x for x in rss}
    for v in variations or []:
        key = v.get("key")
        if not key:
            continue
        row = items.setdefault(key, {"key": key, "source": v.get("source", ""), "title": v.get("title", ""), "date": parse_date(v.get("made")), "url": v.get("url", ""), "summary": ""})
        row.update(variation=v.get("text", ""), variation_title=v.get("title", ""), check=v.get("check", []), variation_made=v.get("made", ""))
    return sorted(items.values(), key=lambda x: x.get("date") or "", reverse=True)


def update():
    try:
        rss = fetch_rss()
        rss_err = ""
    except (requests.RequestException, ET.ParseError) as e:
        rss, rss_err = [], f"{type(e).__name__}"
    variations = load_variations()
    rows = merge(rss, variations)
    if not rows and not rss:   # 망이 끊겨도 지난 목록은 지우지 않는다
        return load_json(DATA / "새글.json", []), {"rss": 0, "rss_error": rss_err, "variations": 0, "total": 0}
    save_json(DATA / "새글.json", rows)
    return rows, {"rss": len(rss), "rss_error": rss_err, "variations": len(variations or []), "variation_file": variations is not None, "total": len(rows)}


def dumps(rows, n=20):
    return "\n".join(f"{(r.get('date') or '')[:10]}  {r['key']:<22} {'바레이션' if r.get('variation') else '요약만':<5} {r['title'][:50]}" for r in rows[:n])


if __name__ == "__main__":
    print(json.dumps(update()[1], ensure_ascii=False))
