"""PPTX → 캔바 디자인. 토큰이 있는 작업 폴더(config.json 의 canva_workdir)의 기존 코드를 그 폴더에서 실행한다.

여기서 토큰·.env 를 읽지 않는다. 로그인 창도 열지 않는다. 연결이 끊겼으면 작업 폴더에서 다시 연결해야 한다.
새 refresh token 저장과 잠금은 작업 폴더의 publish/canva_auth.py 가 맡는다 (1회용이라 다른 곳에 복사하면 안 된다).
"""
import json
import os
import pathlib
import subprocess
import sys

from studio.paths import CONFIG

# 작업 폴더에서 돌아가는 부분. 표준 출력으로 편집 주소만 내보낸다
RUNNER = r"""
import json, pathlib, sys, urllib.request
sys.path.insert(0, ".")
from common import load_env
load_env()
from publish.canva import Canva
a = json.loads(sys.argv[1])
cv = Canva()
d = cv.import_file(a["pptx"], a["title"], cv.ensure_folder(a["folder"]))
out = {"id": d["id"], "edit_url": d["urls"]["edit_url"], "pages": 0}
if a.get("preview"):
    p = pathlib.Path(a["preview"]); p.mkdir(parents=True, exist_ok=True)
    for i, u in enumerate(cv.export(d["id"], "jpg"), 1):
        urllib.request.urlretrieve(u, p / f"캔바_{i:02d}.jpg")
        out["pages"] = i
print("RESULT " + json.dumps(out))
"""


def send(pptx, title, preview_dir=None):
    work = pathlib.Path(CONFIG["canva_workdir"])
    if not (work / "publish" / "canva.py").exists():
        raise SystemExit(f"캔바 작업 폴더를 찾지 못했어요: {work}\n이 PC에서는 canva.com 에 캔바용.pptx 를 끌어다 놓아 주세요.")
    arg = json.dumps({"pptx": str(pathlib.Path(pptx).resolve()), "title": title, "folder": CONFIG["canva_folder"], "preview": str(pathlib.Path(preview_dir).resolve()) if preview_dir else ""}, ensure_ascii=False)
    r = subprocess.run([sys.executable, "-c", RUNNER, arg], cwd=work, capture_output=True, text=True, encoding="utf-8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}, timeout=900)
    line = next((x for x in r.stdout.splitlines() if x.startswith("RESULT ")), None)
    if r.returncode or not line:
        # 오류 마지막 줄만 보여 준다 (토큰이 찍히는 코드는 아니지만 긴 출력을 남기지 않는다)
        tail = (r.stderr.strip().splitlines() or ["알 수 없는 오류"])[-1]
        raise SystemExit(f"캔바로 보내지 못했어요: {tail[:300]}")
    return json.loads(line[7:])
