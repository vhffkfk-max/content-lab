"""백업 폴더·압축 파일을 안전하게 훑는다. 압축은 풀지 않고 필요한 파일만 메모리에서 읽는다.

    for f in walk(folder): f.rel (경로), f.name, f.ext, f.size, f.read()
"""
import pathlib
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

MAX_BYTES = 50 * 1024 * 1024   # 글·설명 파일 하나의 최대 크기
KST = timezone(timedelta(hours=9))


@dataclass
class Entry:
    rel: str
    size: int
    reader: Callable[[], bytes]

    @property
    def name(self):
        return self.rel.rsplit("/", 1)[-1]

    @property
    def ext(self):
        return pathlib.PurePosixPath(self.name).suffix.lower()

    def read(self):
        if self.size > MAX_BYTES:
            raise ValueError(f"파일이 너무 큼: {self.rel}")
        return self.reader()

    def text(self):
        raw = self.read()
        for enc in ("utf-8-sig", "cp949"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", "replace")


def _zip_name_ok(name):
    p = pathlib.PurePosixPath(name.replace("\\", "/"))
    return not p.is_absolute() and ".." not in p.parts


def walk(folder):
    folder = pathlib.Path(folder)
    if not folder.exists():
        return
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        rel = path.relative_to(folder).as_posix()
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as z:
                for info in z.infolist():
                    if info.is_dir() or not _zip_name_ok(info.filename):
                        continue
                    # 파일을 실제로 읽을 때만 압축을 연다
                    yield Entry(f"{rel}!/{info.filename}", info.file_size,
                                lambda p=path, n=info.filename: zipfile.ZipFile(p).read(n))
        else:
            yield Entry(rel, path.stat().st_size, path.read_bytes)


def skipped(rel, words):
    """경로 안에 빼기로 한 낱말이 폴더·파일 이름으로 들어 있나."""
    low = rel.lower().replace("!/", "/")
    parts = re.split(r"[/\\]", low)
    for w in words:
        w = w.lower()
        if "/" in w:
            if w in low:
                return True
        elif any(w == p or p.startswith(w + "_") or p.startswith(w + ".") or (not w.isascii() and w in p) for p in parts):
            return True
    return False


DATE_RES = [
    (re.compile(r"(20\d{2})[.\-/년]\s*(\d{1,2})[.\-/월]\s*(\d{1,2})일?(?:[.\sT]+(\d{1,2}):(\d{2}))?"), None),
    (re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)"), None),
]


def parse_date(value):
    """여러 모양의 날짜 → 한국시간 ISO 글자. 못 읽으면 None."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        if v > 1e11:
            v /= 1000
        if 9e8 < v < 4e9:
            return datetime.fromtimestamp(v, KST).isoformat(timespec="minutes")
        return None
    s = str(value).strip()
    if re.fullmatch(r"\d{10,13}", s):
        return parse_date(int(s))
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(s).astimezone(KST).isoformat(timespec="minutes")
    except (TypeError, ValueError, IndexError):
        pass
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=KST)).astimezone(KST).isoformat(timespec="minutes")
    except ValueError:
        pass
    for rx, _ in DATE_RES:
        m = rx.search(s)
        if m:
            g = m.groups()
            try:
                d = datetime(int(g[0]), int(g[1]), int(g[2]), int(g[3] or 0) if len(g) > 3 else 0, int(g[4] or 0) if len(g) > 4 else 0, tzinfo=KST)
                return d.isoformat(timespec="minutes")
            except ValueError:
                continue
    return None
