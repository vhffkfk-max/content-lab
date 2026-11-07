"""말희아빠 스튜디오 명령.

    python studio.py 전체분석            백업을 읽고 짝짓고 패턴 보고서를 만듭니다
    python studio.py 점검                백업 폴더 형식만 확인합니다
    python studio.py 새글                RSS·바레이션으로 새 글 목록을 갱신합니다
    python studio.py 만들기 <이름|키|최신> [--카드만] [--릴스만] [--차트없이]
    python studio.py 다시 <결과폴더> [--카드만] [--릴스만]    원고.json 을 고친 뒤 그대로 다시 만듭니다
    python studio.py 캡컷 <결과폴더>    릴스를 캡컷 프로젝트로 넣습니다 (켜져 있으면 닫았다가 다시 엽니다)
    python studio.py 캔바 <결과폴더> [--미리보기]    캔바용.pptx 를 캔바 '오뉴월드 · 초안' 폴더로 보내고 편집 주소를 줍니다
"""
import argparse
import json
import os
import pathlib
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from studio import analyze, feed, ig_export, material, naver_backup  # noqa: E402
from studio.paths import ANALYSIS, BACKUP_IG, BACKUP_NAVER, RESULT, load_json  # noqa: E402

KST = timezone(timedelta(hours=9))


def cmd_analyze(a):
    r = analyze.analyze()
    print((ANALYSIS / "패턴_보고서.md").read_text(encoding="utf-8"))
    print(f"결과: {ANALYSIS / '패턴_보고서.md'}, 짝.csv, 패턴.json, 백업_점검.md")
    return r


def cmd_check(a):
    _, n = naver_backup.read_all(BACKUP_NAVER)
    _, i = ig_export.read_all(BACKUP_IG)
    text = analyze.check_md(n, i)
    (ANALYSIS / "백업_점검.md").write_text(text, encoding="utf-8")
    print(text)


def cmd_feed(a):
    rows, info = feed.update()
    print(json.dumps(info, ensure_ascii=False))
    print(feed.dumps(rows, a.n))


def _patterns():
    r = load_json(ANALYSIS / "패턴.json")
    if not r or not r.get("posts"):
        return ""
    return json.dumps({k: r.get(k) for k in ("mode", "kinds", "slides_median", "topics", "features_pct", "performance")}, ensure_ascii=False)


def _charts(mat, folder):
    """결과 폴더 안으로 원본을 그대로 복사하고 바이트가 같은지 본다."""
    d = pathlib.Path(folder) / "차트원본"
    d.mkdir(parents=True, exist_ok=True)
    charts, hashes = {}, {}
    for p in mat["charts"]:
        dst = d / p.name
        shutil.copy2(p, dst)
        if material.md5(dst) != material.md5(p):
            raise SystemExit(f"차트 복사본이 원본과 달라요: {p.name}")
        charts[p.name], hashes[p.name] = dst, material.md5(p)
    return charts, hashes


def _cover(mat, s, folder):
    from studio import covers
    if mat["cover"]:
        return mat["cover"], None
    found = load_json(pathlib.Path(folder) / "표지_출처.json")
    old = next(pathlib.Path(folder).glob("표지_위키미디어.*"), None)
    if found and old:
        return old, found
    return covers.find(s.cover_queries, folder)


