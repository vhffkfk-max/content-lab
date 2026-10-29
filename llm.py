"""Claude 호출을 내 PC의 Claude Code(Max 구독)로 돌린다 — API 요금이 따로 나가지 않게.

anthropic SDK 와 같은 모양으로 쓴다: `import llm as anthropic` 후
  anthropic.Anthropic().messages.parse(model=, system=, messages=, output_format=PydanticModel, output_config={"effort": ...})
  anthropic.Anthropic().messages.stream(...)  (with 문 → get_final_message())
  anthropic.Anthropic().messages.create(...)  (글만 받을 때)
결과: .parsed_output / .content[0].text / .stop_reason / .usage.input_tokens / .usage.output_tokens

- 깃허브 서버처럼 Claude Code 로그인이 없는 곳에서는 ready() 가 False → 각 프로그램이 건너뛰고 지난 결과를 유지한다.
- ANTHROPIC_API_KEY 는 일부러 지우고 부른다 (키가 있으면 Claude Code 가 API 요금으로 돌기 때문).
"""
import json
import os
import shutil
import subprocess
import tempfile
from types import SimpleNamespace

TIMEOUT = 20 * 60


class APIStatusError(Exception):
    pass


class APIConnectionError(Exception):
    pass


def _cli():
    return shutil.which("claude") or next((p for p in (os.path.expanduser(r"~\.local\bin\claude.exe"),
                                                       os.path.expanduser("~/.local/bin/claude")) if os.path.exists(p)), None)


def ready():
    """이 컴퓨터에서 Max 구독으로 Claude 를 부를 수 있나 (깃허브 서버면 False)."""
    return not os.environ.get("GITHUB_ACTIONS") and _cli() is not None


def _text(content):
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content if b.get("type") == "text")


def _prompt(messages):
    """여러 턴 대화는 한 덩어리 글로 펴서 넘긴다 (draft_card 의 'JSON 다시 주세요' 재시도용)."""
    if len(messages) == 1:
        return _text(messages[0]["content"])
    who = {"user": "사용자", "assistant": "당신(이전 답변)"}
    return "\n\n".join(f"[{who.get(m['role'], m['role'])}]\n{_text(m['content'])}" for m in messages) + "\n\n[마지막 사용자 요청에 답하세요]"


def _run(model, system, messages, schema=None, effort=None):
    cli = _cli()
    if not cli:
        raise APIConnectionError("claude 명령을 찾지 못했어요 (Claude Code 설치·로그인 필요)")
    sys_text = system if isinstance(system, str) else _text(system or [])
    with tempfile.TemporaryDirectory() as tmp:   # 프로젝트 설정·CLAUDE.md 를 안 읽게 빈 폴더에서
        sp = os.path.join(tmp, "system.txt")
        with open(sp, "w", encoding="utf-8") as f:
            f.write(sys_text or "You are a helpful assistant.")
        cmd = [cli, "-p", "--model", model, "--system-prompt-file", sp, "--tools", "", "--strict-mcp-config",
               "--setting-sources", "", "--no-session-persistence", "--output-format", "json"]
        if schema is not None:
            cmd += ["--json-schema", json.dumps(schema.model_json_schema(), ensure_ascii=False)]
        if effort:
            cmd += ["--effort", effort]
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}   # API 요금 방지
        try:
            p = subprocess.run(cmd, input=_prompt(messages), capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=TIMEOUT, cwd=tmp, env=env)
        except subprocess.TimeoutExpired:
            raise APIConnectionError(f"Claude Code 가 {TIMEOUT // 60}분 안에 끝나지 않았어요")
    try:
        d = json.loads(p.stdout)
    except json.JSONDecodeError:
        raise APIStatusError(f"Claude Code 실행 실패({p.returncode}): {(p.stderr or p.stdout)[-400:]}")
    if d.get("is_error") or d.get("subtype") != "success":
        raise APIStatusError(f"Claude Code 오류: {str(d.get('result') or d.get('subtype'))[:400]}")
    u = next(iter((d.get("modelUsage") or {}).values()), {})
    usage = SimpleNamespace(input_tokens=u.get("inputTokens", 0) + u.get("cacheReadInputTokens", 0) + u.get("cacheCreationInputTokens", 0),
                            output_tokens=u.get("outputTokens", 0))
    parsed = None
    if schema is not None:
        raw = d.get("structured_output")
        if raw is None:
            raw = json.loads(d.get("result") or "null")
        parsed = schema.model_validate(raw) if raw is not None else None
    text = d.get("result") or ""
    return SimpleNamespace(parsed_output=parsed, stop_reason="end_turn", usage=usage,
                           content=[SimpleNamespace(type="text", text=text)])


class _Stream:
    def __init__(self, r):
        self.r = r

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.r


class _Messages:
    def parse(self, model, messages, system=None, output_format=None, output_config=None, **_):
        return _run(model, system, messages, output_format, (output_config or {}).get("effort"))

    def stream(self, model, messages, system=None, output_format=None, output_config=None, **_):
        return _Stream(self.parse(model, messages, system, output_format, output_config))

    def create(self, model, messages, system=None, output_config=None, **_):
        return _run(model, system, messages, None, (output_config or {}).get("effort"))


class Anthropic:
    def __init__(self, *a, **k):
        self.messages = _Messages()
