"""BGM 추천 검색어로 메타 오디오 API(GET /ig_audio)에서 실제 곡 후보를 찾는다. 연구소 사이트에서 들어 볼 수 있게.

- 나오는 곡은 메타가 외부 앱에 허가한 곡이라 인스타 앱 목록과 다를 수 있다.
- url(미리듣기)은 약 1.5일 뒤 만료된다. audio_id 는 릴스 발행(audio_configuration)에 쓴다.
- 검색은 말뜻이 아니라 글자로 찾는 듯하다(한글 '긴장감' 0곡, 2026-11-05). 분위기는 사람이 듣고 판단한다.
- 실패해도 초안을 막지 않는다. 후보가 없으면 빈 목록.
"""
import os

from publish.instagram import Instagram, PublishError

MAX_TRACKS = 5
MIN_SEC = 15


def _search(ig, query):
    return ig._call("GET", "ig_audio", {"audio_type": "music", "user_id": ig.user_id, "search_query": query}).get("audio", [])


def find(search_terms, ig=None):
    """검색어 목록 → [{audio_id, title, artist, sec, url}]. 여러 검색어에서 고루 뽑는다."""
    terms = [t for t in (search_terms or []) if t][:3]
    if not terms:
        return []
    if ig is None:
        user, token = os.environ.get("IG_USER_ID"), os.environ.get("IG_ACCESS_TOKEN")
        if not (user and token):
            return []
        ig = Instagram(user, token)
    groups = []
    try:
        for term in terms:
            found = _search(ig, term)
            words = term.split()
            if not found and len(words) > 1:   # 긴 검색어는 잘 안 맞아서 앞 두 단어로 한 번 더
                found = _search(ig, " ".join(words[:2]))
            groups.append(found)
    except PublishError as e:
        print("⚠️ BGM 곡 검색 실패 (초안은 그대로):", e.reason)
    out, seen = [], set()
    for i in range(MAX_TRACKS):
        for found in groups:
            if i < len(found) and len(out) < MAX_TRACKS:
                x = found[i]
                sec = (x.get("duration_in_ms") or 0) // 1000
                if x.get("audio_id") and x.get("download_url") and sec >= MIN_SEC and x["audio_id"] not in seen:
                    seen.add(x["audio_id"])
                    out.append({"audio_id": x["audio_id"], "title": x.get("title", ""), "artist": x.get("display_artist", ""), "sec": sec, "url": x["download_url"]})
    return out
