"""대표가 고른 카드뉴스 초안 하나를 @hotconomy 에 올린다 (메타 공식 API).

    python ai_request.py publish id=20261101-1805-bignum     # 요청 → PC(local_ai.py)가 5분 안에 처리, 이렇게 쓴다
    python -m publish.publish_card <초안 id> --dry-run       # 올리지 않고 무엇이 올라갈지만 확인
    python -m publish.publish_card <초안 id> --yes           # 바로 올림

자동으로 고르지 않는다 — 초안 id 를 찍어 준 것만 올린다. 이미 올린 초안, 위험 표현 경고가 남은 초안은 거절한다.
이미지: 캔바에서 고쳤으면 고친 디자인을 내보내서(글자 깨짐 검사 포함), 안 고쳤으면 저장된 글을 지금 배치로 다시 그려서(겹침 검사 포함).
         캔바를 고쳤는데 못 가져오면 고치기 전 이미지로 올리지 않고 멈춘다.
순서: 임시 공개 주소(깃허브 Release) → 인스타 캐러셀 발행 → 임시 파일 삭제 → 큐에 기록 → 텔레그램 알림.
"""
import argparse
import os
import pathlib
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

from common import ROOT, load_env
from publish import hosting, notify
from publish.instagram import Instagram, PublishError

KST = timezone(timedelta(hours=9))
EDITED_AFTER = 120   # 캔바 사본을 만든 뒤 이만큼 지나서 바뀌었으면 고친 것 (card_learn 과 같은 기준)


def load_item(queue, did):
    for it in queue["items"]:
        if it["id"] == did:
            return it
    return None


def refuse_reason(it):
    if it.get("status") == "published" or (it.get("published") or {}).get("instagram"):
        return "이미 발행한 초안이에요."
    if it.get("warnings"):
        return "경고가 남아 있어요: " + " / ".join(it["warnings"])
    return ""


def canva_edited(it):
    """캔바 디자인 정보 → 고쳤으면 디자인 id, 아니면 None."""
    cid = (it.get("canva") or {}).get("id")
    if not cid:
        return None
    from publish.canva import Canva
    d = Canva()._call("GET", f"designs/{cid}")["design"]
    upd = d.get("updated_at") or 0
    return cid if upd - (d.get("created_at") or upd) >= EDITED_AFTER else None


def redraw(it):
    """저장된 글(post.json)을 지금 배치로 다시 그린다 — 옛 초안도 겹침 고친 배치로. 겹치면 멈춘다."""
    import json

    from publish import forms
    from publish.layout_check import check
    folder = ROOT / "output" / "cardnews" / "drafts" / it["id"]
    if not (folder / "post.json").exists():
        return [ROOT / f for f in it["files"]]
    post = json.loads((folder / "post.json").read_text(encoding="utf-8"))
    css, slides = forms._styled(post)
    problems = check(slides, css)
    if problems:
        raise RuntimeError("글자 겹침: " + " / ".join(problems[:3]))
    return forms.make(post, folder, it["id"])


def images(it):
    """올릴 이미지 경로. 캔바에서 고쳤으면 내보내서 받는다."""
    cid = canva_edited(it)
    if not cid:
        return redraw(it), "처음 초안 (지금 배치로 다시 그림)"
    from publish.canva import Canva
    out = ROOT / "output" / "cardnews" / "drafts" / it["id"] / "canva-final"
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for n, url in enumerate(Canva().export(cid, "jpg"), 1):
        p = out / f"{it['id']}-canva-{n}.jpg"
        with urllib.request.urlopen(url, timeout=120) as r:
            p.write_bytes(r.read())
        paths.append(p)
    return paths, "캔바에서 고친 이미지"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("id")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true", help="확인 없이 실제로 올림 (없으면 올리지 않음)")
    a = ap.parse_args()
    load_env()
    from publish.card_learn import QUEUE, load, save
    queue = load(QUEUE, {"items": []})
    it = load_item(queue, a.id)
    if not it:
        notify.send(f"❌ 발행 못 함: 초안 {a.id} 를 찾지 못했어요.")
        sys.exit(f"❌ 초안을 찾지 못했어요: {a.id}")

    def fail(head, reason):   # 사이트가 실패를 바로 보여 주도록 큐에도 남긴다 (올린 초안의 기록은 건드리지 않음)
        if not a.dry_run and it.get("status") != "published":
            it["publish_error"] = {"at": datetime.now(KST).isoformat(timespec="seconds"), "reason": str(reason)[:300]}
            save(QUEUE, queue)
        notify.send(f"❌ {head}: {it.get('title', a.id)}\n{reason}")
        sys.exit(f"❌ {reason}")

    why = refuse_reason(it)
    if why:
        fail("발행 안 함", why)
    try:
        paths, source = images(it)
    except Exception as e:   # 고친 내용을 잃고 올리지 않도록 여기서 멈춘다
        fail("발행 못 함", f"이미지 준비 실패: {e}")
    if [p for p in paths if not pathlib.Path(p).exists()]:
        fail("발행 못 함", "이미지 파일이 없어요.")
    ig = Instagram(os.environ["IG_USER_ID"], os.environ["IG_ACCESS_TOKEN"])
    print(f"제목: {it.get('title')}\n폼: {it.get('form')} / {len(paths)}장 ({source})\n오늘 발행 사용량: {ig.limit()}\n캡션 {len(it['caption'])}자:\n{it['caption'][:300]}")
    if a.dry_run or not a.yes:
        print("(올리지 않았어요)")
        return
    tag = f"publish-{it['id']}"
    try:
        urls = hosting.upload(paths, tag)
        media_id, link = ig.publish_carousel(urls, it["caption"])
    except (PublishError, RuntimeError) as e:
        fail("인스타 발행 실패", f"{e.reason} {e.detail}" if isinstance(e, PublishError) else str(e))
    finally:
        hosting.cleanup(tag)
    it["status"] = "published"
    it.pop("publish_error", None)
    it.setdefault("published", {})["instagram"] = {"media_id": media_id, "permalink": link,
                                                    "at": datetime.now(KST).isoformat(timespec="seconds"), "source": source}
    save(QUEUE, queue)
    print("✅ 발행:", link)
    notify.send(f"✅ 인스타 발행 완료: {it.get('title', a.id)}\n{source} {len(paths)}장\n{link}")


if __name__ == "__main__":
    sys.exit(main())
