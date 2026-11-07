"""멀티계정 콘텐츠 레이어 — 기존 수집(news_pool)은 그대로 두고, 그 소재를 계정별로 변주한다.

    python -m acclab.refine                 # 소재 정제 (raw 묶음 → 사실/해석 분리 + 카테고리 태그 + 계정 라우팅)
    python -m acclab.generate hotconomy     # 그 계정 몫 소재로 쓰레드 글 + 영상 대본
    python -m acclab.run                    # 정제 + 준비된(ready) 계정 전부 (local_ai.py 가 하루 3번 부름)
    python -m acclab.pages                  # public/accounts/ 페이지만 다시 (build_site.py 가 부름)
"""
