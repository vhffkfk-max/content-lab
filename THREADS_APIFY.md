# 쓰레드 자동 수집 (Apify) 켜기 — 10분

매일 06:00에 경제 키워드 검색 인기 글 + 지정 계정 글을 **좋아요·답글·리포스트 수와 함께** 모아요.
팀 폼에 **링크만** 넣어도 본문과 숫자를 자동으로 채워요.

- 쓰는 서비스: Apify의 `themineworks/threads-scraper` (공개 글만 읽음, 우리 쓰레드 계정 로그인 없음)
- 비용: 글 1,000개당 약 1.2~2달러. 지금 설정(키워드 10개 × 20개 + 계정 10곳 + 팀 링크)은 하루 약 300개 → **하루 0.6달러 안팎, 한 달 15~20달러**
- Apify 무료 크레딧(월 5달러)으로는 1주일 남짓만 돌아가요. 계속 쓰려면 유료 플랜이 필요해요(요금은 apify.com/pricing 에서 확인).

## 1. 가입
https://apify.com → Sign up (구글 계정으로 가입 가능)

## 2. 토큰 복사
오른쪽 위 프로필 → **Settings → API & Integrations** → Personal API tokens 의 토큰 **복사**
> 토큰은 채팅에 붙여넣지 마세요.

## 3. GitHub 비밀값으로 등록 (터미널)
```
gh secret set APIFY_TOKEN --repo vhffkfk-max/content-lab
```
입력하라고 나오면 붙여넣고 Enter (화면에 안 보여도 정상).

## 4. 확인
GitHub 저장소 → Actions → 매일 실행 → **Run workflow** 로 바로 돌려 보거나, 다음 날 06:00 이후 사이트 **쓰레드 → 자동 수집 인기 글** 확인.

## 바꾸고 싶을 때
- 검색 키워드·개수: `apify_threads.py` 의 `THREADS_KEYWORDS`, `PER_KEYWORD`
- 볼 계정: `threads_accounts.csv` 에 쓰레드 아이디 한 줄씩
- 구글 폼의 '본문' 질문은 **선택**으로 바꿔 두면 팀원이 링크만 넣어도 돼요.
- 끄기: GitHub 비밀값 `APIFY_TOKEN` 삭제 → 자동으로 건너뜀
