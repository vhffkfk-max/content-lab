"""만든 영상·이미지를 텔레그램으로 자동 전송 (2분마다, 작업 스케줄러 content-lab-tg-watch).

어느 제작기로 만들었든 완성 폴더에 새 결과물이 생기면 보낸다.
이미 보낸 것은 ~/.content-lab-ai/tg_sent.json 에 내용 지문으로 적어 두어 두 번 보내지 않는다
(영상 연구소·카드 초안처럼 스스로 보내는 곳도 publish.notify 가 같은 장부에 적는다).
처음 실행하면 지금 있는 파일은 보낸 것으로만 적고 넘어간다 (예전 것 폭탄 방지).

    python -m publish.tg_watch          # 한 번 훑기
    python -m publish.tg_watch --dry    # 보낼 것만 보여 주기
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from publish import notify  # noqa: E402

HOME = Path.home()
DESK = HOME / "Desktop"
DEV = DESK / "솔개" / "insta-research"
VIDEO_AGE = 5 * 60    # 다 쓰이고 제작기가 직접 보낼 시간을 준 뒤에 본다
PHOTO_AGE = 2 * 60
SKIP = ("테스트", "test", "자막없는", "1차", "_tmp", "임시")

VIDEOS = [  # (폴더, 패턴)
    (DESK / "릴스 완성영상", "*.mp4"),
    (DEV / "output" / "reels" / "duo", "*/영상.mp4"),
    (DEV / "ohneworld" / "결과", "*/릴스/영상.mp4"),
    (DESK / "솔개" / "hotconomy-reels" / "outputs", "A_*.mp4"),
]
CARD_SETS = [  # 카드 묶음 폴더 (안의 카드_*.jpg 를 앨범으로)
    (DEV / "ohneworld" / "결과", "*/카드뉴스"),
]


def ready(p, age):
    try:
        return time.time() - p.stat().st_mtime > age and p.stat().st_size > 0
    except OSError:
        return False


def skip(p):
    return any(s.lower() in str(p).lower() for s in SKIP)


def label(p):
    """텔레그램 설명 한 줄: 폴더·파일 이름에서 주제를 뽑는다."""
    name = p.stem if p.stem not in ("영상", "카드뉴스") else p.parent.name
    if name == "릴스":
        name = p.parent.parent.name
    return name.replace("_", " ")


def todo():
    vids, sets = [], []
    for base, pat in VIDEOS:
        if base.exists():
            vids += [p for p in base.glob(pat) if not skip(p)]
    for base, pat in CARD_SETS:
        if base.exists():
            for d in base.glob(pat):
                cards = sorted(d.glob("카드_*.jpg")) or sorted(d.glob("*.png"))
                if cards and not skip(d):
                    sets.append((d, cards[:10]))
    return vids, sets


def main(dry=False):
    from common import load_env
    load_env()
    load_env(DEV / ".env")
    sent = notify.load_sent()
    init = notify.SENT.with_name("tg_watch_init")
    first = not init.exists()
    vids, sets = todo()
    new = 0
    for p in sorted(vids, key=lambda x: x.stat().st_mtime):
        sent = notify.load_sent()   # 방금 보낸 것과 같은 내용의 사본은 건너뛰게 매번 다시 읽음
        k = notify.key(p)
        if k in sent or not ready(p, VIDEO_AGE):
            continue
        new += 1
        if first or dry:
            print(("기록만" if first and not dry else "보낼 영상"), p)
            if first and not dry:
                notify.mark([p])
            continue
        mb = p.stat().st_size / 1e6
        if mb > 49:
            ok = notify.send(f"🎬 영상이 나왔어요: {label(p)}\n크기 {mb:.0f}MB라 텔레그램(50MB 한도)으로는 못 보내요.\nPC 위치: {p}")
            ok and notify.mark([p])
        else:
            notify.send_video(p, f"🎬 영상이 나왔어요: {label(p)}\n확인한 뒤 직접 올려 주세요.")
    for d, cards in sets:
        sent = notify.load_sent()
        if all(notify.key(c) in sent for c in cards) or not all(ready(c, PHOTO_AGE) for c in cards):
            continue
        new += 1
        if first or dry:
            print(("기록만" if first and not dry else "보낼 카드"), d, len(cards), "장")
            if first and not dry:
                notify.mark(cards)
            continue
        notify.send_photos(cards, f"🖼 카드뉴스가 나왔어요: {label(d)} ({len(cards)}장)\n확인한 뒤 직접 올려 주세요.")
    if first and not dry:
        init.parent.mkdir(parents=True, exist_ok=True)
        init.write_text(time.strftime("%Y-%m-%d %H:%M"), encoding="utf-8")
    return new


if __name__ == "__main__":
    print("새 결과물", main(dry="--dry" in sys.argv), "개")
