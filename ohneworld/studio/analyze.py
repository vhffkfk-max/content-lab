"""패턴 분석: 백업 → 짝 → 특징 → 보고서.

성과 수치가 없으면 '자주 쓴 패턴'만 말한다. 있으면 같은 계정 안에서 비교하되 표본이 적으면 표시한다.
수치 파일(성과/수치.csv): 날짜,캡션앞부분,주소,도달,저장,좋아요,댓글,공유 (빈칸 허용)
"""
import csv
import pathlib
import re
import statistics as st
from collections import Counter
from datetime import datetime

from studio import ig_export, match, naver_backup
from studio.paths import ANALYSIS, BACKUP_IG, BACKUP_NAVER, DATA, METRICS, save_json

TOPICS = [("미국 개별주", r"나스닥|뉴욕증시|미국 주식|미 증시|테슬라|엔비디아|애플|인텔|아이온큐|가트너|덱스컴|마이크론"), ("한국 개별주", r"삼성전자|하이닉스|코스닥|씨에스윈드|오션플랜트|한미반도체"),
          ("지수·시황", r"코스피|S&P|지수|증시|시황"), ("금리·환율·물가", r"금리|환율|물가|CPI|연준|FOMC|국채|달러"), ("원자재·코인", r"금값|\b금\b|유가|WTI|비트코인|이더리움"),
          ("부동산·정책", r"부동산|집값|아파트|대통령|정부|선거")]
CHART = re.compile(r"지지|저항|추세선|수렴|박스권|채널|돌파|이탈|차트")


def topic_of(text):
    return next((name for name, rx in TOPICS if re.search(rx, text or "")), "기타")


def caption_features(c):
    first = (c or "").strip().split("\n")[0] if c else ""
    return {"첫줄_숫자": bool(re.search(r"\d", first)), "첫줄_질문": "?" in "\n".join((c or "").strip().split("\n")[:2]), "차트_언급": bool(CHART.search(c or "")),
            "체크표시": bool(re.search(r"[✔✅☑]", c or "")), "댓글_유도": "댓글" in (c or ""), "저장_유도": "저장" in (c or ""),
            "투자_고지": bool(re.search(r"투자\s?자문|투자 권유|투자 판단", c or "")), "텔레그램_언급": "텔레그램" in (c or "")}


def load_metrics(path, posts):
    """수치.csv → 게시물에 붙인다. 주소가 안 맞으면 날짜 + 캡션 앞부분으로 찾는다."""
    path = pathlib.Path(path)
    if not path.exists():
        return 0
    n = 0
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            nums = {k: int(re.sub(r"\D", "", row[h])) for h, k in (("도달", "reach"), ("저장", "saved"), ("좋아요", "likes"), ("댓글", "comments"), ("공유", "shares")) if re.sub(r"\D", "", row.get(h) or "")}
            if not nums:
                continue
            day, head = (row.get("날짜") or "")[:10], (row.get("캡션앞부분") or "").strip()
            same = [p for p in posts if (p.get("date") or "")[:10] == day]
            hit = [p for p in same if head and p.get("caption", "").strip().startswith(head)] or (same if len(same) == 1 else [])
            if hit:
                hit[0].setdefault("metrics", {}).update(nums)
                n += 1
    return n


def _rate(p):
    m = p.get("metrics") or {}
    return m["saved"] / m["reach"] if m.get("reach") and m.get("saved") is not None else None


def performance(posts, min_n=5):
    """특징별 저장률(저장/도달) 중앙값. 표본이 min_n 미만이면 결론 안 냄."""
    rated = [p for p in posts if _rate(p) is not None]
    groups = {"형식": lambda p: p["kind"], "주제": lambda p: p["topic"]}
    for k in ("첫줄_숫자", "첫줄_질문", "차트_언급", "체크표시"):
        groups[k] = lambda p, k=k: "있음" if p["features"][k] else "없음"
    out = {}
    for name, fn in groups.items():
        rows = {}
        for p in rated:
            rows.setdefault(fn(p), []).append(_rate(p))
        out[name] = {k: {"n": len(v), "median_save_rate": round(st.median(v) * 100, 2), "enough": len(v) >= min_n} for k, v in rows.items()}
    return {"rated": len(rated), "median_save_rate": round(st.median([_rate(p) for p in rated]) * 100, 2) if rated else None, "groups": out}


