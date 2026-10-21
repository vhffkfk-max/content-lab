# 경제 인스타 트렌드 리서치

한국·해외 경제(미국주식·국내주식·코인) 인스타 계정을 공식 API로 수집해서
**어떤 주제·형식·첫 문장·시간대가 반응이 좋은지** 분석하고, **이유와 함께 콘텐츠를 추천**합니다.

## 처음 한 번
1. `SETUP_GUIDE.md` 대로 API 연결 (약 30분)
2. `accounts.csv` 에 분석할 계정 아이디 추가 (지역: `KR` 또는 `US`)
3. `hashtags.csv` 에 볼 해시태그 확인 (7일에 30개 제한)

## 매번 실행
`run.bat` 더블클릭 → 수집 → 분석 → 리포트가 브라우저로 열려요.

또는 직접:
```
python collect.py      # 데이터 수집 (data/insta.db 에 누적)
python analyze.py      # 분석 + output/report.html 생성
```
**며칠 간격으로 꾸준히 돌릴수록** 팔로워 성장, 주제 추세가 정확해져요.

## 웹사이트 (말희아빠 & 파로파트너스 컨텐츠 연구소)
https://claude.ai/artifact/U7KbV28HRGSRQXriHe7DLT

수집 후 `python export_site.py` 가 `output/site/*.json` 을 만들고,
Claude에게 "연구소 사이트 갱신해줘" 하면 그 파일들을 사이트에 올려요.
(사이트의 데이터 하나 = output/site 의 같은 이름 파일 하나: summary, recs, rec_reasons, rec_examples,
insights, topics, patterns, accounts, top_posts)
기본은 비공개예요. 팀원에게 보여주려면 사이트 오른쪽 위 공유 메뉴에서 직접 공유하세요.

## API 연결 전에 미리 보기
```
python demo_data.py
python analyze.py --db data/demo.db
```
가짜 데이터라 숫자는 의미 없어요. 화면 구성만 확인하는 용도예요.

## 추천 방식
- **평소 대비 ○배**: 게시물 반응(좋아요 + 댓글×3) ÷ 그 계정 반응의 중앙값
- 추천 유형
  - **국내·해외 모두 강세**: 어디서나 통하는 주제
  - **국내 검증 주제**: 한국 팔로워에게 이미 잘 되는 주제
  - **해외 선행 주제**: 해외에서 터지는데 한국엔 아직 별로 없는 주제 → 선점 기회
  - **해외 벤치마킹 주제**: 한국도 다루지만 반응이 약함 → 해외 형식·첫 문장 따라 하기
- 주제 분류 키워드는 `topics.py` 에서 자유롭게 추가할 수 있어요.

## 파일
| 파일 | 역할 |
|---|---|
| `collect.py` | 공식 API로 계정·게시물·해시태그 수집 |
| `analyze.py` | 분석·추천 생성 |
| `report.py` | HTML 리포트 화면 |
| `topics.py` | 주제·첫 문장 스타일 분류 규칙 |
| `get_token.py` | 토큰 발급 도우미 |
| `output/report.json` | 분석 결과 원본 (Claude에게 "리포트 보고 대본 써줘" 할 때 사용) |
