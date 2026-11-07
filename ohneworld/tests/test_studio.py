"""가짜 파일 시험: python -m unittest discover tests  (인터넷·Claude·음성 없이 돌아감)"""
import json
import pathlib
import shutil
import sys
import tempfile
import unittest
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import make_fixtures  # noqa: E402
from studio import analyze, facts, feed, ig_export, match, naver_backup, write  # noqa: E402

FX = ROOT / "tests" / "fixtures"
make_fixtures.main()


class Naver(unittest.TestCase):
    def setUp(self):
        self.posts, self.rep = naver_backup.read_all(FX / "naver")
        self.by = {p["title"]: p for p in self.posts}

    def test_four_formats(self):
        self.assertEqual(self.rep["posts"], 5)   # html, json 2(겹침 제거), xml, txt
        for t in ("금값 3% 반등 가짜 글", "인텔 가짜 XML 글", "아이온큐 가짜 메모 글"):
            self.assertIn(t, self.by)

    def test_fields(self):
        p = self.by["금값 3% 반등 가짜 글"]
        self.assertTrue(p["date"].startswith("2025-05-10"))
        self.assertEqual(p["images"], ["a.png", "b.png"])
        self.assertNotIn("<b>", p["text"])
        h = self.by["테슬라 박스권 돌파 300달러 지지 확인"]
        self.assertTrue(h["date"].startswith("2025-03-02"))
        self.assertNotIn("스크립트", h["text"])
        self.assertIn("img/a.png", h["images"])
        self.assertTrue(any(x.endswith("차트.png") for x in h["images"]))
        self.assertIn("v.mp4", h["videos"])

    def test_comments_not_read(self):
        self.assertNotIn("비밀문자", json.dumps(self.posts, ensure_ascii=False))
        self.assertGreaterEqual(self.rep["skipped_paths"], 1)


class Instagram(unittest.TestCase):
    def setUp(self):
        self.posts, self.rep = ig_export.read_all(FX / "ig")

    def test_counts_kinds(self):
        self.assertEqual(self.rep["posts"], 4)
        self.assertEqual(sorted(p["kind"] for p in self.posts), ["릴스", "사진", "사진", "캐러셀"])

    def test_korean_restored(self):
        self.assertTrue(self.posts[0]["caption"].startswith("테슬라 300달러"))

    def test_dm_not_opened(self):
        opened = " ".join(self.rep["opened"])
        self.assertNotIn("messages", opened)
        self.assertNotIn("personal_information", opened)
        self.assertGreaterEqual(self.rep["skipped_paths"], 2)
        blob = json.dumps(self.posts, ensure_ascii=False)
        for word in ("비밀문자", "latitude", "media_metadata"):
            self.assertNotIn(word, blob)

    def test_dm_never_read_even_in_zip(self):
        """압축 안에서도 DM 파일을 꺼내지 않고, 폴더 밖을 가리키는 이름은 무시한다."""
        with tempfile.TemporaryDirectory() as t:
            z = pathlib.Path(t) / "export.zip"
            with zipfile.ZipFile(z, "w") as w:
                for f in (FX / "ig").rglob("*.json"):
                    w.write(f, f.relative_to(FX / "ig").as_posix())
                w.writestr("../탈출.json", "{}")
            reads, real = [], zipfile.ZipFile.read
            zipfile.ZipFile.read = lambda self, n, *a: (reads.append(n), real(self, n, *a))[1]
            try:
                posts, _ = ig_export.read_all(t)
            finally:
                zipfile.ZipFile.read = real
            self.assertEqual(len(posts), 4)
            self.assertFalse([n for n in reads if "messages" in n or "personal_information" in n or ".." in n])

    def test_insights_attached(self):
        self.assertEqual(self.posts[0]["metrics"], {"reach": 1000, "saved": 50})


