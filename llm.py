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
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime
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


# ── PC 무료 AI (Ollama) ─────────────────────────────────────────────
# 2026-11-07 대표 결정: 매시간 도는 분석(요약·진단)은 이 PC 그래픽카드의 무료 AI 로 돌려 Max 한도를 아낀다.
# 독자에게 나가는 글(기획안·텔레그램 문구·쓰레드 글 등)은 그대로 Claude.
# 무료 AI 가 꺼져 있거나 답이 형식에 안 맞으면 자동으로 Claude 로 넘어간다 (사이트가 멈추지 않게).
# PC 에서만 바꾸기: ~/.content-lab-ai/llm_route.json  {"off": true} → 전부 Claude / {"local": ["a.py", ...], "model": "qwen3:8b"}
LOCAL_URL = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
LOCAL_MODEL = "qwen3:8b"
LOCAL_SCRIPTS = set()   # 2026-11-07 시험 결과: 이 PC(그래픽카드 8GB를 다른 프로그램이 대부분 씀)에서는 느리고 품질이 낮아 기본은 끔
LOCAL_MAX_PROMPT = 30000          # 이보다 긴 자료(추정 토큰)는 8GB 그래픽카드에 안 들어가서 Claude 로
LOCAL_TIMEOUT = 15 * 60
_HOME = os.path.join(os.path.expanduser("~"), ".content-lab-ai")


def _local_log(msg):
    try:
        os.makedirs(_HOME, exist_ok=True)
        with open(os.path.join(_HOME, "llm_local.log"), "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%m/%d %H:%M:%S} {os.path.basename(sys.argv[0] or '?')} {msg}\n")
    except OSError:
        pass


def _route():
    """(무료 AI 를 쓸지, 모델 이름). 깃허브 서버·설정 off·목록 밖 프로그램이면 Claude."""
    if os.environ.get("GITHUB_ACTIONS") or os.environ.get("LLM_BACKEND") == "claude":
        return False, None
    cfg = {}
    try:
        with open(os.path.join(_HOME, "llm_route.json"), encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        pass
    if cfg.get("off"):
        return False, None
    scripts = set(cfg.get("local") or LOCAL_SCRIPTS)
    me = os.path.basename(sys.argv[0] or "")
    return (os.environ.get("LLM_BACKEND") == "local" or me in scripts), cfg.get("model") or LOCAL_MODEL


def _local(model, system, messages, schema):
    sys_text = system if isinstance(system, str) else _text(system or [])
    user = _prompt(messages)
    est = (len(sys_text) + len(user)) // 2          # 한글 기준 대략 2글자 = 1토큰보다 넉넉하게
    if est > LOCAL_MAX_PROMPT:
        raise APIConnectionError(f"자료가 길어요(약 {est:,}토큰)")
    if schema is not None:
        sys_text += "\n\n반드시 주어진 JSON 형식으로만, 한국어로 답하세요."
    body = {"model": model, "stream": False, "think": False,
            "messages": [{"role": "system", "content": sys_text}, {"role": "user", "content": user}],
            "options": {"num_ctx": min(40960, max(8192, int(est * 1.15) + 8192)), "temperature": 0.4}}
    if schema is not None:
        body["format"] = schema.model_json_schema()
    req = urllib.request.Request(LOCAL_URL + "/api/chat", data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=LOCAL_TIMEOUT) as r:
            d = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise APIConnectionError(f"무료 AI 연결 실패: {e}")
    text = (d.get("message") or {}).get("content") or ""
    parsed = None
    if schema is not None:
        try:
            parsed = schema.model_validate(json.loads(text))
        except Exception as e:  # 형식이 틀리면 Claude 로
            raise APIStatusError(f"무료 AI 답 형식 오류: {str(e)[:160]}")
    usage = SimpleNamespace(input_tokens=d.get("prompt_eval_count", 0), output_tokens=d.get("eval_count", 0), backend="local")
    _local_log(f"무료AI {model} 입력 {usage.input_tokens:,} 출력 {usage.output_tokens:,} {time.time() - t:.0f}초 ✓")
    return SimpleNamespace(parsed_output=parsed, stop_reason="end_turn", usage=usage,
                           content=[SimpleNamespace(type="text", text=text)])


def _run(model, system, messages, schema=None, effort=None):
    use_local, local_model = _route()
    if use_local:
        try:
            return _local(local_model, system, messages, schema)
        except (APIConnectionError, APIStatusError) as e:
            _local_log(f"→ Claude 로 넘김 ({e})")
    return _claude(model, system, messages, schema, effort)


def _claude(model, system, messages, schema=None, effort=None):
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
                               errors="replace", timeout=TIMEOUT, cwd=tmp, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
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


def look(model, prompt, image):
    """그림 파일 하나를 보여 주고 글로 답을 받는다 (Read 도구만 허용)."""
    cli = _cli()
    if not cli:
        raise APIConnectionError("claude 명령을 찾지 못했어요")
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    cmd = [cli, "-p", "--model", model, "--tools", "Read", "--allowedTools", "Read", "--strict-mcp-config", "--setting-sources", "",
           "--no-session-persistence", "--output-format", "json"]
    p = subprocess.run(cmd, input=f"{prompt}\n\n그림 파일: {image}", capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=180, cwd=os.path.dirname(image), env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    d = json.loads(p.stdout)
    if d.get("is_error"):
        raise APIStatusError(str(d.get("result"))[:300])
    return d.get("result") or ""


def look_json(model, prompt, images, schema, system=None, timeout=420):
    """그림 여러 장을 보여 주고 schema(pydantic) 모양으로 답을 받는다 (Read 도구만 허용)."""
    cli = _cli()
    if not cli:
        raise APIConnectionError("claude 명령을 찾지 못했어요")
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    listing = "\n".join(str(i) for i in images)
    with tempfile.TemporaryDirectory() as tmp:
        cmd = [cli, "-p", "--model", model, "--tools", "Read", "--allowedTools", "Read", "--strict-mcp-config", "--setting-sources", "",
               "--no-session-persistence", "--output-format", "json", "--json-schema", json.dumps(schema.model_json_schema(), ensure_ascii=False)]
        if system:
            sp = os.path.join(tmp, "system.txt")
            with open(sp, "w", encoding="utf-8") as f:
                f.write(system)
            cmd += ["--system-prompt-file", sp]
        try:
            p = subprocess.run(cmd, input=f"{prompt}\n\n그림 파일(모두 Read 로 열어 보세요):\n{listing}", capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=timeout, cwd=tmp, env=env,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            raise APIConnectionError(f"그림 분석이 {timeout}초 안에 끝나지 않았어요")
    try:
        d = json.loads(p.stdout)
    except json.JSONDecodeError:
        raise APIStatusError(f"Claude Code 실행 실패({p.returncode}): {(p.stderr or p.stdout)[-400:]}")
    if d.get("is_error"):
        raise APIStatusError(str(d.get("result"))[:300])
    raw = d.get("structured_output")
    return schema.model_validate(raw if raw is not None else json.loads(d.get("result") or "null"))


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
