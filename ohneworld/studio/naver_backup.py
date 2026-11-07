"""네이버 콘텐츠 백업 읽기 → 글·사진·영상·날짜만.

실제 백업 파일을 아직 못 봤다. 그래서 JSON·XML·HTML·TXT·PDF 를 모두 시도하고,
칸 이름은 formats.json 의 후보로 찾는다. 받은 뒤 형식이 다르면 `python studio.py 점검` 결과를 보고
formats.json 을 고치거나 read_entry 에 형식을 하나 더한다.
댓글·이웃·쪽지 같은 경로(skip_paths)는 열지 않고, 글에서도 정해진 칸만 꺼낸다.
"""
import hashlib
import html
import json
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

from studio.backup_common import parse_date, skipped, walk
from studio.paths import FORMATS, load_json

IMAGE = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
VIDEO = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
DOC = {".json", ".xml", ".rss", ".html", ".htm", ".txt", ".md", ".pdf"}


def _fmt():
    return load_json(FORMATS)["naver"]


def _clean(s):
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", str(s or ""))
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    return re.sub(r"[ \t ​]+", " ", re.sub(r"\s*\n\s*", "\n", s)).strip()


def _first(d, keys):
    low = {k.lower(): v for k, v in d.items()}
    for k in keys:
        if k.lower() in low and low[k.lower()] not in (None, "", []):
            return low[k.lower()]
    return None


def _files(v):
    """사진·영상 칸의 값 → 경로·주소 목록."""
    out = []
    for x in v if isinstance(v, list) else [v] if v else []:
        if isinstance(x, dict):
            x = _first(x, ["path", "url", "src", "uri", "file", "경로"])
        if x:
            out.append(str(x))
    return out


def _post(title, date, body, images=(), videos=(), pid=None, src=""):
    body = _clean(body)
    title = _clean(title)
    if not (title or body):
        return None
    when = parse_date(date)
    raw = pid or f"{title}|{when}|{body[:80]}"
    return {"id": str(pid) if pid else hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12], "date": when, "title": title, "text": body,
            "images": list(images), "videos": list(videos), "source_file": src}


def _json_posts(node, f, src, out):
    if isinstance(node, list):
        for x in node:
            _json_posts(x, f, src, out)
    elif isinstance(node, dict):
        title, body = _first(node, f["title"]), _first(node, f["body"])
        if title is not None and body is not None:
            p = _post(title, _first(node, f["date"]), body, _files(_first(node, f["images"])), _files(_first(node, f["videos"])), _first(node, f["id"]), src)
            if p:
                out.append(p)
            return
        for v in node.values():
            if isinstance(v, (list, dict)):
                _json_posts(v, f, src, out)


def _xml_posts(text, f, src):
    out = []
    root = ET.fromstring(text)
    tag = lambda e: e.tag.rsplit("}", 1)[-1].lower()
    tags = {t.lower() for t in f["post_tags"]}
    for el in root.iter():
        if tag(el) not in tags:
            continue
        d = {}
        imgs, vids = [], []
        for ch in el:
            d.setdefault(tag(ch), (ch.text or "") + "".join(ET.tostring(x, encoding="unicode") for x in ch))
            if tag(ch) in {k.lower() for k in f["images"]}:
                imgs.append(ch.text or ch.get("src") or ch.get("url") or "")
            if tag(ch) in {k.lower() for k in f["videos"]}:
                vids.append(ch.text or ch.get("src") or ch.get("url") or "")
        body = _first(d, f["body"]) or ""
        imgs += re.findall(r'<img[^>]+src=["\']([^"\']+)', html.unescape(body))
        p = _post(_first(d, f["title"]), _first(d, f["date"]), body, [x for x in imgs if x], [x for x in vids if x], _first(d, f["id"]), src)
        if p:
            out.append(p)
    return out


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.imgs, self.vids, self.meta, self.title, self.h1 = [], [], [], {}, "", ""
        self._skip = self._t = self._h = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "title":
            self._t = 1
        elif tag == "h1":
            self._h = 1
        elif tag == "img" and a.get("src"):
            self.imgs.append(a["src"])
        elif tag in ("video", "source") and a.get("src"):
            self.vids.append(a["src"])
        elif tag == "meta" and a.get("content"):
            self.meta[(a.get("name") or a.get("property") or "").lower()] = a["content"]
        elif tag == "time" and a.get("datetime"):
            self.meta["time"] = a["datetime"]

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._t = 0
        elif tag == "h1":
            self._h = 0
        elif tag in ("p", "div", "br", "li", "h2", "h3"):
            self.parts.append("\n")

    def handle_data(self, data):
        if self._skip:
            return
        if self._t:
            self.title += data
        elif self._h:
            self.h1 += data
        else:
            self.parts.append(data)


