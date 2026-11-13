"""ChatGPT(Codex CLI, ChatGPT 계정 로그인 = 정액제) 로 글을 쓰는 엔진. Claude 토큰을 쓰지 않는다.

PC 에 Codex 앱이 깔려 있고 로그인돼 있어야 한다 (%LOCALAPPDATA%\\OpenAI\\Codex\\bin\\<버전>\\codex.exe).
읽기 전용·임시 폴더에서 돌려 PC 파일을 건드리지 못하게 하고, 답 모양은 JSON 스키마로 고정한다.
"""
import copy
import glob
import json
import os
import subprocess
import tempfile
from pathlib import Path


def codex():
    hits = glob.glob(os.path.expandvars(r"%LOCALAPPDATA%\OpenAI\Codex\bin\*\codex.exe"))
    return max(hits, key=os.path.getmtime) if hits else None


def ready():
    return bool(codex())


def strict(schema):
    """OpenAI 구조화 출력 규칙: 모든 객체에 additionalProperties=false, 모든 속성 required."""
    s = copy.deepcopy(schema)

    def fix(n):
        if isinstance(n, dict):
            if n.get("type") == "object" and "properties" in n:
                n["additionalProperties"] = False
                n["required"] = list(n["properties"])
            n.pop("title", None)
            for v in n.values():
                fix(v)
        elif isinstance(n, list):
            for v in n:
                fix(v)
    fix(s)
    return s


def ask(system, prompt, schema, timeout=15 * 60):
    """system + prompt 를 ChatGPT 에 보내고 schema 모양 dict 를 돌려준다."""
    exe = codex()
    if not exe:
        raise RuntimeError("codex.exe 없음 (Codex 앱 설치·로그인 필요)")
    with tempfile.TemporaryDirectory(prefix="gpt_") as d:
        sp, op = Path(d) / "schema.json", Path(d) / "out.json"
        sp.write_text(json.dumps(strict(schema), ensure_ascii=False), encoding="utf-8")
        text = (f"{system}\n\n---\n\n{prompt}\n\n"
                "파일을 읽거나 명령을 실행하지 말고, 위 자료만으로 바로 답해. 답은 주어진 JSON 스키마 그대로.")
        r = subprocess.run([exe, "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only", "-C", d,
                            "--output-schema", str(sp), "-o", str(op), "-"],
                           input=text.encode("utf-8"), capture_output=True, timeout=timeout)
        if r.returncode != 0 or not op.exists():
            raise RuntimeError(f"Codex 실패({r.returncode}): {r.stderr.decode('utf-8', 'ignore')[-400:]}")
        raw = op.read_text(encoding="utf-8").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").split("\n", 1)[1]
    return json.loads(raw)
