"""릴스 영상 형식 8가지와 컷 사진. 대본은 그대로 두고 화면만 바꾼다.

- 계정 색(검정 #0B0B0D · 빨강 #E3262B · 노랑 #FFC23A · 흰색)은 모든 형식이 같이 쓴다. 형식은 배치·글꼴·사진 쓰는 법만 다르다.
- 사진은 카드뉴스와 같은 publish/photos.py: 위키미디어 공용의 상업 이용 가능 사진(CC BY·BY-SA·CC0·퍼블릭 도메인)만,
  후보를 Claude 가 눈으로 보고 고른다. 출처는 올릴 글 끝에 모아 적는다 (CC BY 는 출처 표시가 조건).
"""
import time

from pydantic import BaseModel

MAIN_REPEAT = 2   # 대표 사진을 쓰는 컷 수 상한 (시청자 2차: 같은 사진 최대 2회)
PHOTO_MODEL = "claude-sonnet-5-5"   # 사진 검색어만 정하는 가벼운 일

# key: (이름, 어떤 영상에 어울리나, CSS). 순서가 사이트에 보이는 순서.
FORMATS = {
    "frame": ("핫코노미 v2 (뉴스 프레임형)", "기본 형식. 연구소에 모은 상위 릴스(조선비즈 66~111배)의 구성: 검은 바탕 가운데 큰 사진, 사진 아래 고정 두 줄 제목(흰색+빨강), 장식 없음", """
body.fmt-frame{background:#000!important}
body.fmt-frame #fx,body.fmt-frame #flash,body.fmt-frame #wipe1,body.fmt-frame #wipe2{display:none!important}
body.fmt-frame #head{top:262px;justify-content:flex-end;z-index:5}body.fmt-frame #head img{height:66px}
body.fmt-frame #bar{height:6px;background:#E3262B}
body.fmt-frame section{left:0;right:0;top:240px;height:1160px;padding:60px 65px 330px;background:#111;overflow:hidden}
body.fmt-frame section:has(.ph:not(.blur))>*:not(.ph){display:none}
body.fmt-frame .ph{position:absolute;inset:0;background-size:cover;background-position:center;z-index:-1}
body.fmt-frame section::after{content:'';position:absolute;left:0;right:0;bottom:0;height:560px;background:linear-gradient(180deg,rgba(0,0,0,0),rgba(0,0,0,.94) 70%);z-index:-1}
body.fmt-frame .ph.blur{filter:blur(22px) brightness(.42);transform:scale(1.12)}
body.fmt-frame .a,body.fmt-frame .ln,body.fmt-frame .slam{opacity:1!important;transform:none!important}
body.fmt-frame .card2{background:none;border:0;padding:6px 0}body.fmt-frame .card2 b{display:none}body.fmt-frame .ln.mark{background-image:none}
body.fmt-frame #headline{display:block}
body.fmt-frame .kick{background:transparent;color:#bbb!important;padding:0;font-size:40px}
body.fmt-frame #cap{top:1290px;height:96px}body.fmt-frame #headline{top:1105px}
body.fmt-frame #cap>div{background:none;border:0;padding:0;font-size:50px;font-weight:700;text-shadow:none;color:#fff}
body.fmt-frame #cap em{color:#ff5a5f}
body.fmt-frame .ln.num,body.fmt-frame .big,body.fmt-frame .num{color:#fff;text-shadow:none}body.fmt-frame .big.dn{color:#62ACFF}body.fmt-frame .big.up{color:#ff5a5f}body.fmt-frame .ln.mark{background-image:linear-gradient(transparent 62%,rgba(227,38,43,.9) 62%,rgba(227,38,43,.9) 94%,transparent 94%)}body.fmt-frame .card2 b{background:#E3262B}
"""),
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
    "ohne": ("오뉴월드형", "오뉴월드 릴스 틀: 검정 바탕, 위 날짜·굵은 흰 제목(빨간 밑줄), 가운데 고정 칸(사진은 자르지 않고 원본 비율), 아래 흰 말풍선 자막과 고정 질문. 빨간 동그라미·화살표·손글씨 라벨로 강조", ""),   # CSS 는 아래 OHNE (오뉴월드 틀 공유)
}
DEFAULT = "frame"   # 연구소 상위 릴스 벤치마크 (2026-11-06 대표 요청: 잘 된 글의 색을 가져가자)
# 모든 형식 공통: 해시태그 띠·큰 워터마크·이모지·반짝이는 상위 글 어디에도 없어 뺀다. 오른쪽 위 기준일·면책 문구는 화면에서 빼고 올릴 글 끝에만 둔다 (대표 요청 2026-11-06, 짜쳐 보인다). AI 음성 표시는 캡션과 플랫폼 AI 표시로 한다.
COMMON = "#headline{display:none}body #tape,body #bigword,body .emo,body #fx .pt{display:none!important}body #warn,body #head span{display:none!important}body #warn,body #head span{text-shadow:0 1px 4px rgba(0,0,0,.85),0 0 2px rgba(0,0,0,.9);color:#fff}body.fmt-paper #warn,body.fmt-paper #head span,body.fmt-minimal #warn,body.fmt-minimal #head span{text-shadow:none;color:#444}\n"


