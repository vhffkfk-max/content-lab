"""인스타에 넘길 '공개 주소' 만들기: 깃허브 Release 첨부 파일로 잠깐 올리고, 발행 뒤 지운다 (저장소가 공개라 무료).

    from publish.hosting import upload, cleanup
    urls = upload(["a.jpg", "b.jpg"], tag="publish-20261027-1")
    ... 발행 ...
    cleanup(tag)
gh CLI 를 쓴다 (깃허브 실행에서는 GITHUB_TOKEN, 내 PC에서는 gh auth login).
"""
import pathlib
import subprocess

REPO = "vhffkfk-max/content-lab"


def _gh(*args):
    return subprocess.run(["gh", *args, "--repo", REPO], capture_output=True, text=True, encoding="utf-8", errors="ignore")


def upload(paths, tag):
    r = _gh("release", "create", tag, *map(str, paths), "--title", f"발행용 임시 파일 {tag}",
            "--notes", "인스타 발행용 임시 파일 — 발행 뒤 자동 삭제", "--prerelease")
    if r.returncode != 0:
        raise RuntimeError(f"임시 파일 올리기 실패: {r.stderr[-300:]}")
    return [f"https://github.com/{REPO}/releases/download/{tag}/{pathlib.Path(p).name}" for p in paths]


def cleanup(tag):
    _gh("release", "delete", tag, "--yes", "--cleanup-tag")
