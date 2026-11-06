"""릴스 영상 형식 8가지와 컷 사진. 대본은 그대로 두고 화면만 바꾼다.

- 계정 색(검정 #0B0B0D · 빨강 #E3262B · 노랑 #FFC23A · 흰색)은 모든 형식이 같이 쓴다. 형식은 배치·글꼴·사진 쓰는 법만 다르다.
- 사진은 카드뉴스와 같은 publish/photos.py: 위키미디어 공용의 상업 이용 가능 사진(CC BY·BY-SA·CC0·퍼블릭 도메인)만,
  후보를 Claude 가 눈으로 보고 고른다. 출처는 올릴 글 끝에 모아 적는다 (CC BY 는 출처 표시가 조건).
"""
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel

PHOTO_MODEL = "claude-sonnet-5-5"   # 사진 검색어만 정하는 가벼운 일

# key: (이름, 어떤 영상에 어울리나, CSS). 순서가 사이트에 보이는 순서.
FORMATS = {
    "neon": ("다이내믹 네온형", "숫자·시세가 많은 급등락 소식. 지금까지 쓰던 기본 화면", """
body.fmt-neon .ph{position:absolute;left:-30px;right:-30px;top:-20px;bottom:-20px;background-size:cover;background-position:center;border-radius:28px;opacity:.42;z-index:-1}
body.fmt-neon .ph::after{content:'';position:absolute;inset:0;border-radius:28px;background:linear-gradient(180deg,rgba(11,11,13,.15),rgba(11,11,13,.88))}
"""),
    "photo": ("사진 뉴스형", "기업·인물이 주인공인 소식. 화면 전체 사진 위에 큰 글씨 (카드뉴스 기본형과 같은 결)", """
body.fmt-photo #fx,body.fmt-photo #bigword{display:none}
body.fmt-photo .ph{position:absolute;left:-65px;top:-360px;width:1080px;height:1920px;background-size:cover;background-position:center;z-index:-1}
body.fmt-photo .ph::after{content:'';position:absolute;inset:0;background:linear-gradient(180deg,rgba(0,0,0,.5) 0%,rgba(0,0,0,.2) 18%,rgba(0,0,0,.72) 34%,rgba(0,0,0,.93) 58%)}
body.fmt-photo section:has(.ph){justify-content:flex-end}
body.fmt-photo section:has(.ph) .emo{display:none}
body.fmt-photo .q,body.fmt-photo .big,body.fmt-photo .nm{text-shadow:0 4px 18px rgba(0,0,0,.6)}
"""),
    "breaking": ("속보형", "방금 나온 발표·판결·사건. 빨간 속보 띠와 위쪽 사진", """
body.fmt-breaking #rays{display:none}
body.fmt-breaking section:has(.ph)::after{content:'속보';position:absolute;left:0;top:300px;height:56px;padding:0 22px;background:#E3262B;color:#fff;font:900 34px/56px HSans,sans-serif;letter-spacing:6px}
body.fmt-breaking .ph{position:absolute;left:-65px;right:-65px;top:-6px;height:370px;background-size:cover;background-position:center;z-index:-1;border-bottom:8px solid #E3262B}
body.fmt-breaking section:has(.ph){justify-content:flex-start;padding-top:392px}
body.fmt-breaking section:has(.ph) .emo{display:none}
body.fmt-breaking section:has(.ph)>*:not(.ph){zoom:.8}
body.fmt-breaking .q,body.fmt-breaking .wave,body.fmt-breaking .big{font-family:HBlack,HSans,sans-serif;font-weight:400}
body.fmt-breaking #tape{background:#E3262B}body.fmt-breaking #tape div{color:#fff}
"""),
    "paper": ("아침 경제신문형", "정책·제도·법원 판단처럼 차분히 설명할 소식. 밝은 종이와 명조", """
body.fmt-paper{background:#f2ede3!important;color:#151515}
body.fmt-paper #fx,body.fmt-paper #flash{display:none}
body.fmt-paper .q,body.fmt-paper .wave,body.fmt-paper .why2,body.fmt-paper .num,body.fmt-paper .big{font-family:HMyeongjo,serif;color:#151515;text-shadow:none}
body.fmt-paper .nm,body.fmt-paper .tag,body.fmt-paper .lb,body.fmt-paper .chk{color:#151515}
body.fmt-paper .sub,body.fmt-paper #warn,body.fmt-paper #head span{color:#555}
body.fmt-paper .kick{background:#151515;color:#f2ede3!important}
body.fmt-paper .ln.num{color:#E3262B;text-shadow:none}
body.fmt-paper .ln.mark{background-image:linear-gradient(transparent 62%,rgba(255,194,58,.75) 62%,rgba(255,194,58,.75) 94%,transparent 94%)}
body.fmt-paper .card2{background:#fff;border-color:#d8cfbf}
body.fmt-paper .ph{position:absolute;left:0;right:0;top:0;height:300px;background-size:cover;background-position:center;filter:grayscale(1) contrast(1.15);border:3px solid #151515}
body.fmt-paper section:has(.ph){justify-content:flex-start;padding-top:326px}
body.fmt-paper section:has(.ph) .emo{display:none}
body.fmt-paper section:has(.ph)>*:not(.ph){zoom:.82}
body.fmt-paper #cap>div{background:#fff;border-color:#151515;color:#151515}body.fmt-paper #cap em{color:#E3262B}
body.fmt-paper #tape{background:#151515}body.fmt-paper #tape div{color:#FFC23A}
body.fmt-paper #bigword{-webkit-text-stroke:3px rgba(0,0,0,.08)}
body.fmt-paper .track{background:rgba(0,0,0,.08)}
"""),
    "split": ("사진 반반형", "사진이 이야기를 많이 하는 소식. 위 절반 사진, 아래 절반 글", """
body.fmt-split #rays{display:none}
body.fmt-split .ph{position:absolute;left:-65px;top:-360px;width:1080px;height:760px;background-size:cover;background-position:center;z-index:-1}
body.fmt-split .ph::after{content:'';position:absolute;inset:0;background:linear-gradient(180deg,rgba(0,0,0,.35),rgba(0,0,0,0) 35%,rgba(11,11,13,.2) 75%,#0B0B0D)}
body.fmt-split section:has(.ph){justify-content:flex-start;padding-top:380px}
body.fmt-split section:has(.ph) .emo{display:none}
body.fmt-split section:has(.ph)>*:not(.ph){zoom:.78}
"""),
    "data": ("데이터 터미널형", "지수·환율·금리처럼 숫자가 주인공. 남색 화면과 또렷한 고딕", """
body.fmt-data{background:#06101f!important}
body.fmt-data #rays,body.fmt-data #bigword{display:none}
body.fmt-data #grid{background-image:linear-gradient(rgba(90,162,255,.12) 2px,transparent 2px),linear-gradient(90deg,rgba(90,162,255,.12) 2px,transparent 2px);background-size:60px 60px}
body.fmt-data .q,body.fmt-data .big,body.fmt-data .num,body.fmt-data .wave{font-family:HPlex,HSans,sans-serif}
body.fmt-data .kick{background:transparent;color:#FFC23A!important;border:3px solid #FFC23A}
body.fmt-data .ph{position:absolute;left:-20px;right:-20px;top:-20px;bottom:-20px;background-size:cover;background-position:center;opacity:.22;filter:grayscale(1);z-index:-1;border-radius:16px}
body.fmt-data .ph::after{content:'';position:absolute;inset:0;background:repeating-linear-gradient(0deg,rgba(6,16,31,.55) 0 3px,transparent 3px 6px)}
body.fmt-data #cap>div{border-color:#5AA2FF}
"""),
    "minimal": ("미니멀 화이트형", "생활 속 돈 이야기·쉬운 설명. 흰 바탕에 큰 검은 글씨", """
body.fmt-minimal{background:#f7f6f3!important;color:#111}
body.fmt-minimal #fx,body.fmt-minimal #flash,body.fmt-minimal #bigword{display:none}
body.fmt-minimal .q,body.fmt-minimal .wave,body.fmt-minimal .why2,body.fmt-minimal .num,body.fmt-minimal .big{color:#111;text-shadow:none}
body.fmt-minimal .nm,body.fmt-minimal .tag,body.fmt-minimal .lb,body.fmt-minimal .chk{color:#111}
body.fmt-minimal .sub,body.fmt-minimal #warn,body.fmt-minimal #head span{color:#666}
body.fmt-minimal .kick{background:#E3262B;color:#fff!important}
body.fmt-minimal .ln.num{color:#E3262B;text-shadow:none}
body.fmt-minimal .card2{background:#fff;border-color:#e4e1da}
body.fmt-minimal .ph{position:absolute;right:0;top:0;width:250px;height:250px;border-radius:50%;background-size:cover;background-position:center;border:6px solid #fff;box-shadow:0 10px 30px rgba(0,0,0,.15)}
body.fmt-minimal section:has(.ph){padding-top:240px}
body.fmt-minimal section:has(.ph)>*:not(.ph){zoom:.86}
body.fmt-minimal #cap>div{background:#111;border-color:#111;color:#fff}
body.fmt-minimal #tape{background:#111}body.fmt-minimal #tape div{color:#fff}
body.fmt-minimal .track{background:rgba(0,0,0,.07)}
"""),
    "kinetic": ("큰 글씨 키네틱형", "짧고 센 한마디가 이어지는 소식. 컷마다 빨강·검정·노랑 면이 바뀜", """
body.fmt-kinetic #fx,body.fmt-kinetic #bigword{display:none}
body.fmt-kinetic section::before{content:'';position:absolute;left:-65px;top:-360px;width:1080px;height:1920px;z-index:-2;background:#E3262B}
body.fmt-kinetic section:nth-of-type(3n+2)::before{background:#0B0B0D}
body.fmt-kinetic section:nth-of-type(3n)::before{background:#FFC23A}
body.fmt-kinetic section:nth-of-type(3n) .q,body.fmt-kinetic section:nth-of-type(3n) .big,body.fmt-kinetic section:nth-of-type(3n) .nm,body.fmt-kinetic section:nth-of-type(3n) .why2,body.fmt-kinetic section:nth-of-type(3n) .chk,body.fmt-kinetic section:nth-of-type(3n) .wave{color:#111;text-shadow:none}
body.fmt-kinetic section:nth-of-type(3n) .kick{background:#111;color:#FFC23A!important}
body.fmt-kinetic section:nth-of-type(3n+1) .kick{background:#111;color:#fff!important}
body.fmt-kinetic .q,body.fmt-kinetic .wave,body.fmt-kinetic .big{font-family:HBlack,HSans,sans-serif;font-weight:400;letter-spacing:-1px}
body.fmt-kinetic .ln.num{color:inherit;text-decoration:underline 10px #FFC23A;text-underline-offset:10px;text-shadow:none}
body.fmt-kinetic .up,body.fmt-kinetic .dn{color:inherit}
body.fmt-kinetic .ph{position:absolute;left:-65px;right:-65px;top:-360px;height:560px;background-size:cover;background-position:center;filter:grayscale(1) contrast(1.25);mix-blend-mode:multiply;opacity:.85;z-index:-1}
body.fmt-kinetic section:has(.ph){justify-content:flex-end}
body.fmt-kinetic section:has(.ph) .emo{display:none}
"""),
}
DEFAULT = "photo"


