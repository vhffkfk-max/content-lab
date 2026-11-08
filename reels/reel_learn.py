"""릴스 성과 틀 (카드뉴스 publish/card_learn.py 의 릴스판). 인스타 내부 API는 쓰지 않는다.

- 영상을 완성하면 log_made 가 기록한다: ~/content-lab-reels/reel_log.json
- 사용자가 인사이트 숫자를 ~/content-lab-reels/성과.csv 에 적는다.
  열: 폴더,조회,저장,공유,댓글,평균시청초,길이초 ('폴더'는 보드 폴더 이름)
- report 가 형식·첫 문장 유형별 점수를 낸다. 점수 = (저장 + 2×공유 + 댓글) / 조회 × 100, 시청률 = 평균시청초 / 길이초
- 유형별 MIN 개 미만이면 대본에 아무것도 반영하지 않는다.
"""
import csv
import json
import pathlib
import re
import statistics as st
from datetime import datetime

DIR = pathlib.Path.home() / "content-lab-reels"
LOG, CSV, STATS = DIR / "reel_log.json", DIR / "성과.csv", DIR / "reel_stats.json"
MIN = 3


def _load(f, default):
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def hook_type(line):
    if re.search("[\"“”'‘’]", line or ""):
        return "실명 한마디"
    if re.search(r"\d", line or ""):
        return "숫자"
    return "단정"


def log_made(out, account, topic, fmt):
    state = _load(pathlib.Path(out) / "대본.json", {})
    cuts = (state.get("script") or {}).get("cuts") or [{}]
    log = _load(LOG, {})
    log[pathlib.Path(out).name] = {"account": account, "topic": topic, "format": fmt, "hook": cuts[0].get("cap", ""), "closer": cuts[-1].get("cap", ""),
                                   "made": datetime.now().strftime("%Y-%m-%d %H:%M")}
    LOG.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


def _rows():
    if not CSV.exists():
        return []
    log, out = _load(LOG, {}), []
    with CSV.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            info = log.get((r.get("폴더") or "").strip())
            try:
                views, saves, shares, comments = (float(r[k]) for k in ("조회", "저장", "공유", "댓글"))
                watch = float(r["평균시청초"]) / float(r["길이초"])
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                continue
            if info and views > 0:
                out.append({**info, "score": (saves + 2 * shares + comments) / views * 100, "watch": watch})
    return out


def report():
    rows = _rows()

    def group(key):
        res = {}
        for name in {key(r) for r in rows}:
            v = [r for r in rows if key(r) == name]
            res[name] = {"n": len(v), "score": round(st.mean(x["score"] for x in v), 2), "watch": round(st.mean(x["watch"] for x in v), 2)}
        return res
    out = {"videos": len(rows), "format": group(lambda r: r["format"]), "hook": group(lambda r: hook_type(r["hook"]))}
    if DIR.exists():
        STATS.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def prompt_notes():
    hooks = {k: v for k, v in report()["hook"].items() if v["n"] >= MIN}
    if len(hooks) < 2:
        return ""
    best = max(hooks, key=lambda k: hooks[k]["score"])
    return f"[내 릴스 성과] 첫 문장 유형 중 '{best}'이 저장·공유 점수가 가장 높았습니다 ({hooks[best]['n']}개 평균 {hooks[best]['score']}). 사실에 맞을 때만 우선하세요."


if __name__ == "__main__":
    print(json.dumps(report(), ensure_ascii=False, indent=1))