def _html_post(text, src):
    pg = _Page()
    pg.feed(text)
    body = "".join(pg.parts)
    date = pg.meta.get("time") or pg.meta.get("article:published_time") or pg.meta.get("date")
    if not date:
        date = parse_date(body[:400]) or parse_date(src)
    return _post(pg.h1 or pg.title, date, body, pg.imgs, pg.vids, None, src)


def _pdf_post(raw, name, src):
    try:
        import fitz
    except ImportError:
        return None
    with fitz.open(stream=raw, filetype="pdf") as doc:
        body = "\n".join(p.get_text() for p in doc)
        n = sum(len(p.get_images(full=True)) for p in doc)
    title = re.sub(r"\.pdf$", "", name, flags=re.I)
    p = _post(title, parse_date(name) or parse_date(body[:400]), body, [], [], None, src)
    if p:
        p["pdf_images"] = n
    return p


def read_entry(e, f):
    """파일 하나 → 글 목록. 새 형식은 여기에 더한다."""
    if e.ext == ".json":
        out = []
        _json_posts(json.loads(e.text()), f, e.rel, out)
        return out
    if e.ext in (".xml", ".rss"):
        return _xml_posts(e.text(), f, e.rel)
    if e.ext in (".html", ".htm"):
        p = _html_post(e.text(), e.rel)
        return [p] if p else []
    if e.ext in (".txt", ".md"):
        lines = e.text().strip().split("\n")
        p = _post(lines[0][:120], parse_date("\n".join(lines[:5])) or parse_date(e.name), "\n".join(lines[1:]), src=e.rel)
        return [p] if p else []
    if e.ext == ".pdf":
        p = _pdf_post(e.read(), e.name, e.rel)
        return [p] if p else []
    return []


def read_all(folder):
    f = _fmt()
    posts, report = [], {"docs": 0, "skipped_paths": 0, "unknown_ext": {}, "errors": [], "media_files": 0, "no_post": []}
    media_by_dir = {}
    entries = list(walk(folder))
    for e in entries:
        if skipped(e.rel, f["skip_paths"]):
            report["skipped_paths"] += 1
            continue
        if e.ext in IMAGE or e.ext in VIDEO:
            report["media_files"] += 1
            media_by_dir.setdefault(e.rel.rsplit("/", 1)[0] if "/" in e.rel else "", []).append(e)
    for e in entries:
        if skipped(e.rel, f["skip_paths"]) or e.ext in IMAGE or e.ext in VIDEO:
            continue
        if e.ext not in DOC:
            report["unknown_ext"][e.ext or "(없음)"] = report["unknown_ext"].get(e.ext or "(없음)", 0) + 1
            continue
        report["docs"] += 1
        try:
            found = read_entry(e, f)
        except (ValueError, ET.ParseError, OSError) as err:
            report["errors"].append(f"{e.rel}: {type(err).__name__}")
            continue
        if not found:
            report["no_post"].append(e.rel)
        # 글 하나짜리 파일이면 같은 폴더(또는 이름이 같은 폴더)의 사진을 붙인다
        if len(found) == 1:
            d = e.rel.rsplit("/", 1)[0] if "/" in e.rel else ""
            stem = e.name.rsplit(".", 1)[0]
            near = media_by_dir.get(f"{d}/{stem}" if d else stem, []) or (media_by_dir.get(d, []) if d else [])
            for m in near:
                (found[0]["images"] if m.ext in IMAGE else found[0]["videos"]).append(m.rel)
        posts += found
    seen, uniq = set(), []
    for p in sorted(posts, key=lambda x: x["date"] or ""):
        if p["id"] not in seen:
            seen.add(p["id"])
            uniq.append(p)
    report["posts"] = len(uniq)
    report["no_date"] = sum(1 for p in uniq if not p["date"])
    return uniq, report