class Analysis(unittest.TestCase):
    def run_it(self, metrics_text=None):
        t = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, t)
        m = t / "수치.csv"
        if metrics_text:
            m.write_text(metrics_text, encoding="utf-8")
        return analyze.analyze(FX / "naver", FX / "ig", t / "분석", t / "데이터", m), t

    def test_pairs(self):
        r, t = self.run_it()
        rows = (t / "분석" / "짝.csv").read_text(encoding="utf-8-sig")
        self.assertIn("테슬라 박스권", rows)
        self.assertIn("금값 3% 반등", rows)
        self.assertNotIn("오늘 점심", rows)
        self.assertGreaterEqual(r["pairs"]["짝없는_게시물"], 1)

    def test_with_metrics_from_insights(self):
        r, t = self.run_it()
        self.assertEqual(r["mode"], "성과 있음")
        self.assertEqual(r["performance"]["rated"], 1)
        self.assertIn("표본 적음", (t / "분석" / "패턴_보고서.md").read_text(encoding="utf-8"))

    def test_without_metrics(self):
        t = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, t)
        shutil.copytree(FX / "ig" / "your_instagram_activity", t / "ig" / "your_instagram_activity")
        r = analyze.analyze(FX / "naver", t / "ig", t / "a", t / "d", t / "없음.csv")
        self.assertEqual(r["mode"], "성과 없음")
        self.assertIsNone(r["performance"])
        self.assertIn("잘 된 패턴이라고 말할 수 없습니다", (t / "a" / "패턴_보고서.md").read_text(encoding="utf-8"))

    def test_metrics_csv(self):
        r, _ = self.run_it("날짜,캡션앞부분,주소,도달,저장,좋아요,댓글,공유\n2025-06-05,코스피,,2000,20,5,1,0\n")
        self.assertEqual(r["metrics_from_csv"], 1)
        self.assertEqual(r["performance"]["rated"], 2)

    def test_empty_backup(self):
        t = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, t)
        r = analyze.analyze(t / "n", t / "i", t / "a", t / "d", t / "m.csv")
        self.assertEqual(r["posts"], 0)
        self.assertIn("백업 파일이 아직 없습니다", (t / "a" / "패턴_보고서.md").read_text(encoding="utf-8"))


class Feed(unittest.TestCase):
    RSS = """<rss><channel><item><title><![CDATA[제목]]></title><guid>https://blog.naver.com/kis6574/999</guid><pubDate>Thu, 05 Nov 2026 16:00:00 +0900</pubDate><category>주식</category>
<description><![CDATA[요약 글 <img src="x"> 끝]]></description></item></channel></rss>"""

    def test_merge(self):
        rows = feed.merge(feed.parse_rss(self.RSS), [{"key": "blog:999", "text": "바레이션", "check": ["a"], "title": "t"}, {"key": "ig:abc", "source": "인스타", "text": "v", "title": "x", "made": "2026-11-04T10:00:00+09:00"}])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["key"], "blog:999")
        self.assertEqual(rows[0]["summary"], "요약 글 끝")
        self.assertEqual(rows[0]["variation"], "바레이션")
        self.assertTrue(rows[0]["date"].startswith("2026-11-05T16:00"))


class Facts(unittest.TestCase):
    def test_reading(self):
        cases = {"$79.93": "칠십구 점 구삼 달러", "77~78달러": "칠십칠에서 칠십팔 달러", "$77~78": "칠십칠에서 칠십팔 달러", "6.4% 급락": "육 점 사 퍼센트 급락", "10/29 종가": "시월 이십구일 종가",
                 "6월과 7월": "유월과 칠월", "+11%": "플러스 십일 퍼센트", "13.4억 달러": "십삼 점 사억 달러", "10억 달러": "십억 달러", "3분기": "삼분기", "1,234원": "천이백삼십사원", "0.9%p": "영 점 구 퍼센트 포인트", "12,500": "만 이천오백"}
        for k, v in cases.items():
            self.assertEqual(facts.to_reading(k), v, k)

    def test_numbers(self):
        src = facts.nums("종가 $79.93, 지지 77~78달러, 1,234")
        self.assertEqual(facts.unknown_numbers("79.93 그리고 1234 그리고 3", src), [])
        self.assertEqual(facts.unknown_numbers("80 달러", src), ["80"])

    def test_advice(self):
        self.assertTrue(facts.problems("지금 분할 매수", "x", set()))
        self.assertFalse(facts.problems("지지 확인이 먼저", "x", set()))


