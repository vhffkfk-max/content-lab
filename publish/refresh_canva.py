"""안 고친 초안의 이미지와 캔바 사본을 지금 배치로 다시 만든다 (배치를 고친 뒤 한 번씩).

    python ai_request.py refresh_canva      # PC(local_ai.py)가 처리. 큐·캔바 토큰이 PC 쪽에 있어서 이렇게 쓴다

대표가 캔바에서 고친 사본은 건드리지 않는다. 옛 사본은 지우지 않고 '핫코노미 · 옛 초안' 폴더로 옮긴다.
새 편집 링크는 큐와 텔레그램으로.
"""
import os
import json
import sys

from common import OUTPUT_DIR, load_env
from publish import forms, notify
from publish.card_learn import QUEUE, load, save
from publish.canva import Canva, CanvaError
from publish.canva_copy import to_canva
from publish.layout_check import check

DRAFTS = OUTPUT_DIR / "cardnews" / "drafts"
OLD_FOLDER = "핫코노미 · 옛 초안"
EDITED_AFTER = 120


def main():
    load_env()
    queue = load(QUEUE, {"items": []})
    cv = Canva()
    old = cv.ensure_folder(OLD_FOLDER)
    done, kept = [], []
    for it in queue["items"]:
        c = it.get("canva") or {}
        folder = DRAFTS / it["id"]
        if not c.get("id") or it.get("status") != "drafted" or not (folder / "post.json").exists():
            continue
        try:
            d = cv._call("GET", f"designs/{c['id']}")["design"]
            upd = d.get("updated_at") or 0
            if upd - (d.get("created_at") or upd) >= EDITED_AFTER:
                kept.append(it.get("title", it["id"]))
                continue
            post = json.loads((folder / "post.json").read_text(encoding="utf-8"))
            css, slides = forms._styled(post)
            problems = check(slides, css)
            if problems:
                print("⚠️ 겹침이 남아 건너뜀:", it["id"], problems[:2])
                continue
            forms.make(post, folder, it["id"])
            new = to_canva(forms.make_canva(post, folder / f"{it['id']}.pptx"), f"[초안] {post.get('title', it.get('topic', ''))}"[:50])
            cv.move(c["id"], old)
            it["canva"] = {"id": new["id"], "edit_url": new["urls"]["edit_url"], "replaced": c["id"]}
            save(QUEUE, queue)   # 하나 끝날 때마다 저장 — 중간에 끊겨도 같은 사본을 또 만들지 않게
            done.append(it)
            print("✅", it["id"], new["id"])
        except (CanvaError, OSError, ValueError) as e:
            print("⚠️", it["id"], e)
    lines = [f"🎨 캔바 사본을 새 배치로 다시 만들었어요 ({len(done)}개, 옛 사본은 '{OLD_FOLDER}' 폴더로)"]
    lines += [f"\n{it.get('title', it['id'])}\n{it['canva']['edit_url']}" for it in done[-8:]]
    if kept:
        lines.append(f"\n대표님이 고친 사본 {len(kept)}개는 그대로 뒀어요.")
    if (done or kept) and os.environ.get("WATCH_ALERTS") == "1":  # 봇엔 올릴 콘텐츠만 (2026-11-13 대표 요청) — WATCH_ALERTS=1 이면 다시 보냄
        notify.send("\n".join(lines))
    print(f"다시 만듦 {len(done)}개, 고친 사본 유지 {len(kept)}개")


if __name__ == "__main__":
    sys.exit(main())
