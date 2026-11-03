"""PC 크롤러의 깃허브 올리기·받기 — 개발 폴더에서 수정 중인 코드를 절대 치우지 않는다 (threads_watch.py, tg_live.py).

크롤러가 개발 폴더에서 돌기 때문에 pull --autostash 를 쓰면 작업 중인 수정이 stash 로 사라지곤 했다 (2026-11-01).
- publish: 임시 인덱스로 origin/main 위에 지정한 파일만 얹어 바로 push. 작업 폴더·스테이지를 안 건드리고, 겹치면 PC 파일이 이긴다.
- pull: fast-forward 만. 들어오는 파일과 겹치는 결과물(REGENERATED)은 되돌리고, 겹치는 코드 수정이 있으면 이번엔 안 받는다.
"""
import os
import re
import subprocess
import tempfile

from common import ROOT

REGENERATED = re.compile(r"^(?:output/site/|data/insta\.db$|data/free_crawl\.json$)")   # 다시 만들어지는 파일 — 되돌려도 잃는 것 없음


def git(*args, env=None):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="ignore",
                       env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.returncode, (r.stdout + r.stderr).strip()


def publish(files, message):
    """files 를 origin/main 위에 커밋해 올린다 → '완료' / '바뀐 것 없음' / '실패: ...'."""
    files = [f for f in files if (ROOT / f).exists()]
    out = "올릴 파일 없음"
    for _ in range(3):   # 그사이 다른 곳이 먼저 올렸으면 새로 받아 다시
        code, out = git("fetch", "-q", "origin", "main")
        if code != 0:
            continue
        # 커밋 하나로 고정한다. origin/main 은 다른 프로세스의 fetch·push 로 언제든 움직이는데, 다시 읽으면 옛 파일 묶음이 새 커밋 위에 얹혀 그사이 올라온 것을 되돌린다 (2026-11-03 d9b769c)
        base = git("rev-parse", "origin/main")[1]
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "GIT_INDEX_FILE": os.path.join(tmp, "index")}
            git("read-tree", base, env=env)
            code, out = git("add", "--", *files, env=env)
            if code != 0:
                return f"실패: {out[-200:]}"
            _, tree = git("write-tree", env=env)
        if tree == git("rev-parse", f"{base}^{{tree}}")[1]:
            return "바뀐 것 없음"
        code, commit = git("commit-tree", tree, "-p", base, "-m", message)
        if code != 0:
            return f"실패: {commit[-200:]}"
        code, out = git("push", "-q", "origin", f"{commit}:refs/heads/main")
        if code == 0:
            return "완료"
    return f"실패: {out[-200:]}"


def pull():
    """개발 폴더를 origin/main 까지 앞으로 → '완료' / '받을 것 없음' / '보류: ...'. stash 는 쓰지 않는다."""
    code, out = git("fetch", "-q", "origin", "main")
    if code != 0:
        return f"보류: {out[-200:]}"
    if git("rev-parse", "--abbrev-ref", "HEAD")[1] != "main":
        return "보류: main 브랜치가 아님"
    if git("merge-base", "--is-ancestor", "HEAD", "origin/main")[0] != 0:
        return "보류: 아직 안 올린 커밋이 있음"
    incoming = set(git("diff", "--name-only", "HEAD", "origin/main")[1].splitlines())
    if not incoming:
        return "받을 것 없음"
    overlap = incoming & set(git("diff", "--name-only", "HEAD")[1].splitlines())
    blocked = [f for f in overlap if not REGENERATED.match(f)]
    if blocked:
        return f"보류: 수정 중인 파일과 겹침 ({', '.join(sorted(blocked)[:5])})"
    if overlap:
        git("restore", "--source=HEAD", "--staged", "--worktree", "--", *overlap)
    code, out = git("merge", "-q", "--ff-only", "origin/main")
    return "완료" if code == 0 else f"보류: {out[-200:]}"