def analyze(naver_dir=BACKUP_NAVER, ig_dir=BACKUP_IG, out_dir=ANALYSIS, data_dir=DATA, metrics=METRICS):
    out_dir, data_dir = pathlib.Path(out_dir), pathlib.Path(data_dir)
    blogs, nrep = naver_backup.read_all(naver_dir)
    posts, irep = ig_export.read_all(ig_dir)
    for p in posts:
        p["features"] = caption_features(p.get("caption"))
        p["topic"] = topic_of(p.get("caption"))
    n_csv = load_metrics(metrics, posts)
    n_metric = sum(1 for p in posts if p.get("metrics"))
    save_json(data_dir / "네이버글.json", blogs)
    save_json(data_dir / "인스타게시물.json", posts)
    pairs = match.assign(blogs, posts, match.load_manual(out_dir / "수동짝.csv"))
    out_dir.mkdir(parents=True, exist_ok=True)
    by_b, by_p = {b["id"]: b for b in blogs}, {p["id"]: p for p in posts}
    with open(out_dir / "짝.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["단계", "점수", "시차(일)", "블로그id", "블로그날짜", "블로그제목", "게시물id", "게시물날짜", "형식", "캡션앞부분", "공통낱말"])
        for r in pairs:
            b, p = by_b.get(r["blog"], {}), by_p.get(r["post"], {})
            w.writerow([r["level"], r["score"], r["lag_days"], r["blog"], (b.get("date") or "")[:10], b.get("title", "")[:60], r["post"], (p.get("date") or "")[:10], p.get("kind", ""), (p.get("caption") or "")[:40].replace("\n", " "), " ".join(r["common"])])
    result = summarize(blogs, posts, pairs, nrep, irep, n_metric)
    result["metrics_from_csv"] = n_csv
    result["performance"] = performance(posts) if n_metric else None
    save_json(out_dir / "패턴.json", result)
    (out_dir / "패턴_보고서.md").write_text(report_md(result), encoding="utf-8")
    (out_dir / "백업_점검.md").write_text(check_md(nrep, irep), encoding="utf-8")
    return result


def _span(rows):
    ds = sorted(x["date"][:10] for x in rows if x.get("date"))
    if not ds:
        return None
    return {"from": ds[0], "to": ds[-1], "days": (datetime.fromisoformat(ds[-1]) - datetime.fromisoformat(ds[0])).days}


def summarize(blogs, posts, pairs, nrep, irep, n_metric):
    n = max(1, len(posts))
    paired = [r for r in pairs if r["level"] in ("확실", "수동")]
    paired_posts = {r["post"] for r in pairs}
    lags = [r["lag_days"] for r in paired if r["lag_days"] is not None]
    feats = Counter(k for p in posts for k, v in p["features"].items() if v)
    return {
        "mode": "성과 있음" if n_metric else "성과 없음", "metric_posts": n_metric,
        "blogs": len(blogs), "posts": len(posts), "blog_span": _span(blogs), "post_span": _span(posts),
        "pairs": {"확실": sum(r["level"] == "확실" for r in pairs), "수동": sum(r["level"] == "수동" for r in pairs), "검토": sum(r["level"] == "검토" for r in pairs),
                  "짝없는_게시물": len(posts) - len(paired_posts), "시차중앙값_일": round(st.median(lags), 2) if lags else None},
        "kinds": dict(Counter(p["kind"] for p in posts)),
        "slides_median": st.median([p["n_media"] for p in posts if p["kind"] == "캐러셀"] or [0]),
        "topics": dict(Counter(p["topic"] for p in posts).most_common()),
        "features_pct": {k: round(v / n * 100) for k, v in feats.most_common()},
        "weekday": dict(sorted(Counter("월화수목금토일"[datetime.fromisoformat(p["date"]).weekday()] for p in posts if p.get("date")).items(), key=lambda x: "월화수목금토일".index(x[0]))),
        "hour_top": Counter(datetime.fromisoformat(p["date"]).hour for p in posts if p.get("date")).most_common(5),
        "blog_images_median": st.median([len(b["images"]) for b in blogs] or [0]),
    }


def report_md(r):
    L = ["# 오뉴월드 패턴 보고서", "", f"- 분석 방식: **{r['mode']}**"]
    if r["blogs"] == 0 and r["posts"] == 0:
        return "\n".join(L + ["", "백업 파일이 아직 없습니다. `백업/네이버`, `백업/인스타` 에 넣고 다시 돌려 주세요."]) + "\n"
    bs, ps = r["blog_span"], r["post_span"]
    L += [f"- 블로그 글 {r['blogs']}개" + (f" ({bs['from']} ~ {bs['to']}, {bs['days']}일)" if bs else ""),
          f"- 오뉴월드 게시물 {r['posts']}개" + (f" ({ps['from']} ~ {ps['to']}, {ps['days']}일)" if ps else "")]
    if not bs or bs["days"] < 365 or not ps or ps["days"] < 365:
        L.append("- ⚠️ 기간이 1년이 안 됩니다. 1~2년 패턴으로 보기 어렵습니다.")
    p = r["pairs"]
    L += ["", "## 짝", f"- 확실 {p['확실']} · 수동 {p['수동']} · 검토 {p['검토']} · 짝 없는 게시물 {p['짝없는_게시물']}",
          f"- 블로그 → 인스타 시차 중앙값: {p['시차중앙값_일']}일", "- `짝.csv` 에서 '검토' 줄을 사람이 확인하고, 고칠 때는 `수동짝.csv` 를 씁니다.",
          "", "## 자주 쓴 패턴 (빈도)", f"- 형식: {r['kinds']}", f"- 캐러셀 장수 중앙값: {r['slides_median']}", f"- 주제: {r['topics']}", f"- 캡션 요소(%): {r['features_pct']}",
          f"- 요일: {r['weekday']}", f"- 많이 올린 시각(시, 개수): {r['hour_top']}"]
    L += ["", "## 성과"]
    pf = r.get("performance")
    if not pf:
        L += ["성과 수치가 없습니다. 위 내용은 **자주 쓴 패턴**이고, **잘 된 패턴이라고 말할 수 없습니다.**", "메타 공식 API 권한을 연결하거나 `성과/수치.csv` 를 채우면 같은 명령으로 이 칸이 채워집니다."]
    else:
        L += [f"수치가 있는 게시물 {r['metric_posts']}개, 저장률 계산 가능 {pf['rated']}개. 저장률(저장/도달) 중앙값 {pf['median_save_rate']}%.", "같은 계정 안의 비교이며 인과가 아닙니다. 주제·시기 영향이 섞입니다.", ""]
        for name, rows in pf["groups"].items():
            L.append(f"- {name}: " + ", ".join(f"{k} {v['median_save_rate']}% (n={v['n']}{'' if v['enough'] else ', 표본 적음'})" for k, v in rows.items()))
    return "\n".join(L) + "\n"


def check_md(n, i):
    L = ["# 백업 점검", "", "실제 백업 형식을 맞추기 위한 결과입니다. 글 내용은 넣지 않습니다.", "", "## 네이버", f"- 글 {n['posts']}개 (날짜 못 읽음 {n['no_date']}), 문서 파일 {n['docs']}, 사진·영상 파일 {n['media_files']}, 안 읽은 경로 {n['skipped_paths']}",
         f"- 모르는 확장자: {n['unknown_ext'] or '없음'}", f"- 글을 못 찾은 문서: {len(n['no_post'])}개 {n['no_post'][:10]}", f"- 오류: {n['errors'][:10] or '없음'}",
         "", "## 인스타", f"- 게시물 {i['posts']}개 (날짜 못 읽음 {i['no_date']}), 사진·영상 파일 {i['media_files']}, 안 읽은 경로(DM 등) {i['skipped_paths']}, 그 밖의 파일 {i['other_files']}",
         f"- 연 파일: {i['opened'] or '없음'}", f"- 인사이트 수치 줄: {i['insight_rows']}", f"- 오류: {i['errors'][:10] or '없음'}"]
    if i["html_files"] and not i["opened"]:
        L.append("- ⚠️ HTML 형식으로 받은 것 같습니다. 내보내기를 JSON 형식으로 다시 요청해 주세요.")
    return "\n".join(L) + "\n"
