# 텔레그램 방 분석 켜기 — 15분

대표님 텔레그램 계정으로 **가입해 있는 방(비공개 포함)** 의 글을 이 PC에서 **실시간**으로 모으고,
30분마다 사이트 **텔레그램** 탭을 갱신해요. 평소의 3배 이상 반응이 나온 글은 내 텔레그램 **저장된 메시지**로 바로 알려줘요.

- 사이트에 보이는 것: 다른 방 반응 큰 글(원문·방 이름 포함), 잘 되는 공식·시간대, **오늘 우리 방에 올릴 문구**
- 로그인 정보(`data/telegram.session`)는 이 PC에만 있고 저장소에 올라가지 않아요. **이 파일은 계정 전체 권한이라 누구에게도 주지 마세요.**
- 비용: 수집·30분 갱신·알림은 무료. Claude '오늘의 문구'는 하루 한 번(07시 이후)만 써서 하루 약 0.2~0.4달러
- PC가 켜져 있는 동안만 모여요. PC를 켜고 로그인하면 자동으로 다시 시작해요(멈춰도 1분 뒤 다시 시작).

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

## 5. 실시간 수집 켜기 (한 번만)
```
powershell -ExecutionPolicy Bypass -File .	g_live_install.ps1
```
실시간 수집 전용으로 한 번 더 로그인해요(전화번호 → 앱으로 온 코드 → 2단계 비밀번호).
끝나면 작업 스케줄러 `content-lab-telegram-live` 가 PC 로그온 때마다 `tg_live.py` 를 켜요.

- 기록: `data	g_live.log`
- 알림 기준 바꾸기: `tg_live.py` 의 `ALERT_X`(배수), `ALERT_HOURS`(몇 시간 안 글), `ALERT_MAX`(한 번에 최대 개수)

## 끄기 / 바꾸기
- 방 추가·제외: `telegram_chats.csv` 의 분석 칸 수정 후 작업 스케줄러에서 `content-lab-telegram-live` 다시 시작
  (새로 가입한 방은 `python tg_login.py` 다시 실행하면 목록에 추가)
- 실시간 수집 끄기: 작업 스케줄러에서 `content-lab-telegram-live` 삭제
- 로그아웃: 텔레그램 앱 → 설정 → 기기 → 이 PC 세션 종료 (로그인을 두 번 해서 세션이 2개예요)

## 회원 참여도 (내 방, 상품 지급용)
```
python tg_participation.py --chat <방 id> --start 2026-10-01 --end 2026-10-31
```
결과는 `output\participation\` 에 엑셀로만 저장돼요 (회원 정보라 저장소에 안 올라감).
