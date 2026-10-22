"""캡션에서 주제·훅(첫 문장 스타일)·포맷을 분류하는 규칙.

키워드는 자유롭게 추가/수정하세요. 영어 키워드는 단어 단위로, 한글은 포함 여부로 찾습니다.
"""
import re

TOPICS = {
    "AI·반도체": ["엔비디아", "nvidia", "nvda", "반도체", "hbm", "semiconductor", "chips", "tsmc", "하이닉스", "amd", "broadcom", "젠슨", "ai", "인공지능"],
    "빅테크": ["애플 주가", "애플(aapl)", "apple", "aapl", "마이크로소프트", "microsoft", "msft", "구글", "alphabet", "googl", "아마존", "amazon", "amzn", "메타", "meta", "빅테크", "magnificent 7", "매그니피센트"],
    "테슬라": ["테슬라", "tesla", "tsla", "일론", "elon", "musk"],
    "금리·연준": ["금리", "연준", "fomc", "파월", "powell", "the fed", "rate cut", "rate cuts", "interest rate", "interest rates"],
    "물가·경기": ["cpi", "인플레이션", "inflation", "물가", "경기침체", "recession", "gdp", "고용지표", "jobs report", "실업률", "unemployment"],
    "환율·달러": ["환율", "원달러", "달러", "dollar", "dxy", "엔화", "yen"],
    "비트코인": ["비트코인", "bitcoin", "btc"],
    "알트코인": ["이더리움", "ethereum", "eth", "솔라나", "solana", "리플코인", "xrp", "알트코인", "altcoin", "altcoins", "밈코인", "memecoin", "도지코인", "dogecoin", "알트시즌"],
    "ETF·지수투자": ["etf", "s&p500", "s&p 500", "sp500", "나스닥100", "qqq", "voo", "spy", "index fund", "인덱스펀드", "지수투자"],
    "배당": ["배당", "dividend", "dividends", "schd", "월배당"],
    "국내 대형주": ["삼성전자", "코스피", "kospi", "코스닥", "kosdaq", "현대차", "카카오", "네이버", "밸류업"],
    "2차전지": ["2차전지", "이차전지", "배터리", "에코프로", "battery", "lithium", "리튬"],
    "실적발표": ["실적", "어닝", "earnings", "가이던스", "guidance", "eps"],
    "초보·투자마인드": ["초보", "입문", "마인드", "습관", "복리", "compound", "beginner", "beginners", "mindset", "부자", "wealth", "millionaire"],
    "연금·절세": ["국민연금", "연금저축", "퇴직연금", "개인연금", "연금계좌", "isa", "irp", "절세", "세금", "tax", "taxes", "401k", "roth"],
    "부동산": ["부동산", "아파트", "청약", "집값", "real estate", "housing", "mortgage"],
    "급락·변동성": ["폭락", "급락", "하락장", "crash", "sell-off", "selloff", "조정장", "correction", "공포지수", "공포탐욕", "vix", "bear market"],
    "정치·관세": ["관세", "tariff", "tariffs", "트럼프", "trump", "대선", "election"],
}

HOOKS = {
    "숫자·리스트형": [r"\d+\s*(가지|개|종목|선|위)", r"\btop\s*\d+", r"\d+\s*(things|stocks|ways|reasons)"],
    "질문형": [r"\?", r"까요", r"나요", r"일까"],
    "경고·실수형": [r"주의", r"경고", r"절대", r"하지\s*마", r"실수", r"손해", r"stop\b", r"mistake", r"warning", r"don't", r"never"],
    "속보·뉴스형": [r"속보", r"긴급", r"방금", r"breaking", r"just in", r"오늘"],
    "정리·요약형": [r"정리", r"총정리", r"요약", r"한눈에", r"explained", r"summary", r"guide"],
    "숫자 강조형": [r"\d[\d,.]*\s*(억|만|조|%|원|배|달러|bp)", r"\$\d"],
    "대비형": [r"인데", r"는데도", r"반면", r"\bvs\b", r"했지만"],
    "1인칭 경험형": [r"^(제가|저는|내가|나는)", r"^(i |i'm|my )"],
    "인용형": [r"^[\"“”'‘’]"],
}

# 캡션 속 행동 유도(CTA). 좋아요·댓글만 보이므로 '댓글 유도' 외에는 효과를 직접 잴 수 없다
CTAS = {
    "댓글 유도": [r"댓글", r"여러분은", r"여러분의", r"알려주세요", r"comment", r"let me know"],
    "저장 유도": [r"저장", r"나중에 (보|꺼내)", r"\bsave\b"],
    "공유 유도": [r"공유", r"태그해", r"친구에게", r"짝꿍에게", r"\bshare\b", r"\btag\b"],
    "링크·DM 유도": [r"프로필 링크", r"링크 클릭", r"\bdm\b", r"link in bio", r"오픈채팅"],
}
_CTA_PATS = {name: [re.compile(p, re.I) for p in pats] for name, pats in CTAS.items()}


def cta_of(caption):
    text = (caption or "")
    for name, pats in _CTA_PATS.items():
        if any(p.search(text) for p in pats):
            return name
    return "행동 유도 없음"


def length_of(caption):
    n = len((caption or "").strip())
    return "100자 이하" if n <= 100 else "101~300자" if n <= 300 else "301~800자" if n <= 800 else "800자 초과"


def tagcount_of(caption):
    n = len(re.findall(r"#[\w가-힣]+", caption or ""))
    return "해시태그 0개" if n == 0 else "1~3개" if n <= 3 else "4~8개" if n <= 8 else "9개 이상"

# 경품·이벤트·광고성 게시물은 반응이 인위적으로 커서 분석에서 뺀다
PROMO_PATS = [re.compile(p, re.I) for p in [r"#event", r"이벤트", r"경품", r"추첨", r"당첨", r"giveaway", r"에어드랍", r"선착순", r"응모"]]


def is_promo(caption):
    first = (caption or "")[:300]
    return any(p.search(first) for p in PROMO_PATS)


FORMAT_NAMES = {"REELS": "릴스", "CAROUSEL_ALBUM": "캐러셀(카드뉴스)", "VIDEO": "영상", "IMAGE": "단일 이미지"}


def _compile(words):
    pats = []
    for w in words:
        if re.fullmatch(r"[a-z0-9&\-\s]+", w):
            pats.append(re.compile(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])"))
        else:
            pats.append(re.compile(re.escape(w)))
    return pats


_TOPIC_PATS = {name: _compile(words) for name, words in TOPICS.items()}
_HOOK_PATS = {name: [re.compile(p, re.I) for p in pats] for name, pats in HOOKS.items()}


def topics_of(caption):
    # 뉴스 계정 캡션은 길어서 본문의 단어 하나에 엉뚱한 주제가 붙는다 → 앞부분(제목 역할) + 해시태그만 본다
    raw = (caption or "").lower()
    text = raw[:160] + " " + " ".join(re.findall(r"#[\w가-힣]+", raw))
    found = [name for name, pats in _TOPIC_PATS.items() if any(p.search(text) for p in pats)]
    return found or ["기타"]


def hook_of(caption):
    first = (caption or "").strip().split("\n", 1)[0][:120]
    for name, pats in _HOOK_PATS.items():
        if any(p.search(first) for p in pats):
            return name
    return "짧은 한 줄" if len(first) < 20 else "일반 서술형"


def format_of(media_type, product_type):
    if product_type == "REELS":
        return FORMAT_NAMES["REELS"]
    return FORMAT_NAMES.get(media_type or "", media_type or "알 수 없음")
