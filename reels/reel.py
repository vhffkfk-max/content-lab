"""영상 제작 입구 하나. 예전 명령(make_reel.py 등)도 그대로 된다.

    python reels/reel.py 목록
    python reels/reel.py 대화극 "신용융자 담보비율" --style T
"""
import os
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import accounts  # noqa: E402


def command(name, topic, extra=()):
    a = accounts.ACCOUNTS[name]
    return [sys.executable, str(a["maker"]), *[x.replace("{topic}", topic) for x in a["args"]], *extra], a["cwd"]


def main(argv):
    if not argv or argv[0] in ("목록", "list"):
        for k, a in accounts.ACCOUNTS.items():
            print(f"{k}: {a['what']} / 음성 {a['voice']}{'' if a['maker'].exists() else ' (이 PC에 제작기 없음)'}")
        return 0
    if argv[0] not in accounts.ACCOUNTS or len(argv) < 2:
        print('사용법: python reels/reel.py 계정 "주제" [옵션] (계정은 목록으로 확인)')
        return 2
    cmd, cwd = command(argv[0], argv[1], argv[2:])
    return subprocess.run(cmd, cwd=cwd, env={**os.environ, "PYTHONIOENCODING": "utf-8"}).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
