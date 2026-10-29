"""무료 자료(구글 뉴스·급상승 검색어·경제 매체 RSS)만 새로 모아 사이트 표를 갱신한다. Claude·Apify 안 씀 (비용 0).

    python live_news.py
깃허브 live-news.yml 이 5분마다 돌린다. 같은 기사는 DB에서 링크로 한 번만 저장되고(수집기),
사이트 표에선 제목이 같은 기사도 한 번만 보인다(export_site.dedupe).
추천·기획안은 건드리지 않는다 — 그건 매일 06:00 분석이 맡는다.
"""
import json
from datetime import datetime, timedelta, timezone

import google_collect
import press_collect
from analyze import KST, google_section, load_posts
from common import DEFAULT_DB, connect
from export_site import SITE, write, write_news


def links(name):
    try:
        return {r.get("link") for r in json.loads((SITE / f"{name}.json").read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return set()


def main():
    before = {n: links(n) for n in ("google_headlines", "press_headlines")}
    google_collect.main()
    press_collect.main()

    conn = connect(DEFAULT_DB)
    now = datetime.now(timezone.utc)
    _, posts, _ = load_posts(conn)
    since = now - timedelta(days=30)   # analyze.py 기본값과 같게 — 기회 주제 계산이 매일 분석과 어긋나지 않도록
    recent = [p for p in posts if p["dt"] >= since and not p["promo"] and not p["lead"]]
    g = google_section(conn, recent, now)
    write_news(g)

    new = {n: len(links(n) - before[n]) for n in before}
    write("live_meta", [{"updated_at": now.astimezone(KST).strftime("%Y-%m-%d %H:%M"),
                         "new_press": new["press_headlines"], "new_google": new["google_headlines"]}])
    print(f"✅ 새 기사: 매체 {new['press_headlines']}개, 구글 뉴스 {new['google_headlines']}개")


if __name__ == "__main__":
    main()
