"""지금 쓸 거리 영구 보관 — hot_now.json 은 최근 120번만 남으므로, 올라온 글감을 달별 파일에 지우지 않고 쌓는다. AI 없음.

    python hot_archive.py             # 지금 hot_now.json 을 합침 (local_ai.py 가 10분마다)
    python hot_archive.py --backfill  # git 기록의 예전 hot_now.json 까지 한 번 합침

→ output/site/hot_archive/index.json (달 목록) + YYYY-MM.json (글감). 같은 제목은 처음 올라온 것 하나만.
"""
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
HOT = ROOT / "output" / "site" / "hot_now.json"
DIR = ROOT / "output" / "site" / "hot_archive"
KST = timezone(timedelta(hours=9))
FILE = "output/site/hot_now.json"


def month_of(md, ref):
    """'11/09' 에 연도를 붙인다. 기준일보다 미래인 달이면 작년."""
    m = int(md[:2])
    return f"{ref.year - 1 if m > ref.month else ref.year}-{m:02d}"


def load_all():
    return {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in DIR.glob("20*.json")}


def merge(store, seen, hist, ref):
    added = 0
    for run in reversed(hist):      # 오래된 것부터: 같은 제목은 처음 올라온 날에 남긴다
        for i, p in enumerate((run.get("picks") or [])[:3]):
            title = p.get("title")
            if not title or title in seen:
                continue
            seen.add(title)
            t = p.get("time") or run["time"]
            store.setdefault(month_of(t, ref), []).append({**p, "time": t, "run": run["time"], "i": i})
            added += 1
    return added


def history():
    log = subprocess.run(["git", "log", "--format=%h %cI", "--", FILE], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True).stdout
    for line in reversed(log.splitlines()):
        sha, at = line.split()
        r = subprocess.run(["git", "show", f"{sha}:{FILE}"], cwd=ROOT, capture_output=True)
        try:
            yield json.loads(r.stdout.decode("utf-8")), datetime.fromisoformat(at).astimezone(KST)
        except ValueError:
            continue


def main():
    DIR.mkdir(parents=True, exist_ok=True)
    store = load_all()
    seen = {p["title"] for rows in store.values() for p in rows}
    added = 0
    if "--backfill" in sys.argv:
        for hist, ref in history():
            added += merge(store, seen, hist, ref)
    try:
        added += merge(store, seen, json.loads(HOT.read_text(encoding="utf-8")), datetime.now(KST))
    except (OSError, ValueError) as e:
        print("hot_now.json 읽기 실패:", e)
        return
    if added or not (DIR / "index.json").exists():
        for month, rows in store.items():
            rows.sort(key=lambda p: p["time"], reverse=True)
            (DIR / f"{month}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=0), encoding="utf-8")
        idx = [{"month": m, "count": len(store[m])} for m in sorted(store, reverse=True)]
        (DIR / "index.json").write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")
    print(f"쓸 거리 보관: 새로 {added}개, 전체 {len(seen)}개")


if __name__ == "__main__":
    main()
