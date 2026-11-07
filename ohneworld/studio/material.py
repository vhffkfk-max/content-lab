"""글 하나의 재료 폴더: 재료/<이름>/ 글.txt, 차트*.png·jpg, 표지.*, 정보.json

새 글은 RSS 요약과 바레이션으로 글.txt 를 채운다. 차트는 블로그 본문을 긁지 않으므로 사람이 넣는다.
"""
import hashlib
import pathlib
import re

from studio.paths import DATA, MATERIAL, load_json, save_json

IMG = (".png", ".jpg", ".jpeg", ".webp")


def folder_name(key):
    return re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", key)


def md5(path):
    return hashlib.md5(pathlib.Path(path).read_bytes()).hexdigest()


def charts_of(folder):
    return sorted(p for p in pathlib.Path(folder).iterdir() if p.is_file() and p.name.startswith("차트") and p.suffix.lower() in IMG)


def cover_of(folder):
    return next((p for p in sorted(pathlib.Path(folder).iterdir()) if p.is_file() and p.stem == "표지" and p.suffix.lower() in IMG), None)


def prepare(key):
    """이름이나 새 글 키로 재료 폴더를 찾거나 만든다."""
    direct = MATERIAL / key
    if direct.is_dir():
        return direct
    rows = load_json(DATA / "새글.json", []) or []
    row = next((r for r in rows if r["key"] == key), None)
    if key == "최신" and rows:
        row = rows[0]
    if not row:
        raise SystemExit(f"'{key}' 글을 찾지 못했어요. `python studio.py 새글` 로 목록을 확인해 주세요.")
    d = MATERIAL / folder_name(row["key"])
    d.mkdir(parents=True, exist_ok=True)
    if not (d / "글.txt").exists():
        parts = [f"제목: {row['title']}", f"날짜: {row.get('date') or ''}", f"주소: {row.get('url') or ''}", ""]
        if row.get("summary"):
            parts += ["[RSS 요약]", row["summary"], ""]
        if row.get("variation"):
            parts += ["[바레이션]", row["variation"], ""]
        (d / "글.txt").write_text("\n".join(parts), encoding="utf-8")
    if not (d / "정보.json").exists():
        save_json(d / "정보.json", {"key": row["key"], "title": row["title"], "basis": "", "date": (row.get("date") or "")[:10], "url": row.get("url", "")})
    return d


def load(folder):
    folder = pathlib.Path(folder)
    info = load_json(folder / "정보.json", {}) or {}
    return {"folder": folder, "info": info, "text": (folder / "글.txt").read_text(encoding="utf-8") if (folder / "글.txt").exists() else "",
            "charts": charts_of(folder), "cover": cover_of(folder), "checked": (folder / "확인된수치.txt").read_text(encoding="utf-8") if (folder / "확인된수치.txt").exists() else ""}
