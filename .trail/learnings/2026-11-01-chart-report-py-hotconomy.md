---
title: "차트리포트 이미지 자동 생성 (chart_report.py)"
author: Hotconomy
date: 2026-11-01
branch: main
cost: { minutes: 16, tokens: 298035 }
touches:
  - ".github/workflows/telegram.yml"
  - build_site.py
  - local_ai.py
  - output/site/igx_live.json
  - output/site/igx_live_meta.json
  - output/site/thx_live.json
  - output/site/thx_live_meta.json
  - site/body.html
  - tg_analyze.py
  - assets/chart_report.html
---

## Decided
- 트레이딩뷰 계정 자동화 대신 Lightweight Charts v4.2.3(Apache 2.0)를 assets/vendor 에 넣고 HTML에 인라인 → 헤드리스 Chrome(--headless=new, 임시 user-data-dir, scale 1.5)으로 PNG 캡처.
- 시세: 야후 v8 chart 주소 직접(yfinance 미설치), 네이버 siseJson, 바이낸스 klines(실패 시 업비트 KRW).
- 수치(피보·이평·지지·추세선)는 파이썬이 계산, 이미지 문구도 고정 템플릿. 본문만 Claude(llm.py) → 계산에 없는 숫자/금지 표현이면 템플릿으로 대체.
- 사이트에는 output/site/charts/*.jpg(약 200KB, 최근 12개)만 커밋, 원본 PNG(output/charts/)는 gitignore. tg_ai today 항목에 chart 칸 추가, local_ai 가 매 차례 --from-tg 실행(새 slot만, 같은 종목 1번).

## Tried and ruled out
- 브라우저 패널로 file:// 디버그: 정적 스냅샷이라 콘솔 못 봄 → 템플릿에 window.onerror 로 화면에 에러 출력.
- chrome --enable-logging 으로 console 잡기: 안 나옴.

## Watch out
- #chart 에 z-index:0 없으면 차트 캔버스가 제목·패널·SVG 위를 덮음.
- .panel 은 box-sizing:border-box 필요(패딩 때문에 넘침).
- 'A 칸 → B' 형태 type 은 → 뒤만 보고 차트 글인지 판단(안 그러면 '코인 이슈 정리'도 차트로 잡힘). 대문자 단어 티커 추측은 CARF 같은 오탐이 나서 뺌.
- 봇 실제 발송은 아직 시험 안 함(--no-send). 커밋·푸시 전 상태.

## 2차 다듬기 (같은 날)
- 추세선: 그 뒤로 한 번도 넘지 않은 고점 중 가장 최근 것부터 시작, 지금까지 종가가 선을 안 넘은 선만 씀(70일 → 없으면 150일). 전 버전은 완만하고 이미 깨진 선을 골랐음.
- 심리적 지지: 종가 바로 아래 딱 떨어지는 가격(30·75,000)에 최근 60일 저점이 2% 안이면 수평선. 근처 군집 지지선과 겹치면 이것만.
- 시나리오 A·B는 피보·수평선·20일선 중 종가에 가장 가까운 지지·저항으로.

## 종목 요청 흐름 (3차)
- 사이트 '차트리포트 이미지' 칸 입력 → telegram.yml workflow_dispatch(chart 입력) → ai_request.py chart symbols=… → PC local_ai 가 chart_report.py "<종목들>" --send.
- 봇은 이미지 2장(짧은 캡션) 먼저, 설명 글은 sendMessage 로 따로 (캡션 1024자 제한 피함). 못 찾은 종목은 봇에 안내 메시지.
- Bash 도구 heredoc 안의 "\n" 이 실제 줄바꿈으로 들어가는 일이 있었음 → 줄바꿈 문자 들어간 코드는 Edit 도구로.

## 하루 2번 + 수동 (4차)
- 자동은 local_ai slot_once(state, "chart", (8, 19)) 로 하루 2번, 한 번에 '지금 이후 가장 가까운 차트 글' 하나만 (없으면 마지막 차트 글, 그것도 없으면 비트코인).
- 칸 키는 analyzed_at|time 이라 같은 종목도 아침·저녁 따로 다시 만듦 (예전 '같은 종목 한 번만' 중복 제거는 뺌).
- 사이트 버튼에서 칸을 비우면 chart=auto → chart_report.py --from-tg --force.