def _frame():
    """오뉴월드 틀 모듈 (ohneworld/studio/frame.py). 오뉴월드 제작기와 같은 코드를 쓴다."""
    import importlib.util
    import pathlib
    f = pathlib.Path(__file__).resolve().parent.parent / "ohneworld" / "studio" / "frame.py"
    spec = importlib.util.spec_from_file_location("ohne_frame", f)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


frame = _frame()
O = "body.fmt-ohne"
OHNE = frame.font_face() + frame.css(O + " ", O) + f"""
{O} #fx,{O} #wipe1,{O} #wipe2,{O} #head,{O} #headline{{display:none!important}}
{O} #date,{O} #rtitle,{O} #rq{{display:block}}{O} #rq{{top:1540px}}
{O} section{{padding:36px 60px;background:{frame.DARK_BG}}}
{O} .ph{{position:absolute;inset:0;background-color:#000;background-size:contain;background-repeat:no-repeat;background-position:center;z-index:-1}}
{O} section:has(.ph:not(.blur))>*:not(.ph):not(.kick){{display:none}}
{O} section:has(.ph:not(.blur)) .kick{{position:absolute;left:40px;bottom:26px;background:#fff!important;border-radius:12px;padding:2px 22px}}
{O} .kick{{background:none;align-self:center;font-family:Hand,HSans,sans-serif;color:{frame.RED}!important;font-size:66px;padding:0;transform:rotate(-4deg)}}
{O} .kick::after{{content:' ↘';font-family:HSans,sans-serif;font-weight:900}}
{O} .big,{O} .why2 .ln{{position:relative;color:#fff;text-shadow:none}}
{O} .big::after,{O} .why2 .ln::after{{content:'';position:absolute;left:-46px;right:-46px;top:-26px;bottom:-26px;border:9px solid {frame.RED};border-radius:50%;transform:rotate(-5deg)}}
{O} .q .ln:last-child{{background:linear-gradient(transparent 70%,{frame.RED} 70%,{frame.RED} 94%,transparent 94%)}}
{O} .ln.num,{O} .num{{color:#fff}}{O} .up{{color:#FF4B4F}}{O} .dn{{color:#5AA2FF}}
{O} .chart #dot{{r:20px;fill:none;stroke:{frame.RED};stroke-width:9px}}
{O} .card2{{background:#fff;color:#111;border:3px solid #111}}{O} .card2 b{{background:{frame.RED};color:#fff}}
"""
FORMATS["ohne"] = (*FORMATS["ohne"][:2], OHNE)


def css():
    return COMMON + "#date,#rtitle,#rq{display:none}" + "".join(c for _, _, c in FORMATS.values())


