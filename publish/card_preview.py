"""카드 초안 미리보기 → 저장소 card-previews 가지 (연구소 사이트 '카드뉴스 발행'이 보여 줌).

    push("20261105-1101-news", files)     # 초안 1개 (draft_card 가 부름)
    python -m publish.card_preview        # 보관 기간 안의 초안을 한 번에 채움

- 폭 540px 저화질은 화면용(<id>/<n>.jpg, 3일), 원본은 사이트 '이미지 저장'용(<id>/full/<n>.jpg, 2일). 1시간마다 만들어서 짧게 둔다.
- 가지에는 커밋을 하나만 둔다(부모 없는 커밋을 덮어씀). 지난 그림이 기록에 쌓이지 않아 저장소가 안 커지고, main 과 작업 폴더는 건드리지 않는다.
- 공개 저장소라 주소를 알면 볼 수 있다. 사이트 목록은 암호 뒤에 있지만 그림 자체는 비공개가 아니다.
"""
import io
import os
import pathlib
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta

from PIL import Image

from common import ROOT

BRANCH = "card-previews"
WIDTH, QUALITY = 540, 72
KEEP_DAYS = 3
KEEP_FULL_DAYS = 2   # 원본은 무거워서 짧게
IDENT = ["-c", "user.name=content-lab-bot", "-c", "user.email=content-lab-bot@users.noreply.github.com"]


def git(*args, env=None, data=None):
    r = subprocess.run(["git", *IDENT, *args], cwd=ROOT, capture_output=True, input=data, env=env,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.returncode, r.stdout.decode("utf-8", "ignore").strip() or r.stderr.decode("utf-8", "ignore").strip()


def small(path):
    im = Image.open(path).convert("RGB")
    im = im.resize((WIDTH, round(im.height * WIDTH / im.width)), Image.LANCZOS)
    b = io.BytesIO()
    im.save(b, "JPEG", quality=QUALITY, optimize=True)
    return b.getvalue()


def _expired(path, cutoff):
    m = re.match(r"(\d{8})-", path)
    return bool(m) and m[1] < cutoff


def _gone(name, cutoff, full_cutoff):
    return _expired(name, full_cutoff if "/full/" in name else cutoff)


def push(drafts, extra=None):
    """drafts: {초안 id: [그림 경로...]}, extra: {가지 안 경로: bytes}(추천안 표지 시안) → '완료' / '실패: ...'. 다른 PC 폴더가 올린 것도 지우지 않게 가지의 현재 내용 위에 얹는다."""
    cutoff = f"{datetime.now() - timedelta(days=KEEP_DAYS):%Y%m%d}"
    full_cutoff = f"{datetime.now() - timedelta(days=KEEP_FULL_DAYS):%Y%m%d}"
    blobs = dict(extra or {})
    for did, files in drafts.items():
        for i, f in enumerate(files, 1):
            blobs[f"{did}/{i}.jpg"] = small(f)
            if not _expired(did, full_cutoff):
                blobs[f"{did}/full/{i}.jpg"] = pathlib.Path(f).read_bytes()
    out = "올릴 것 없음"
    for _ in range(3):   # 그사이 다른 곳이 먼저 올렸으면 새로 받아 다시
        code, out = git("ls-remote", "origin", f"refs/heads/{BRANCH}")
        if code != 0:
            continue
        old = out.split()[0] if out else ""
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "GIT_INDEX_FILE": os.path.join(tmp, "index")}
            if old:
                code, out = git("fetch", "-q", "--depth", "1", "origin", f"refs/heads/{BRANCH}")
                if code != 0:
                    continue
                git("read-tree", "FETCH_HEAD", env=env)
            _, names = git("ls-files", env=env)
            for name in names.splitlines():
                if _gone(name, cutoff, full_cutoff):
                    git("update-index", "--force-remove", name, env=env)
            for name, data in blobs.items():
                code, sha = git("hash-object", "-w", "--stdin", data=data)
                if code != 0:
                    return f"실패: {sha[-200:]}"
                git("update-index", "--add", "--cacheinfo", f"100644,{sha},{name}", env=env)
            _, tree = git("write-tree", env=env)
        code, commit = git("commit-tree", tree, "-m", "카드 초안 미리보기")
        if code != 0:
            return f"실패: {commit[-200:]}"
        lease = f"--force-with-lease=refs/heads/{BRANCH}:{old}"   # 내가 읽은 뒤 바뀌었으면 거절돼 다시 시도
        code, out = git("push", "-q", lease, "origin", f"{commit}:refs/heads/{BRANCH}")
        if code == 0:
            return "완료"
    return f"실패: {out[-200:]}"


def backfill():
    from common import OUTPUT_DIR
    cutoff = f"{datetime.now() - timedelta(days=KEEP_DAYS):%Y%m%d}"
    drafts = {}
    for d in sorted((OUTPUT_DIR / "cardnews" / "drafts").iterdir()):
        if d.is_dir() and not _expired(d.name, cutoff):
            files = sorted(d.glob(f"{d.name}-*.jpg"), key=lambda p: int(p.stem.rsplit("-", 1)[1]))
            if files:
                drafts[d.name] = files
    print(f"초안 {len(drafts)}개, 그림 {sum(map(len, drafts.values()))}장")
    print(push(drafts))


if __name__ == "__main__":
    sys.exit(backfill())
