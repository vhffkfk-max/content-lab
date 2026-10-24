"""output/report.json 을 웹 대시보드(컨텐츠 연구소 사이트)용 표 형태 JSON 파일들로 나눈다.

    python export_site.py   →  output/site/*.json
"""
import json

from common import OUTPUT_DIR

SITE = OUTPUT_DIR / "site"


def write(name, rows):
    (SITE / f"{name}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  {name}.json: {len(rows)}행")


def main():
    d = json.loads((OUTPUT_DIR / "report.json").read_text(encoding="utf-8"))
    SITE.mkdir(parents=True, exist_ok=True)
    c = d["counts"]
    write("summary", [{
        "generated_at": d["generated_at"], "days": d["days"],
        "accounts_kr": c["accounts_kr"], "accounts_foreign": c["accounts_foreign"],
        "recent_posts": c["recent_posts"], "hashtag_posts": c["hashtag_posts"],
    }])

    recs, reasons, examples = [], [], []
    for rank, r in enumerate(d["recommendations"], 1):
        recs.append({"rank": rank, "topic": r["topic"], "kind": r["kind"], "confidence": r["confidence"],
                     "title_idea": r["title_idea"], "format": r["format"] or "", "hook": r["hook"] or "",
                     "slot": r["slot"] or "", "kr_avg": r["kr"]["avg"], "kr_n": r["kr"]["n"],
                     "foreign_avg": r["foreign"]["avg"], "foreign_n": r["foreign"]["n"]})
        reasons += [{"rank": rank, "n": i, "reason": x} for i, x in enumerate(r["reasons"])]
        examples += [{"rank": rank, "n": i, "username": e["username"], "region": e["region"],
                      "outlier": e["outlier"], "format": e["format"], "caption": e["caption"],
                      "permalink": e["permalink"] or ""} for i, e in enumerate(r["examples"])]
    write("recs", recs)
    write("rec_reasons", reasons)
    write("rec_examples", examples)
    write("insights", [{"n": i, "text": t} for i, t in enumerate(d["insights"])])

    write("topics", [{"topic": t["topic"], "kr_avg": t["kr"]["avg"], "kr_n": t["kr"]["n"],
                      "foreign_avg": t["foreign"]["avg"], "foreign_n": t["foreign"]["n"],
                      "hashtag_hits": t["hashtag_hits"]} for t in d["topics"] if t["topic"] != "기타"])

    patterns = []
    for group, by_region in (("형식", d["formats"]), ("첫 문장", d["hooks"]), ("행동 유도", d["ctas"]),
                             ("캡션 길이", d["lengths"]), ("해시태그 개수", d["tagcounts"])):
        for region, rows in by_region.items():
            patterns += [{"group": group, "region": region, "key": r["key"], "avg": r["avg"], "n": r["n"]}
                         for r in rows if r["n"]]
    patterns += [{"group": "시간대", "region": "한국", "key": r["key"], "avg": r["avg"], "n": r["n"]}
                 for r in d["slots_kr"] if r["n"]]
    write("patterns", patterns)

    write("accounts", [{
        "username": a["username"], "region": a["region"], "category": a["category"] or "",
        "followers": a["followers"], "posts_per_week": a["posts_per_week"], "er": a["er"],
        "growth_pct": a["growth"]["pct"] if a["growth"] else None,
        "likes_hidden": a["likes_hidden"],
        "top_outlier": a["top_post"]["outlier"] if a["top_post"] else None,
        "top_caption": a["top_post"]["caption"] if a["top_post"] else "",
        "top_link": (a["top_post"]["permalink"] or "") if a["top_post"] else "",
    } for a in d["accounts"]])

    write("top_posts", [{
        "rank": i, "username": p["username"], "region": p["region"], "outlier": p["outlier"],
        "topics": ", ".join(p["topics"]), "format": p["format"], "hook": p["hook"],
        "date": p["date"], "caption": p["caption"], "permalink": p["permalink"] or "",
        "likes": p["likes"], "comments": p["comments"],
    } for i, p in enumerate(d["top_posts"], 1)])
    write("calendar", d["calendar"])
    g = d.get("google") or {}
    write("google_meta", [{"date": g.get("date"), "topics": len(g.get("topics") or [])}])
    write("google_topics", [{k: (", ".join(v) if isinstance(v, list) else v) for k, v in x.items()} for x in g.get("topics") or []])
    write("google_headlines", g.get("headlines") or [])
    write("google_trends", g.get("trends") or [])
    fo = d.get("foreign") or {}
    write("fo_hot", [{k: v for k, v in p.items() if k != "full"} for p in fo.get("hot") or []])
    write("fo_topics", fo.get("topics") or [])
    write("acc_details", d.get("acc_details") or [])
    write("acc_patterns", d.get("acc_patterns") or [])
    write("acc_tops", [{k: v for k, v in p.items()} for p in d.get("acc_tops") or []])
    own = d.get("own") or {}
    write("own_meta", own.get("meta") or [])
    write("own_posts", own.get("posts") or [])
    write("own_formats", own.get("formats") or [])
    write("threads_saved", d.get("threads_saved") or [])
    write("threads_saved_stats", d.get("threads_saved_stats") or [])
    tx = d.get("threads_auto") or {}
    for k in ("meta", "hot", "top", "rising", "topics", "formats", "accounts", "rank"):
        write(f"thx_{k}", tx.get(k) or [])
    th = d.get("threads") or {}
    write("threads_meta", th.get("meta") or [])
    write("threads_topics", th.get("topics") or [])
    write("threads_posts", th.get("posts") or [])
    write("press_headlines", g.get("press") or [])
    write("press_popular", g.get("popular") or [])
    write("google_opportunities", [{k: (", ".join(v) if isinstance(v, list) else v) for k, v in x.items()} for x in g.get("opportunities") or []])
    write("this_week", [{k: (", ".join(v) if isinstance(v, list) else v) for k, v in p.items()} for p in d["this_week"]])
    write("this_week_accounts", d["this_week_accounts"])
    print(f"✅ 사이트 데이터 → {SITE}")


if __name__ == "__main__":
    main()
