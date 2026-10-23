# 텔레그램 방 분석 켜기 — 15분

대표님 텔레그램 계정으로 **가입해 있는 방(비공개 포함)** 의 최근 7일 글을 이 PC에서 매일 07:00에 모으고,
GitHub 서버가 Claude로 분석해 사이트 **텔레그램** 탭에 올려요.

- 사이트에 보이는 것: 다른 방 반응 큰 글(원문·방 이름 포함), 잘 되는 공식·시간대, **오늘 우리 방에 올릴 문구**
- 로그인 정보(`data/telegram.session`)는 이 PC에만 있고 저장소에 올라가지 않아요. **이 파일은 계정 전체 권한이라 누구에게도 주지 마세요.**
- 비용: 수집은 무료, Claude 분석은 하루 약 0.2~0.4달러
- 07:00에 PC가 꺼져 있었으면, 켜고 로그인한 직후 자동으로 한 번 돌아요.

## 1. 텔레그램 API 키 받기
1. https://my.telegram.org 접속 → 전화번호(+8210…) 입력 → 텔레그램 앱으로 온 코드 입력
2. **API development tools** → App title `hotconomy lab`, Short name `hotlab`, Platform `Desktop` → Create
3. 나오는 **api_id**(숫자)와 **api_hash**(영문·숫자) 를 확인 — 채팅에는 붙여넣지 마세요.

## 2. .env 에 넣기
`insta-research` 폴더의 `.env` 파일을 메모장으로 열고 맨 아래에 두 줄 추가 후 저장:
```
TG_API_ID=숫자
TG_API_HASH=영문숫자
```

## 3. 로그인 + 방 목록 만들기 (터미널)
```
python tg_login.py
```
전화번호 → 앱으로 온 코드 → (설정했다면) 2단계 비밀번호를 직접 입력해요.
끝나면 가입한 채널·그룹 목록이 `telegram_chats.csv` 로 만들어져요.

## 4. 분석할 방 고르기
`telegram_chats.csv` 를 엑셀로 열고 **분석** 칸에
- 다른 업체 방: `o`
- 내 채널: `내방`
저장. (어떤 방인지 Claude에게 이름으로 말해 주면 대신 표시해 줘요.)

## 5. 첫 수집
```
python tg_collect.py
```
그다음부터는 매일 07:00 자동(작업 스케줄러 `content-lab-telegram`).

## 끄기 / 바꾸기
- 방 추가·제외: `telegram_chats.csv` 의 분석 칸 수정 (새로 가입한 방은 `python tg_login.py` 다시 실행하면 목록에 추가)
- 자동 실행 끄기: 작업 스케줄러에서 `content-lab-telegram` 삭제
- 로그아웃: 텔레그램 앱 → 설정 → 기기 → 이 세션 종료
