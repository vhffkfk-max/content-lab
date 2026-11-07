"""인스타 '내 정보 내보내기'(JSON) 읽기 → 게시물의 글·사진·영상·날짜만.

정해 둔 이름의 파일(posts·reels 등)만 열고, 메시지(DM)·댓글·팔로워·로그인 정보 폴더는 열지 않는다.
사진의 촬영 정보(media_metadata, 위치가 들어 있을 수 있음)는 꺼내지 않는다.
실제 파일을 아직 못 봤다. 칸·파일 이름이 다르면 formats.json 을 고친다.
"""
import hashlib
import json
import re

from studio.backup_common import parse_date, skipped, walk
from studio.paths import FORMATS, load_json

VIDEO = (".mp4", ".mov", ".webm")


def _fmt():
    return load_json(FORMATS)["instagram"]


def fix_text(s):
    """메타 내보내기는 한글을 깨진 라틴 글자로 넣는 일이 많다. 되돌릴 수 있을 때만 되돌린다."""
    if not isinstance(s, str) or not s:
        return s or ""
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def _groups(node):
    """게시물 묶음 찾기: {media: [...]} 하나가 게시물 하나, uri 만 있으면 사진 하나짜리 게시물."""
    if isinstance(node, list):
        for x in node:
            yield from _groups(x)
    elif isinstance(node, dict):
        if isinstance(node.get("media"), list) and node["media"]:
            yield node
        elif "uri" in node:
            yield {"media": [node]}
        else:
            for k, v in node.items():
                if k != "media_metadata" and isinstance(v, (list, dict)):
                    yield from _groups(v)


def _post(g, src, reel):
    media = [m for m in g["media"] if isinstance(m, dict) and m.get("uri")]
    if not media:
        return None
    first = media[0]
    caption = fix_text(g.get("title") or first.get("title") or "")
    ts = g.get("creation_timestamp") or first.get("creation_timestamp") or first.get("taken_at")
    photos = [m["uri"] for m in media if not m["uri"].lower().endswith(VIDEO)]
    videos = [m["uri"] for m in media if m["uri"].lower().endswith(VIDEO)]
    kind = "릴스" if reel or (videos and len(media) == 1) else "캐러셀" if len(media) > 1 else "사진"
    pid = hashlib.sha1((first["uri"] + str(ts)).encode("utf-8")).hexdigest()[:12]
    return {"id": pid, "date": parse_date(ts), "kind": kind, "caption": caption, "photos": photos, "videos": videos, "n_media": len(media), "source_file": src, "ts": ts}


def _insights(node, names, out):
    """옛 '인사이트' 파일에 수치가 있으면 시각으로 묶어 둔다 (없을 수 있음)."""
    if isinstance(node, list):
        for x in node:
            _insights(x, names, out)
    elif isinstance(node, dict):
        smd = node.get("string_map_data")
        if isinstance(smd, dict):
            row, ts = {}, node.get("creation_timestamp")
            for k, v in smd.items():
                k2 = fix_text(k)
                if isinstance(v, dict) and v.get("timestamp") and not ts:
                    ts = v["timestamp"]
                raw = re.sub(r"[^\d]", "", str(v.get("value", ""))) if isinstance(v, dict) else ""
                for field, labels in names.items():
                    if raw and k2 in labels:
                        row[field] = int(raw)
            if row and ts:
                out.append({**row, "ts": ts})
            return
        for k, v in node.items():
            if isinstance(v, (list, dict)):
                _insights(v, names, out)


def read_all(folder):
    f = _fmt()
    files, ins_files = re.compile(f["read_files"], re.I), re.compile(f["insights_files"], re.I)
    posts, insights = [], []
    report = {"opened": [], "skipped_paths": 0, "other_files": 0, "media_files": 0, "html_files": 0, "errors": []}
    for e in walk(folder):
        if skipped(e.rel, f["skip_paths"]):
            report["skipped_paths"] += 1   # 내용을 읽지 않고 넘어간다
            continue
        if e.ext in (".jpg", ".jpeg", ".png", ".webp", ".heic", ".mp4", ".mov", ".webm"):
            report["media_files"] += 1
            continue
        if e.ext in (".html", ".htm"):
            report["html_files"] += 1
            continue
        in_ins = f["insights_dir"] in e.rel
        if e.ext != ".json" or not (ins_files if in_ins else files).match(e.name):
            report["other_files"] += 1
            continue
        report["opened"].append(e.rel)
        try:
            data = json.loads(e.text())
        except ValueError as err:
            report["errors"].append(f"{e.rel}: {type(err).__name__}")
            continue
        if in_ins:
            _insights(data, f["metric_names"], insights)
            continue
        reel = "reel" in e.name.lower() or "igtv" in e.name.lower()
        posts += [p for p in (_post(g, e.rel, reel) for g in _groups(data)) if p]
    seen, uniq = set(), []
    for p in sorted(posts, key=lambda x: x["date"] or ""):
        if p["id"] not in seen:
            seen.add(p["id"])
            uniq.append(p)
    # 인사이트 수치를 같은 시각(±2분) 게시물에 붙인다
    report["insight_rows"] = len(insights)
    for row in insights:
        for p in uniq:
            try:
                if p.get("ts") and abs(int(p["ts"]) - int(row["ts"])) <= 120:
                    p.setdefault("metrics", {}).update({k: v for k, v in row.items() if k != "ts"})
                    break
            except (TypeError, ValueError):
                continue
    report["posts"] = len(uniq)
    report["no_date"] = sum(1 for p in uniq if not p["date"])
    return uniq, report