class ScriptCheck(unittest.TestCase):
    def script(self, **kw):
        base = dict(keyword="덱스컴", cover_sub="왜 빠졌나", cover_queries=[], basis="10/29 종가 기준",
                    slides=[write.Slide(form="chart", tag="차트", title="제목", chart="차트1.png", lines=["79.93"])] * 6,
                    caption="79.93 10/29 종가 기준 투자 판단은 본인", hashtags=[], check=[],
                    reel=[write.Scene(kind="word", big="말", lines=[write.ReelLine(say="칠", cap="칠")])] * 7)
        return write.Script(**{**base, **kw})

    def mat(self):
        return {"text": "79.93 10/29", "checked": "", "info": {"basis": "10/29 종가 기준"}, "charts": [pathlib.Path("차트1.png")]}

    def test_ok(self):
        self.assertEqual(write.check(self.script(), self.mat()), [])

    def test_date_in_words(self):
        m = self.mat()
        m["checked"] = "11/04 $88.48"
        self.assertEqual(facts.unknown_numbers("11월 4일", write.source_numbers(m)), [])

    def test_blocks_made_up_number(self):
        self.assertTrue(any("80" in x for x in write.check(self.script(cover_sub="80달러 간다"), self.mat())))

    def test_blocks_missing_disclaimer(self):
        self.assertTrue(write.check(self.script(caption="79.93"), self.mat()))


class Srt(unittest.TestCase):
    def test_srt(self):
        from studio.reel import make_srt
        s = make_srt([{"caps": [{"t": .15, "e": 1.5, "text": "가"}, {"t": 61.5, "e": 62, "text": "나"}]}])
        self.assertIn("00:00:00,150 --> 00:00:01,500\n가", s)
        self.assertIn("00:01:01,500 --> 00:01:02,000\n나", s)


class Capcut(unittest.TestCase):
    def test_timeline(self):
        from studio import capcut_draft as cd
        tpl = json.loads((cd.TEMPLATE / "draft_content.json").read_text(encoding="utf-8"))
        srt = chr(0xFEFF) + "\n\n".join(["1\n00:00:00,150 --> 00:00:01,500\n첫 자막", "2\n00:00:01,500 --> 00:00:03,000\n둘째 +6.64%"]) + "\n"
        caps = cd.parse_srt(srt)
        self.assertEqual([c["text"] for c in caps], ["첫 자막", "둘째 +6.64%"])
        d = cd.build_content(tpl, [("a/01.mp4", 2000000), ("a/02.mp4", 1000000)], ("v.m4a", 3100000), ("m.m4a", 3000000), caps)
        self.assertEqual([t["type"] for t in d["tracks"]], ["video", "audio", "audio", "text"])
        v = d["tracks"][0]["segments"]
        self.assertEqual(v[1]["target_timerange"], {"start": 2000000, "duration": 1000000})
        self.assertEqual(d["duration"], 3000000)
        self.assertEqual(d["tracks"][1]["segments"][0]["target_timerange"]["duration"], 3000000)
        ids = {m["id"] for k in d["materials"].values() for m in k}
        for t in d["tracks"]:
            for s in t["segments"]:
                self.assertIn(s["material_id"], ids)
                self.assertTrue(set(s["extra_material_refs"]) <= ids)
        self.assertEqual(json.loads(d["materials"]["texts"][1]["content"])["text"], "둘째 +6.64%")
        self.assertEqual(d["canvas_config"]["width"], 1080)
        d2 = cd.build_content(tpl, [("a/01.mp4", 1400000), ("a/02.mp4", 2000000)], ("v.m4a", 1), ("m.m4a", 1), caps, dark_scenes={0})
        self.assertEqual([t["text_color"] for t in d2["materials"]["texts"]], ["#FFFFFF", "#111111"])


class Match(unittest.TestCase):
    def test_outside_window(self):
        b = [{"id": "b", "date": "2025-01-01T09:00+09:00", "title": "테슬라", "text": "테슬라 돌파"}]
        p = [{"id": "p", "date": "2025-03-01T09:00+09:00", "caption": "테슬라 돌파"}]
        self.assertEqual(match.assign(b, p), [])


if __name__ == "__main__":
    unittest.main()
