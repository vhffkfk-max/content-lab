---
title: "쓰레드 콘텐츠 만들기 A·B·C 버튼"
author: Hotconomy
date: 2026-11-01
branch: main
cost: { minutes: 10, tokens: 197513 }
touches:
  - ".github/workflows/telegram.yml"
  - ai_request.py
  - build_site.py
  - local_ai.py
  - output/site/igx_live.json
  - output/site/igx_live_meta.json
  - output/site/thx_live.json
  - output/site/thx_live_meta.json
  - site/body.html
  - tg_analyze.py
---

## Decided
- 사이트 '지금 쓸 거리' 카드마다 A(짧은 줄 속보)·B(해석·의견)·C(질문·참여) + 'A·B·C 다 만들기' 버튼.
- 흐름: 사이트 → thread-post.yml(ai_request thpost) → PC local_ai.py(run_cycle 맨 앞) → thread_post.py(llm.py, Max) → output/site/thread_posts.json → threads-live.yml 배포.
- 사이트는 contents API(raw)로 thread_posts.json 을 15초마다 읽어 rid 로 결과를 찾음. 대기 중 요청은 localStorage th_pending 에 남김(20분).
- 말투 지침은 config/threads_abc.md — 사용자 Claude.ai 지침을 받으면 이 파일만 바꾸면 됨. '## A · 이름' 줄이 버튼 이름.
- AI 티 정규식(아니라/라기보다, 번호·기호 목록, 기사 건수·보도 시각 등) 걸리면 한 번 다시 쓰게 함.
- 활용 체크 제목은 "{pick} ({style})".

## Tried and ruled out
- 첫 버전은 첫 줄을 '기사 2건'처럼 기사 수로 시작하고 '~라기보다 ~' 반전을 씀 → 지침·정규식에 추가해서 막음.
- launch.json 의 기존 포트(8765, 8781)는 다른 세션이 씀 → content-lab-thread(8792)를 따로 둠.

## Watch out
- 공유 파일(local_ai.py, body.html, ai_request.py, build_site.py)에는 다른 세션이 커밋하지 않은 수정이 있음. HEAD 에 내 변경만 넣은 블롭을 만들어 git update-index --cacheinfo 로 스테이징함.
- 브라우저 창이 숨겨져 있으면 스크린샷이 시간 초과됨 → find/javascript 로 확인.
- 로컬 테스트는 window.fetch 를 막아서 함(api.github.com 은 가짜로 응답). 함수들이 클로저 안에 있어 fb·ghApi 에 직접 접근할 수 없음.