def _render(s, mat, folder, want_card, want_reel, notes):
    from studio import card, reel
    folder = pathlib.Path(folder)
    charts, hashes = _charts(mat, folder)
    cover, credit = _cover(mat, s, folder)
    note = mat["info"].get("chart_note", "원본 차트")
    from studio import chartmark, write as _w
    ctx = {}
    for c in s.slides:
        if c.chart:
            ctx.setdefault(c.chart, []).append(" / ".join([c.title, *c.lines, *c.hand, *c.red]))
    desc = mat["info"].get("charts", {})
    marks = chartmark.load_or_make(mat["folder"], charts, {k: f"{desc.get(k, '')}\n장면: " + " | ".join(v) for k, v in ctx.items()}, _w.source_numbers(mat))
    report = [f"제목: {mat['info'].get('title', '')}", f"기준: {s.basis}", f"표지 사진: {'재료 폴더' if cover and not credit else (credit['title'] + ' / ' + credit['license'] + ' / ' + credit['page']) if credit else '없음 (기본 배경)'}", ""]
    report += ["[원고에 남은 문제]", *notes, ""] if notes else []
    report += ["[올리기 전 확인]", *[f"- {x}" for x in s.check], ""]
    report += ["[차트 원본 확인] " + ", ".join(f"{k} md5 {v}" for k, v in hashes.items()), ""]
    if want_card:
        r = card.build(s, charts, cover, folder / "카드뉴스", note=note, marks=marks)
        (folder / "카드뉴스" / "캡션.txt").write_text(card.caption_text(s, credit), encoding="utf-8")
        rows, missing = card.verify_pptx(r["pptx"], hashes)
        report += ["[카드뉴스] " + f"{len(r['images'])}장, 넘침: " + (", ".join(r["problems"]) or "없음"),
                   "캔바용 PPTX 장별 글상자/그림: " + " ".join(f"{x['slide']}장 {x['textboxes']}/{x['pictures']}" for x in rows),
                   "PPTX 속 차트 원본 일치: " + ("빠짐 " + ", ".join(missing) if missing else "모두 일치"), ""]
    if want_reel:
        rr = reel.build(s, charts, cover, folder / "릴스", note=note, marks=marks)
        pack, bad = reel.pack_capcut(folder / "릴스", s, rr["scenes"], charts, hashes)
        report += ["[릴스] " + f"{rr['duration']}초, 화면 넘침: " + (", ".join(rr["problems"]) or "없음"), "받아쓰기에서 안 들린 숫자: " + (", ".join(rr["miss"]) or "없음"), "받아쓰기: " + rr["heard"],
                   f"캡컷 폴더: {pack}", "차트 바이트 확인: " + ("다름 " + ", ".join(bad) if bad else "원본과 같음"), ""]
    (folder / "확인목록.txt").write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report))
    print("폴더:", folder)
    print("게시는 사람이 확인한 뒤 직접 해 주세요 (자동 게시 없음).")


def cmd_make(a):
    from studio import write
    d = material.prepare(a.name)
    mat = material.load(d)
    if not mat["charts"] and not a.no_chart:
        raise SystemExit(f"차트가 없어요. {d} 에 블로그 원본 차트를 '차트1.png' 처럼 넣고 다시 실행해 주세요.\n차트 없이 만들려면 --차트없이 를 붙이세요.")
    s, left = write.make(mat, _patterns())
    slug = re.sub(r"[^0-9A-Za-z가-힣]+", "_", mat["info"].get("title") or d.name)[:24]
    folder = RESULT / f"{datetime.now(KST):%Y%m%d_%H%M}_{slug}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "원고.json").write_text(json.dumps({"material": d.name, "script": s.model_dump()}, ensure_ascii=False, indent=1), encoding="utf-8")
    if left:
        print("문제가 남아 그림·영상을 만들지 않았어요:", *left, sep="\n  ")
        (folder / "확인목록.txt").write_text("[막힌 문제]\n" + "\n".join(left), encoding="utf-8")
        raise SystemExit(f"{folder / '원고.json'} 을 고친 뒤 `python studio.py 다시 \"{folder}\"` 로 만들 수 있어요.")
    _render(s, mat, folder, not a.reel_only, not a.card_only, [])


def cmd_rebuild(a):
    from studio import write
    folder = _result(a.folder)
    saved = json.loads((folder / "원고.json").read_text(encoding="utf-8"))
    s = write.Script(**saved["script"])
    mat = material.load(material.prepare(saved["material"]))
    notes = write.check(s, mat)
    if notes:
        print("확인이 필요한 부분 (그래도 다시 만듭니다):", *notes, sep="\n  ")
    _render(s, mat, folder, not a.reel_only, not a.card_only, notes)


