"""숫자·표현 검사와 숫자 읽기. 대본은 숫자로 쓰고, 음성용 한글은 코드가 만든다 (자막과 음성 숫자가 어긋나지 않게)."""
import re

NUM = re.compile(r"\d[\d,.]*\d|\d")
ADVICE = re.compile(r"사세요|파세요|담으세요|매수하세요|매도하세요|매수 추천|매도 추천|매수 관점|분할 매수|손절|지금이 기회|무조건|확실히 오릅|목표가|수익 보장|떡상|떡락|저점 매수|추격 매수")
FREE = {"1", "2", "3"}   # 순서·개수로 흔히 쓰는 숫자
DIGIT = "영일이삼사오육칠팔구"
HAS_FORBIDDEN_LATIN = re.compile(r"[A-Za-z]")


def nums(text):
    return {n.replace(",", "").rstrip(".") for n in NUM.findall(text or "")}


def unknown_numbers(text, source_nums):
    return sorted(n for n in nums(text) if n not in source_nums and n not in FREE)


def under_10k(n):
    out = ""
    for u, name in ((1000, "천"), (100, "백"), (10, "십")):
        d, n = divmod(n, u)
        if d:
            out += ("" if d == 1 else DIGIT[d]) + name
    return out + (DIGIT[n] if n else "")


def read_int(n):
    if n == 0:
        return "영"
    out = ""
    for u, name in ((10 ** 12, "조"), (10 ** 8, "억"), (10 ** 4, "만")):
        d, n = divmod(n, u)
        if d:
            out += ("" if d == 1 and name == "만" else under_10k(d)) + name + " "
    return (out + under_10k(n)).strip()


def read_number(s):
    s = s.replace(",", "")
    if "." in s:
        a, b = s.split(".", 1)
        return f"{read_int(int(a or 0))} 점 {''.join(DIGIT[int(c)] for c in b)}"
    return read_int(int(s))


MONTH = {6: "유월", 10: "시월"}


def to_reading(text):
    """글자 속 숫자 → 읽는 한글. 예: '$79.93' → '칠십구 점 구삼 달러', '77~78달러' → '칠십칠에서 칠십팔 달러', '10/29' → '시월 이십구일'."""
    t = text
    t = re.sub(r"\$(\d[\d,.]*(?:\s*~\s*\d[\d,.]*)?)(억|조|만)?", r"\1\2달러", t)
    t = re.sub(r"(?<![\d.])(\d{1,2})/(\d{1,2})(?![\d/])", lambda m: f"{MONTH.get(int(m[1]), read_int(int(m[1])) + '월')} {read_int(int(m[2]))}일", t)
    t = re.sub(r"(\d{1,2})월", lambda m: MONTH.get(int(m[1]), read_int(int(m[1])) + "월"), t)
    t = re.sub(r"(\d[\d,.]*)\s*~\s*(\d[\d,.]*)", lambda m: f"{read_number(m[1].rstrip('.'))}에서 {read_number(m[2].rstrip('.'))}", t)
    t = re.sub(r"\+(?=\d)", "플러스 ", t)
    t = re.sub(r"[−-](?=\d)", "마이너스 ", t)
    t = t.replace("%p", " 퍼센트 포인트").replace("%", " 퍼센트")
    t = re.sub(r"\d[\d,]*\.\d+|\d[\d,]*", lambda m: read_number(m[0]), t)
    t = re.sub(r"(?<=[영일이삼사오육칠팔구십백천만억조])달러", " 달러", t)
    return re.sub(r"\s+", " ", t).strip()


def problems(text, where, source_nums):
    """글 한 조각의 막을 문제."""
    out = []
    for n in unknown_numbers(text, source_nums):
        out.append(f"{where}: 자료에서 확인 안 되는 숫자 {n} ({text[:50]})")
    if ADVICE.search(text or ""):
        out.append(f"{where}: 투자 권유로 보이는 표현 ({text[:50]})")
    return out
