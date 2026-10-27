"""발행 시험: 흑백 테스트 이미지 2장으로 캐러셀 1개를 실제로 올린다 (올린 뒤 대표가 인스타 앱에서 직접 삭제).

    python -m publish.test_publish        # 확인 질문 뒤 발행
"""
import os
import sys
import tempfile
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

from common import load_env
from publish import hosting
from publish.instagram import Instagram, PublishError
from publish.notify import send

FONT = "C:/Windows/Fonts/malgunbd.ttf"


def make(path, n):
    img = Image.new("RGB", (1080, 1350), "white")
    d = ImageDraw.Draw(img)
    big, small = ImageFont.truetype(FONT, 120), ImageFont.truetype(FONT, 44)
    d.text((90, 520), f"테스트 {n}/2", font=big, fill="black")
    d.text((90, 700), "자동 발행 시험 — 곧 지웁니다", font=small, fill="black")
    img.save(path, "JPEG", quality=92)


def main():
    load_env()
    if "--yes" not in sys.argv and input("@hotconomy 에 테스트 캐러셀을 실제로 올릴까요? (y/n) ").strip().lower() != "y":
        return
    tmp = tempfile.mkdtemp()
    paths = [os.path.join(tmp, f"test{n}.jpg") for n in (1, 2)]
    for n, p in enumerate(paths, 1):
        make(p, n)
    tag = "publish-test-" + datetime.now().strftime("%Y%m%d%H%M%S")
    urls = hosting.upload(paths, tag)
    print("임시 공개 주소:", urls[0])
    ig = Instagram(os.environ["IG_USER_ID"], os.environ["IG_ACCESS_TOKEN"])
    try:
        media_id, link = ig.publish_carousel(urls, "자동 발행 시험입니다. 곧 지웁니다.\n\n(정보 제공용이며 투자 권유가 아닙니다)")
        print("✅ 발행 성공:", link)
        send(f"✅ 인스타 발행 시험 성공\n{link}\n확인 뒤 인스타 앱에서 지워 주세요.")
    except PublishError as e:
        print("❌", e.reason, e.detail)
        send(f"❌ 인스타 발행 시험 실패\n{e.reason}")
    finally:
        hosting.cleanup(tag)


if __name__ == "__main__":
    main()