def _result(name):
    folder = pathlib.Path(name)
    return folder if folder.is_absolute() else RESULT / name


def cmd_canva(a):
    from studio import canva_send
    folder = _result(a.folder)
    saved = json.loads((folder / "원고.json").read_text(encoding="utf-8"))
    mat = material.load(material.prepare(saved["material"]))
    title = f"[오뉴월드] {saved['script']['keyword']} {mat['info'].get('date', '')}"
    r = canva_send.send(folder / "카드뉴스" / "캔바용.pptx", title, folder / "카드뉴스" / "캔바_미리보기" if a.preview else None)
    (folder / "카드뉴스" / "캔바주소.txt").write_text(r["edit_url"], encoding="utf-8")
    print("캔바 편집 주소:", r["edit_url"])
    if a.preview:
        print("캔바가 그린 미리보기:", r["pages"], "장")


def cmd_capcut(a):
    from studio import capcut_draft
    folder = _result(a.folder)
    pack = folder / "릴스" / "캡컷용"
    still = pack / "장면" / "c1.jpg"
    kinds = [sc["kind"] for sc in json.loads((folder / "원고.json").read_text(encoding="utf-8"))["script"]["reel"]]
    dark = set(range(len(kinds)))   # 오뉴월드 틀: 자막 자리(아래 말풍선)는 검은 바탕이라 흰 글씨
    from studio.reel import CAP_Y
    if capcut_draft.is_running() and not capcut_draft.ctl("busy")[0]:
        raise SystemExit("지금 캡컷을 쓰고 계신 것 같아 닫지 않았어요. 다른 창으로 옮긴 뒤 다시 실행해 주세요.")
    if capcut_draft.is_running():   # 켜 둔 채 목록을 고치면 덮어써질 수 있어 먼저 닫는다 (캡컷이 스스로 저장)
        ok, msg = capcut_draft.ctl("close")
        print("캡컷 닫기:", msg)
        if not ok:
            raise SystemExit("캡컷이 닫히지 않았어요. 저장 확인 창이 떠 있는지 봐 주세요.")
    made, info = capcut_draft.install(pack, "오뉴월드_" + folder.name, cover=still, dark_scenes=dark, caption_y=round((960 - CAP_Y) / 960, 3))
    print("캡컷 열기:", capcut_draft.ctl("open")[1])
    print(f"캡컷 프로젝트를 만들었어요: {made.name} (장면 {info['scenes']}개, 자막 {info['captions']}줄, {info['seconds']}초)")
    print("캡컷을 열면 프로젝트 목록에 보입니다. 결과 폴더를 지우거나 옮기면 파일을 다시 연결해야 해요.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("전체분석").set_defaults(fn=cmd_analyze)
    sub.add_parser("점검").set_defaults(fn=cmd_check)
    f = sub.add_parser("새글")
    f.add_argument("-n", type=int, default=20)
    f.set_defaults(fn=cmd_feed)
    for name, fn in (("만들기", cmd_make), ("다시", cmd_rebuild)):
        m = sub.add_parser(name)
        m.add_argument("name" if name == "만들기" else "folder")
        m.add_argument("--카드만", dest="card_only", action="store_true")
        m.add_argument("--릴스만", dest="reel_only", action="store_true")
        if name == "만들기":
            m.add_argument("--차트없이", dest="no_chart", action="store_true")
        m.set_defaults(fn=fn)
    cc = sub.add_parser("캡컷")
    cc.add_argument("folder")
    cc.set_defaults(fn=cmd_capcut)
    c = sub.add_parser("캔바")
    c.add_argument("folder")
    c.add_argument("--미리보기", dest="preview", action="store_true")
    c.set_defaults(fn=cmd_canva)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    main()