class PhotoPlan(BaseModel):
    person: str = ""
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
- person: 소식의 주인공이 실명 인물이면 그 사람의 영문 이름만 (예: Chey Tae-won). 기업·제도가 주인공이면 빈 문자열.
- subject: 영상 전체의 주인공 사진 검색어. 인물 소식이면 그 사람 이름 그대로 (예: Chey Tae-won), 아니면 장소·사물 (예: Coupang delivery truck).
- cuts: 컷 수와 같은 개수. 그 컷에 더 맞는 사진이 있으면 검색어, 숫자·질문처럼 사진이 필요 없으면 빈 문자열.""",
        messages=[{"role": "user", "content": f"주제: {topic}\n컷:\n{lines}"}])
    p = r.parsed_output
    return p.person.strip(), p.subject, (p.cuts + [""] * len(cuts))[:len(cuts)]


def fetch(topic, cuts):
    """→ 컷마다 {"uri","credit","page"} 또는 None. 주제 사진을 먼저 찾고, 컷 사진이 없으면 주제 사진을 쓴다."""
    from publish import photos
    person, subject, queries = plan(topic, cuts)
    face = None
    if person:   # 인물 소식은 그 사람 얼굴을 표지(1컷)에 먼저 (대표 요청 2026-11-07: 최태원 보드 첫 컷이 건물이었음)
        face = photos.find(person, about=f"{person}의 얼굴이 잘 보이는 인물 사진. 건물·로고·행사장 전경은 고르지 않음")
        time.sleep(1.5)
    main = face or (photos.find(subject, about=f"{topic} 영상의 대표 사진") if subject and subject != person else None)
    used = {main["url"]} if main else set()

    def one(args):
        q, c = args
        if not q:
            return None
        try:
            return photos.find(q, used=used, about=f"{topic}: {c.cap}")
        except Exception:
            return None

    got = []
    for args in zip(queries, cuts):   # 위키미디어가 동시 요청을 막아서(429) 한 장씩 쉬어 가며 받는다
        got.append(one(args))
        if args[0]:
            time.sleep(1.5)
    out, main_left = [], MAIN_REPEAT
    if face:   # 1컷은 인물 사진으로 고정
        got[0] = face
        main_left -= 1
    for i, g in enumerate(got):
        if g:
            out.append(g)
        elif main and main_left and (i == 0 or i % 4 == 0):   # 대표 사진은 첫 컷과 4컷마다, 최대 3컷만 (같은 사진 반복 방지)
            out.append(main)
            main_left -= 1
        else:
            out.append(None)
    note = (f"위키미디어 공용에서 {person}의 무료 사진을 찾지 못했어요. 컷의 '사진 바꾸기'로 직접 올릴 수 있어요." if person and not face else "")
    return {"subject": subject, "person": person, "queries": queries, "photos": out, "note": note}


def candidates(query, n=8):
    """사이트 '사진 바꾸기'의 후보: 위키미디어 공용, 상업 이용 가능 라이선스만. 빠르게 작은 미리보기만 받는다."""
    import hashlib
    import json as _json
    import re as _re
    import urllib.parse
    import urllib.request
    from publish import photos
    q = urllib.parse.urlencode({"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6, "gsrlimit": 40,
                                "gsrsearch": f"{query} filetype:bitmap", "prop": "imageinfo", "iiprop": "url|size|extmetadata", "iiurlwidth": 480,
                                "iiextmetadatafilter": "LicenseShortName|Artist"})
    try:
        pages = _json.loads(photos._get(f"{photos.API}?{q}")).get("query", {}).get("pages", {})
    except Exception:
        return []
    words = [w.lower() for w in _re.findall(r"[A-Za-z]{3,}|[가-힣]{2,}", query)]
    out = []
    for p in sorted(pages.values(), key=lambda p: p.get("index", 0)):
        info = (p.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        lic = (meta.get("LicenseShortName") or {}).get("value", "").strip()
        title = p.get("title", "")
        if not photos.OK_LICENSE.match(lic) or photos.SKIP_TITLE.search(title) or (info.get("width") or 0) < 700:
            continue
        if words and not any(w in title.lower() for w in words):   # 엉뚱한 사진(1529년 그림 등) 거르기
            continue
        thumb = info.get("thumburl")
        if not thumb:
            continue
        path = photos.CACHE / f"cand_{hashlib.sha1(thumb.encode()).hexdigest()[:16]}.jpg"
        if not path.exists():
            try:
                photos.CACHE.mkdir(parents=True, exist_ok=True)
                path.write_bytes(photos._get(thumb, 20))
            except Exception:
                continue
        artist = _re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value", "")).strip()
        row = {"url": info.get("url"), "width": info.get("width"), "height": info.get("height"), "license": lic, "artist": artist, "page": info.get("descriptionurl", ""), "title": title}
        out.append({"uri": path.as_uri(), "url": row["url"], "credit": photos.credit(row), "page": row["page"], "path": str(path),
                    "full": info.get("thumburl", "").replace("480px-", "1400px-") if "480px-" in thumb else row["url"]})
        if len(out) >= n:
            break
    return out


def full(item):
    """고른 후보의 큰 사진(1400px)을 받아 {uri,url,credit,page}로."""
    from publish import photos
    p = photos._save(item.get("full") or item["url"]) or pathlib_path(item["path"])
    return {"uri": p.as_uri(), "url": item["url"], "credit": item["credit"], "page": item["page"]}


def pathlib_path(x):
    import pathlib
    return pathlib.Path(x)


def credits(photos):
    seen = []
    for p in photos or []:
        if p and p.get("credit") and p["credit"] not in seen:
            seen.append(p["credit"])
    return seen
