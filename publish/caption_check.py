"""올리기 전 캡션 점검 — ig-caption·ig-human 스킬 기준을 한국어에 맞춘 것 (2026-11-05).

    caption = clean(caption)                          # 안 보이는 문자, 긴 줄표처럼 고쳐도 뜻이 안 변하는 것만 바로 고침
    block, notes = check(caption, keyword="환율")      # block: 발행을 막는 문제 / notes: 사람이 보고 판단할 참고 사항

스킬의 caption.py 는 영어 문구와 라틴 글자 해시태그만 세어 한국어 캡션에 틀린 경고를 낸다(부탁 0개, 해시태그 0개).
그래서 규칙만 가져와 여기서 센다. 말투 점수는 스킬의 detect.py 가 PC에 있을 때만 참고로 붙인다.
"""
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unicodedata

CUT = 125        # 피드에서 '더 보기' 전에 보이는 대략의 글자 수 (기기마다 다름)
FIRST_LINE = 40
MAX_TAGS = 5
HUMAN_OK = 70    # 스킬의 한국어 기준값도 검증되지 않은 판단값이라 막지 않고 참고만
DETECT = pathlib.Path.home() / ".claude/skills/ig-human/detect.py"
TAG = re.compile(r"(?<!\w)#\w+")
ASK = re.compile(r"(댓글|저장|팔로우|공유|DM|디엠)[^.?!\n]*(주세요|하세요|남겨|눌러)")


def clean(text):
    """뜻이 안 변하는 기계 흔적만 지운다."""
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
    text = re.sub(r"\s*[—―]\s*", ", ", text).replace("–", "-").replace("…", "...")
    for a, b in (("“", '"'), ("”", '"'), ("‘", "'"), ("’", "'"), (" ", " ")):
        text = text.replace(a, b)
    return text


def body_of(caption):
    """면책 문구, 사진 출처, 해시태그를 뺀 사람이 쓴 부분."""
    keep = [x for x in caption.split("\n") if not (x.startswith("사진 ") or x.startswith("(정보 제공용") or (x.strip() and not TAG.sub("", x).strip()))]
    return "\n".join(keep).strip()


def human_note(body):
    if not DETECT.exists() or len(body) < 200:   # 짧은 글은 점수가 흔들림
        return None
    with tempfile.TemporaryDirectory() as tmp:
        f = pathlib.Path(tmp) / "c.txt"
        f.write_text(body, encoding="utf-8")
        try:
            r = subprocess.run([sys.executable, str(DETECT), str(f), "--json"], capture_output=True, encoding="utf-8", errors="replace", timeout=30,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            d = json.loads(r.stdout)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            return None
    if d["human_score"] >= HUMAN_OK:
        return None
    weak = min(d["checks"], key=lambda k: d["checks"][k]["score"])
    return f"말투 점수 {d['human_score']:.0f}점 (가장 낮은 항목 {weak})"


def check(caption, keyword=""):
    """→ (block, notes). block 은 잘못 올라가면 안 되는 것, notes 는 판단이 필요한 것."""
    block, notes = [], []
    first = next((x.strip() for x in caption.split("\n") if x.strip()), "")
    body = body_of(caption)
    if first.startswith("#") or (first and unicodedata.category(first[0]) == "So"):
        block.append("캡션 첫 글자가 해시태그나 이모지예요")
    if len(first) > CUT:
        block.append(f"캡션 첫 줄이 {len(first)}자라 '더 보기'에서 잘려요")
    elif len(first) > FIRST_LINE:
        notes.append(f"첫 줄이 {len(first)}자로 길어요 ({FIRST_LINE}자 권장)")
    if re.search(r"https?://|www\.", body):
        block.append("캡션 본문에 주소가 있어요 (인스타 캡션의 주소는 눌리지 않아요)")
    if len(TAG.findall(caption)) > MAX_TAGS:
        block.append(f"해시태그가 {MAX_TAGS}개를 넘어요")
    asks = len(ASK.findall(body))
    if asks != 1:
        notes.append(f"행동 유도가 {asks}개예요 (1개 권장)")
    if keyword and keyword not in body:
        notes.append(f"끝 장 댓글 키워드 '{keyword}'가 캡션에 없어요")
    ends = re.findall(r"(습니다|입니다|니다|어요|아요|예요|해요|에요|네요)[.!?\s]", body + " ")
    if {"습니다", "입니다", "니다"} & set(ends) and {"어요", "아요", "예요", "해요", "에요", "네요"} & set(ends):
        notes.append("'~습니다'와 '~요'가 섞여 있어요")
    h = human_note(body)
    if h:
        notes.append(h)
    return block, notes
