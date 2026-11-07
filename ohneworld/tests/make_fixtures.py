"""가짜 시험 파일을 만든다. 실제 백업 형식이 아니라 읽는 코드를 시험하려고 지어낸 추정 형식이다.
'비밀문자'가 든 파일은 절대 읽히면 안 되는 파일이다."""
import json
import pathlib
import shutil

FX = pathlib.Path(__file__).parent / "fixtures"


def put(rel, text):
    p = FX / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def moji(s):
    """메타 내보내기처럼 한글을 깨진 라틴 글자로."""
    return s.encode("utf-8").decode("latin-1")


def main():
    shutil.rmtree(FX, ignore_errors=True)
    put("README.md", "전부 지어낸 가짜 파일입니다 (tests/make_fixtures.py 로 만듦). 실제 백업 형식이 아닙니다.\n")
    put("naver/블로그글/2025-03-02_테슬라.html", """<!doctype html><html><head><title>가짜 블로그 제목</title><meta property="article:published_time" content="2025-03-02T09:00:00+09:00"><script>var x="스크립트글자";</script></head>
<body><h1>테슬라 박스권 돌파 300달러 지지 확인</h1><p>테슬라 가짜 본문입니다. 주가는 300달러 위로 올라섰습니다.</p><img src="img/a.png"><video src="v.mp4"></video></body></html>""")
    put("naver/블로그글/2025-03-02_테슬라/차트.png", "x")
    put("naver/posts.json", json.dumps({"blog": {"posts": [
        {"logNo": "111", "title": "금값 3% 반등 가짜 글", "addDate": "2025-05-10 08:30", "content": "<p>금값이 <b>3%</b> 반등했습니다. 3,930달러 안착이 관건입니다.</p>", "images": ["a.png", {"path": "b.png"}]},
        {"logNo": "222", "title": "코스피 약세 가짜 글", "addDate": 1749000000, "content": "코스피 2,500 약세입니다.", "images": []},
        {"logNo": "222", "title": "코스피 약세 가짜 글(겹침)", "addDate": 1749000000, "content": "겹치는 글", "images": []}]}}, ensure_ascii=False))
    put("naver/feed.xml", """<?xml version="1.0" encoding="UTF-8"?><rss><channel><item><title>인텔 가짜 XML 글</title><pubDate>Tue, 01 Jul 2025 10:00:00 +0900</pubDate><description><![CDATA[인텔 자사주 971만 달러 <img src="i.png">]]></description><guid>333</guid></item></channel></rss>""")
    put("naver/메모.txt", "아이온큐 가짜 메모 글\n2025.08.01\n아이온큐 27달러 지지 본문\n")
    put("naver/댓글/comments.json", json.dumps({"title": "비밀문자 댓글", "content": "비밀문자 댓글 본문"}, ensure_ascii=False))
    put("ig/your_instagram_activity/messages/inbox/friend_1/message_1.json", json.dumps({"participants": [{"name": "비밀문자"}], "messages": [{"sender_name": "비밀문자", "content": "비밀문자 DM", "uri": "x.jpg"}]}, ensure_ascii=False))
    put("ig/personal_information/personal_information.json", json.dumps({"profile": [{"string_map_data": {"Email": {"value": "비밀문자@example.com"}}}]}, ensure_ascii=False))
    posts = [
        {"media": [{"uri": "media/posts/202503/a.jpg", "creation_timestamp": 1740960000, "title": "", "media_metadata": {"photo_metadata": {"exif_data": [{"latitude": 37.5, "비밀문자": "위치"}]}}},
                   {"uri": "media/posts/202503/b.jpg", "creation_timestamp": 1740960000, "title": ""}],
         "title": moji("테슬라 300달러 돌파,\n이제 지지 확인일까?\n\n그런데 차트는 박스권 상단입니다\n✔ 300달러 지지\n\n댓글로 의견 남겨주세요!\n저장해두세요\n본 콘텐츠는 투자자문이 아닙니다"), "creation_timestamp": 1740960000},
        {"media": [{"uri": "media/posts/202505/c.jpg", "creation_timestamp": 1747000000, "title": moji("금값 3% 반등, 3,930달러 안착이 관건")}]},
        {"media": [{"uri": "media/posts/202507/d.jpg", "creation_timestamp": 1752000000, "title": moji("오늘 점심 사진 (블로그와 상관없는 글)")}]}]
    put("ig/your_instagram_activity/media/posts_1.json", json.dumps(posts))
    put("ig/your_instagram_activity/media/reels.json", json.dumps({"ig_reels_media": [{"media": [{"uri": "media/reels/202506/r.mp4", "creation_timestamp": 1749100000, "title": moji("코스피 2,500 약세, 차트로 봅시다"), "media_metadata": {"video_metadata": {"exif_data": [{"device_id": "비밀문자"}]}}}]}]}))
    put("ig/logged_information/past_instagram_insights/posts_1.json", json.dumps({"organic_insights_posts": [{"creation_timestamp": 1740960000, "string_map_data": {"Accounts reached": {"value": "1,000"}, "Saves": {"value": "50"}}}]}))


if __name__ == "__main__":
    main()
