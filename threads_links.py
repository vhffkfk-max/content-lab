"""팀이 모은 쓰레드 글(링크 + 붙여넣은 본문)을 읽어 DB에 쌓는다.

입력 두 곳을 모두 읽는다:
  1) 구글 폼 응답 시트를 '웹에 게시(CSV)'한 주소 → site/site_config.json 의 threads_sheet_csv
  2) 저장소의 threads_links.csv (직접 적어도 됨)
열 이름은 자유롭게: '링크'·'본문(또는 내용)'·'좋아요'·'답글'·'리포스트'·'메모'·'이름' 이 들어간 열을 알아서 찾는다.

    python threads_links.py
쓰레드 공식 임베드는 글 본문을 주지 않아서(버튼 틀만 옴), 본문은 사람이 붙여넣거나, 비워 두면 apify_threads.py 가 채운다.
"""
import csv
import hashlib
import io
import json
import re
import urllib.request
from datetime import datetime, timezone

from common import ROOT, connect
from topics import topics_of

SCHEMA = """
CREATE TABLE IF NOT EXISTS threads_saved (
    id TEXT PRIMARY KEY, link TEXT, author TEXT, text TEXT, likes INTEGER, replies INTEGER, reposts INTEGER,
    memo TEXT, submitter TEXT, topics TEXT, first_seen TEXT, updated_at TEXT
);
"""
LINK_RE = re.compile(r"https?://(?:www\.)?threads\.(?:com|net)/@?([\w.]+)?/?(?:post|t)/([\w-]+)", re.I)


def pick(row, *names):
    for k, v in row.items():
        key = (k or "").replace(" ", "").lower()
        if any(n in key for n in names) and (v or "").strip():
            return v.strip()
    return ""


def num(v):
    v = re.sub(r"[^\d.천만kK]", "", v or "")
    if not v:
        return None
    mult = 10000 if "만" in v else 1000 if ("천" in v or v.lower().endswith("k")) else 1
    try:
        return int(float(re.sub(r"[천만kK]", "", v)) * mult)
    except ValueError:
        return None


def read_sources():
    texts = []
    cfg_path = ROOT / "site" / "site_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    url = (cfg.get("threads_sheet_csv") or "").strip()
    if url:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as r:
                texts.append(("구글 시트", r.read().decode("utf-8-sig")))
        except Exception as e:  # 시트를 못 읽어도 파일 입력은 계속
            print(f"⚠️ 구글 시트를 읽지 못했어요: {e}")
    local = ROOT / "threads_links.csv"
    if local.exists():
        texts.append(("threads_links.csv", local.read_text(encoding="utf-8-sig")))
    return texts


def main():
    conn = connect()
    conn.executescript(SCHEMA)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    new = total = 0
    for source, text in read_sources():
        for row in csv.DictReader(io.StringIO(text)):
            raw = pick(row, "링크", "link", "url", "주소")
            m = LINK_RE.search(raw)
            if not m:
                continue
            body = pick(row, "본문", "내용", "text", "글")
            # 본문이 비어 있으면 apify_threads.py 가 링크로 본문·숫자를 채운다
            pid = hashlib.sha1(m.group(2).encode()).hexdigest()[:16]
            exists = conn.execute("SELECT 1 FROM threads_saved WHERE id=?", (pid,)).fetchone()
            conn.execute(
                "INSERT INTO threads_saved VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "text=CASE WHEN excluded.text = '' THEN text ELSE excluded.text END, likes=COALESCE(excluded.likes, likes), replies=COALESCE(excluded.replies, replies), "
                "reposts=COALESCE(excluded.reposts, reposts), memo=excluded.memo, updated_at=excluded.updated_at",
                (pid, raw.split("?")[0], m.group(1) or "", body, num(pick(row, "좋아요", "like")),
                 num(pick(row, "답글", "댓글", "repl")), num(pick(row, "리포스트", "repost", "공유")),
                 pick(row, "메모", "memo", "이유"), pick(row, "이름", "올린", "name", "제출"),
                 ", ".join(t for t in topics_of(body) if t != "기타"), now, now))
            total += 1
            new += 0 if exists else 1
        print(f"✅ {source}: 읽음")
    conn.commit()
    print(f"완료: 쓰레드 글 {total}건 확인 (새 글 {new}건)")


if __name__ == "__main__":
    main()
