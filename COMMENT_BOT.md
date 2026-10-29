# 댓글 기회 봇 (1단계) — 여분 PC에 설치

쓰레드나 인스타 글 링크를 연구소 알림 봇(@hotconomy_lab_bot)에게 보내면, 1분 안에 댓글 3안이 와요.
- A 숫자 보강
- B 다른 각도
- C 질문

버튼을 누르면 고른 댓글만 따로 와요. 길게 눌러 복사한 뒤 **직접** 붙여 넣으세요. 봇은 댓글을 절대 올리지 않아요.

## 여분 PC 준비 (한 번만)
1. 파이썬 3.12와 크롬을 설치해요. 파이썬은 설치할 때 "Add python.exe to PATH"에 체크해요.
2. 이 폴더(insta-research)를 여분 PC로 복사해요. `git clone https://github.com/vhffkfk-max/content-lab` 으로 받아도 돼요.
3. 지금 PC의 `.env` 파일을 USB로 여분 PC의 같은 폴더에 복사해요. 텔레그램 봇 토큰이 들어 있어요.
   > `.env`는 깃허브나 채팅에 올리지 마세요.
4. 여분 PC에서 PowerShell을 열고 이 폴더에서 실행해요.
   ```
   powershell -ExecutionPolicy Bypass -File comment_bot_install.ps1
   ```
   Anthropic API 키를 물으면 붙여 넣고 Enter를 눌러요. 화면에는 안 보여도 정상이에요.
   이후 PC를 켜고 로그인할 때마다 봇이 저절로 켜지고, 꺼지면 1분 뒤 다시 켜져요.
5. 절전을 꺼 두세요: 설정 → 시스템 → 전원 → 화면/절전 "안 함".

## 주의
- 봇은 **한 대에서만** 켜세요. 두 대에서 켜면 서로 충돌해요.
- 안전 규칙
  - 계정당 하루 15개까지예요.
  - 같은 글에는 계정 하나만 쓸 수 있어요.
  - 예전에 고른 댓글과 비슷하면 다시 만들어요.
- 고른 기록은 그 PC의 `data/comment_bot.db`에만 남아요. 깃허브에는 안 올라가요.
- 계정 목록과 말투는 `config/comment_accounts.json`에서 고쳐요.
- 내 PC에서 시험만 하려면: `python comment_bot.py --test <링크>`
