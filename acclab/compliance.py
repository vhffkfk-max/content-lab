"""컴플라이언스 자동 체크 — 생성된 글·대본마다 돌리고, 걸린 항목은 페이지에 ⚠ 와 사유로 보인다.

    from acclab.compliance import check
    flags = check(text, account, facts_text)   # [{"kind": "매수·매도 지시", "hit": "지금 사세요", "level": "stop"}]

level: stop = 올리면 안 되는 것(고쳐서 다시 쓰게 함) / warn = 사람이 한 번 볼 것 / info = 참고
규칙은 정규식이라 놓칠 수 있다. 사람 검토를 대신하지 않는다.
"""
import re

from acclab.common import election_now

R = lambda p: re.compile(p, re.I | re.M)

COMMON = [
    ("매수·매도 지시", "stop", R(r"지금\s*(?:바로\s*)?(?:사|담|매수|팔|매도)(?:세요|시라|하세요|해라|하라)|전량\s*(?:매도|매수)|풀\s*매수|몰빵|"
                                r"매수\s*(?:추천|타이밍입니다|기회입니다|하세요)|매도\s*(?:추천|하세요)|(?:사|담|팔)\s*두세요")),
    ("수익 보장·확정 예측", "stop", R(r"반드시\s*오[르릅]|무조건\s*(?:오[르릅]|수익|떨어)|100\s*%\s*(?:수익|상승|확실)|확실(?:히|한)\s*(?:오[르릅]|수익)|"
                                     r"손실\s*(?:없|제로)|원금\s*보장|수익\s*보장|\d+\s*배\s*(?:간다|갑니다|확정)|떡상\s*확정|오를\s*수밖에\s*없")),
    ("특정 종목·코인·단지 추천", "stop", R(r"(?:종목|코인|단지|아파트)\s*(?:추천|강추)|(?:이|그)\s*(?:종목|코인)\s*(?:사|담)|추천\s*(?:종목|코인|단지)|"
                                        r"(?:목표가|목표\s*주가)\s*[\d,]+")),
    ("레버리지 권유", "stop", R(r"레버리지\s*(?:추천|써|쓰세요|타세요|강추)|(?:\d+)\s*배\s*(?:롱|숏)\s*(?:추천|진입하세요)|풀\s*레버")),
    ("수익 인증식 표현", "warn", R(r"수익\s*인증|\d+\s*%\s*먹었|[\d,]+\s*만\s*원\s*벌었|계좌\s*공개")),
    ("AI 티: 반전 문구 '~가 아니라 ~다'", "stop", R(r"(?:이|가|은|는)?\s*아니라[,\s].{0,25}(?:이다|입니다|거예요|겁니다)|라기보다")),
    ("AI 티 나는 상투 표현", "warn", R(r"결론적으로|요약하자면|것으로\s*보입니다|살펴보겠습니다|알아보겠습니다|중요한\s*시사점|주목할\s*필요가")),
    ("빈칸·번호 머리", "stop", R(r"\[\s*\]|\[\s*확인[^\]]*\]|^\s*\d+\s*/\s*$|^\s*\d+/\s|[1-9]️?⃣", )),
    ("가운뎃점 수치 나열", "warn", R(r"\d[\d,.]*\s*[%원억조달러]?\s*·\s*\d")),
]

POLITICS = [
    ("인격 비하 표현", "stop", R(r"멍청|무능한\s*(?:놈|자)|돌대가리|미친\s*(?:놈|정부|정권)|쓰레기|개돼지|매국노|빨갱이|토착왜구|수꼴|좌빨|틀딱|"
                              r"(?:외모|얼굴|가족|자녀|부인|남편)\s*(?:비하|조롱)")),
    ("단정형 의견 (의견임이 드러나야 함)", "warn", R(r"(?:명백한|명백히)\s*(?:거짓|범죄|실패)|(?:범죄자|사기꾼)(?:이다|입니다)")),
]

DISCLAIMER_KEYS = ("투자 권유가 아닙니다", "투자 권유가 아님")


def quotes_unverified(text, facts_text):
    """따옴표 인용인데 소재 사실(facts)에 없는 문장 → 미확인 인용."""
    out = []
    for q in re.findall(r"[\"“]([^\"”]{6,80})[\"”]", text):
        core = re.sub(r"\s+", "", q)[:12]
        if core and core not in re.sub(r"\s+", "", facts_text or ""):
            out.append(q[:40])
    return out


def check(text, account, facts_text=""):
    flags = []
    for kind, level, rx in COMMON:
        m = rx.search(text or "")
        if m:
            flags.append({"kind": kind, "hit": m.group(0).strip()[:40], "level": level})
    politics = account.get("group") == "정치"
    if politics:
        for kind, level, rx in POLITICS:
            m = rx.search(text or "")
            if m:
                flags.append({"kind": kind, "hit": m.group(0).strip()[:40], "level": level})
        for q in quotes_unverified(text, facts_text):
            flags.append({"kind": "실명 인물 미확인 인용", "hit": q, "level": "stop"})
        if account.get("opinion_note", "") not in (text or ""):
            flags.append({"kind": "'개인 의견입니다' 누락", "hit": "", "level": "stop"})
        e = election_now()
        if e:
            flags.append({"kind": "선거 기간 주의", "hit": e["name"], "level": "warn"})
    elif not any(k in (text or "") for k in DISCLAIMER_KEYS):
        flags.append({"kind": "면책 문구 누락", "hit": "", "level": "stop"})
    return flags


def stops(flags):
    return [f for f in flags if f["level"] == "stop"]


def first_line(text):
    return next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")


def same_hooks(items):
    """같은 소재로 나온 여러 계정 글의 첫 문장이 겹치는지 — [(slug_a, slug_b, 첫문장)]"""
    seen, out = {}, []
    for slug, text in items:
        key = re.sub(r"[\s\W]+", "", first_line(text))[:25]
        if key and key in seen:
            out.append((seen[key], slug, first_line(text)[:40]))
        seen.setdefault(key, slug)
    return out
