"""후보 아이디가 공식 API로 조회되는지(비즈니스/크리에이터 계정인지) 빠르게 확인한다.

    python validate.py candidates.txt
candidates.txt: 한 줄에 "아이디,분야" (분야 생략 가능)
결과: output/validated.csv (조회된 계정의 이름·소개·팔로워) — 사람이 보고 accounts.csv 에 옮긴다.
"""
import csv
import os
import sys
import time

from collect import ApiError, Graph, RateLimited
from common import OUTPUT_DIR, ROOT, load_env


def main():
    load_env()
    graph = Graph(os.environ["IG_ACCESS_TOKEN"], os.environ["IG_USER_ID"],
                  os.environ.get("GRAPH_API_VERSION", "v25.0"))
    lines = [l.strip() for l in open(ROOT / sys.argv[1], encoding="utf-8") if l.strip() and not l.startswith("#")]
    seen, found = set(), []
    for line in lines:
        username, _, category = line.partition(",")
        username = username.strip().lstrip("@").lower()
        if username in seen:
            continue
        seen.add(username)
        try:
            bd = graph.get(graph.ig_user_id, {"fields": f"business_discovery.username({username})"
                                                         "{username,name,biography,followers_count,media_count}"})["business_discovery"]
            found.append({"username": bd["username"], "category": category.strip(), "name": bd.get("name") or "",
                          "followers": bd.get("followers_count") or 0, "media_count": bd.get("media_count") or 0,
                          "bio": (bd.get("biography") or "").replace("\n", " ")[:80]})
            print(f"✅ @{bd['username']} | {bd.get('name')} | 팔로워 {bd.get('followers_count'):,} | {found[-1]['bio'][:50]}")
        except ApiError:
            print(f"   @{username} 없음")
        except RateLimited as e:
            print(f"⏸ 호출 한도: {e}")
            break
        time.sleep(0.5)
    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(OUTPUT_DIR / "validated.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["username", "category", "name", "followers", "media_count", "bio"])
        w.writeheader()
        w.writerows(found)
    print(f"\n조회됨 {len(found)}개 / 후보 {len(seen)}개, API 호출 {graph.calls}회 → output/validated.csv")


if __name__ == "__main__":
    main()
