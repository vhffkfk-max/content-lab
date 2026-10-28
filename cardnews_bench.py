"""카드뉴스 디자인 벤치마크용 이미지 모으기 (가끔 손으로 한 번씩).

    python cardnews_bench.py                    # config/cardnews_bench_urls.json 의 게시물 + 해시태그 인기 캐러셀
결과: output/cardnews/bench/<계정>_<코드>_<장>.jpg 와 bench/index.json (좋아요·장 수·캡션 앞부분).
깃허브에서는 cardnews-bench.yml 이 돌리고 결과를 아티팩트로 올린다 (저장소에는 안 올림).
"""
import json
import os
import pathlib
import urllib.request

from apify_instagram import run_actor
from common import ROOT, load_env

OUT = ROOT / "output" / "cardnews" / "bench"
TAGS = ["카드뉴스", "정보공유", "자기계발", "꿀팁"]   # 경제 밖에서 잘 되는 카드뉴스
PAGES = (0, 1, 2, -1)                               # 표지, 2·3장, 마지막 장


def images(p):
    kids = [c.get("displayUrl") for c in (p.get("childPosts") or []) if c.get("displayUrl")]
    return kids or p.get("images") or [p.get("displayUrl")]


def main():
    load_env()
    tok = os.environ["APIFY_TOKEN"]
    urls = json.load(open(ROOT / "config" / "cardnews_bench_urls.json"))
    econ = run_actor(tok, {"directUrls": urls, "resultsType": "posts", "resultsLimit": 1})
    tags = run_actor(tok, {"directUrls": [f"https://www.instagram.com/explore/tags/{t}/" for t in TAGS],
                           "resultsType": "posts", "resultsLimit": 40})
    side = sorted((p for p in tags if p.get("type") == "Sidecar"), key=lambda p: -(p.get("likesCount") or 0))[:16]
    OUT.mkdir(parents=True, exist_ok=True)
    index = []
    for group, rows in (("econ", econ), ("other", side)):
        for p in rows:
            imgs = images(p)
            files = []
            for i in sorted({k % len(imgs) for k in PAGES}):
                name = f"{group}_{p.get('ownerUsername')}_{p.get('shortCode')}_{i + 1}.jpg"
                try:
                    urllib.request.urlretrieve(imgs[i], OUT / name)
                    files.append(name)
                except Exception as e:
                    print("⚠️", name, e)
            index.append({"group": group, "user": p.get("ownerUsername"), "url": p.get("url"), "likes": p.get("likesCount"),
                          "comments": p.get("commentsCount"), "slides": len(imgs), "caption": (p.get("caption") or "")[:200], "files": files})
    json.dump(index, open(OUT / "index.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"✅ 경제 {len(econ)}개 + 다른 분야 {len(side)}개 → {OUT}")


if __name__ == "__main__":
    main()