def css():
    return "".join(c for _, _, c in FORMATS.values())


class PhotoPlan(BaseModel):
    subject: str
    cuts: list[str]


def plan(topic, cuts):
    """컷마다 위키미디어 공용 검색어(영어). 글자·숫자만 있는 컷은 빈칸 → 주제 사진을 쓴다."""
    import llm
    lines = "\n".join(f"{i}. 자막: {c.cap} / 화면: {c.kick} {c.big.replace(chr(92) + 'n', ' ')}" for i, c in enumerate(cuts, 1))
    r = llm.Anthropic().messages.parse(
        model=PHOTO_MODEL, output_format=PhotoPlan, output_config={"effort": "low"},
        system="""경제 뉴스 쇼츠의 배경 사진을 위키미디어 공용에서 찾을 검색어를 정합니다.
- 검색어는 영어 2~4단어, 실제로 사진이 있을 법한 구체적인 것: 회사 본사 건물, 물류센터, 배송 트럭, 매장, 공장, 법원 건물, 공개 행사의 공인, 도시 풍경.
- 로고·지도·그래프·문서 화면은 찾지 않습니다. 내용과 상관없는 장식 사진도 고르지 않습니다.
- subject: 영상 전체의 주인공 사진 검색어 (예: Coupang delivery truck).
- cuts: 컷 수와 같은 개수. 그 컷에 더 맞는 사진이 있으면 검색어, 숫자·질문처럼 사진이 필요 없으면 빈 문자열.""",
        messages=[{"role": "user", "content": f"주제: {topic}\n컷:\n{lines}"}])
    p = r.parsed_output
    return p.subject, (p.cuts + [""] * len(cuts))[:len(cuts)]


def fetch(topic, cuts):
    """→ 컷마다 {"uri","credit","page"} 또는 None. 주제 사진을 먼저 찾고, 컷 사진이 없으면 주제 사진을 쓴다."""
    from publish import photos
    subject, queries = plan(topic, cuts)
    main = photos.find(subject, about=f"{topic} 영상의 대표 사진") if subject else None
    used = {main["url"]} if main else set()

    def one(args):
        q, c = args
        if not q:
            return None
        try:
            return photos.find(q, used=used, about=f"{topic}: {c.cap}")
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        got = list(pool.map(one, zip(queries, cuts)))
    out = [g or main for g in got]
    return {"subject": subject, "queries": queries, "photos": out}


def credits(photos):
    seen = []
    for p in photos or []:
        if p and p.get("credit") and p["credit"] not in seen:
            seen.append(p["credit"])
    return seen
