# 쓰레드 키워드 검색 심사 신청 안내

목표: 메타의 `threads_keyword_search` 권한(고급 액세스)을 받아서, 내 글이 아닌 **다른 사람들의 공개 쓰레드 글**을
경제 키워드로 검색·수집한다. 심사 전에는 같은 코드가 **내 계정 글만** 검색한다 (메타 정책).

> 메타 화면 구성은 자주 바뀌어요. 메뉴 이름이 조금 달라도 같은 뜻의 버튼을 찾으면 돼요. 막히면 캡처를 보여주세요.
> 앱 시크릿·토큰은 채팅에 붙여넣지 마세요.

---

## 0단계. 준비물 (이미 만들어 둔 것)
| 심사에 필요한 것 | 주소 |
|---|---|
| 개인정보처리방침 | https://vhffkfk-max.github.io/content-lab/privacy.html |
| 데이터 삭제 안내 | https://vhffkfk-max.github.io/content-lab/data-deletion.html |
| 로그인 후 돌아올 주소(리디렉션) | https://vhffkfk-max.github.io/content-lab/threads-callback.html |
| 앱 아이콘 (1024×1024) | `site/pages/` 에 없음 → 브랜드 로고 이미지를 준비해 주세요 |

**문의 이메일**: 두 페이지에 공개될 운영팀 문의 메일을 `site/site_config.json` 의 `contact_email` 에 넣어야 해요 (Claude에게 알려주면 넣어드려요).

## 1단계. 쓰레드 계정 확인
- @hotconomy 인스타와 연결된 **쓰레드 계정이 공개 계정**인지 확인해요 (비공개면 권한 연장이 안 됨).

## 2단계. 메타 앱에 쓰레드 사용 사례 추가
1. https://developers.facebook.com → **내 앱** → 인스타 연결 때 만든 앱(`insta-research`) 선택
   - 기존 앱에 추가가 안 되면 **앱 만들기 → 사용 사례 "Threads API에 액세스"** 로 새 앱을 만들어요.
2. 왼쪽 **사용 사례 → Threads API에 액세스 → 맞춤 설정**
3. **권한**에서 `threads_basic`, `threads_keyword_search` 를 **추가**
4. **설정**에 아래 주소 입력 후 저장
   - 리디렉션 콜백 URL: `https://vhffkfk-max.github.io/content-lab/threads-callback.html`
   - 제거(Uninstall) 콜백 URL: `https://vhffkfk-max.github.io/content-lab/data-deletion.html`
   - 삭제(Delete) 콜백 URL: `https://vhffkfk-max.github.io/content-lab/data-deletion.html`
5. **앱 설정 → 기본 설정**
   - 개인정보처리방침 URL / 데이터 삭제 안내 URL: 0단계 주소
   - 앱 아이콘, 카테고리(비즈니스 및 페이지 또는 유틸리티)
6. 쓰레드 전용 **앱 ID·앱 시크릿**(인스타와 다름)을 확인해서 PC의 `.env` 에 적어요
   ```
   THREADS_APP_ID=쓰레드앱ID
   THREADS_APP_SECRET=쓰레드앱시크릿
   ```
7. **역할 → 사람 추가 → Threads 테스터** 로 내 쓰레드 계정을 추가하고,
   쓰레드 앱 → 설정 → 계정 → **웹사이트 권한 → 초대**에서 수락해요.

## 3단계. 내 계정 연결 (심사 전 동작 확인)
```bash
python threads_auth.py --push
```
브라우저가 열리면 로그인 → 허용 → 콜백 페이지의 코드를 복사해서 창에 붙여넣어요.
`✅ 쓰레드 연결 완료` 와 `GitHub 비밀값 등록`이 나오면 끝. 바로 확인:
```bash
python threads_collect.py
```
(심사 전이라 "내 계정 글만 검색돼요"라고 나오는 게 정상이에요.)

## 4단계. 사업자·액세스 인증
- 앱 대시보드에 **비즈니스 인증(Business Verification)** 또는 **액세스 인증** 요청이 뜨면 진행해요.
  - 사업자등록증(파로파트너스 등) 같은 서류가 필요할 수 있어요. 사람이 직접 해야 하는 단계예요.

## 5단계. 시연 영상 찍기 (1~2분, 화면 녹화)
메타 심사관은 **영어 화면 설명**을 선호해요. 영상에 자막이나 말로 아래 흐름이 보이게 찍어요.
1. PC에서 `python threads_auth.py` 실행 → 브라우저에 **쓰레드 로그인·권한 허용 화면**이 뜨는 것 → **허용** 클릭
2. 콜백 페이지에 코드가 뜨고 → 창에 붙여넣어 `연결 완료`
3. `python threads_collect.py` 실행 → 키워드(예: 미국주식) 검색 결과가 저장되는 것
4. 연구소 사이트 https://vhffkfk-max.github.io/content-lab/ → **쓰레드** 채널에서 검색 결과가
   **주제별 글 수·참고 글 링크**로 쓰이는 화면 (팀이 콘텐츠를 기획하는 용도)
5. 개인정보처리방침 페이지를 잠깐 보여주기

## 6단계. 앱 검수 제출
**앱 검수 → 권한 및 기능 → `threads_keyword_search` → 고급 액세스 요청**
아래 영어 문장을 그대로 붙여넣고 5단계 영상을 올려요. 심사는 보통 2~7일, 반려되면 사유를 보고 다시 내요.

### 제출문 (복사해서 붙여넣기)

**How will your app use `threads_keyword_search`?**
```
Content Lab is an internal content-research dashboard used by our four-person team that creates
personal-finance and investing content (account: @hotconomy). Once a day, our server calls the
keyword search endpoint with a fixed list of about 15 finance keywords (for example "미국주식" US stocks,
"비트코인" bitcoin, "금리" interest rates, "ETF") using search_type TOP and RECENT, limit 50.
From the results we store only the post id, text, author username, permalink, timestamp and media type.
We count how many public posts appear per finance topic, show the counts as charts, and list a few
permalinks so our writers can read the original posts on Threads before planning their own original
content. We do not republish posts, contact users, build user profiles, sell data or use it for ads.
Data older than 90 days is deleted automatically. Users can request deletion via our data deletion
page. Without this permission the search only returns our own posts, so we cannot see which finance
topics are being discussed on Threads.
```

**Step-by-step instructions for the reviewer**
```
1. Open https://vhffkfk-max.github.io/content-lab/ and choose the "쓰레드" (Threads) channel in the left menu.
2. The page shows, for each finance topic, the number of public Threads posts found by keyword search in
   the last 24 hours and links to example posts.
3. The screencast shows the full flow: Threads login and permission consent, the redirect to our callback
   page, the daily keyword search call, and the dashboard that uses the results.
4. Privacy policy: https://vhffkfk-max.github.io/content-lab/privacy.html
   Data deletion: https://vhffkfk-max.github.io/content-lab/data-deletion.html
```

**`threads_basic`** (함께 요청되는 경우)
```
Required to authenticate our team's Threads account and to call the keyword search endpoint.
We read only the authenticated user's id and username to confirm which account is connected.
```

---

## 승인 후
- 다음 06:00 자동 실행부터 다른 사람 공개 글이 함께 수집돼요 (코드 변경 없음).
- 토큰은 60일마다 연장해야 해요: 50일쯤 지나면 `python threads_auth.py --refresh --push`
  (Claude에게 "쓰레드 토큰 연장해줘"라고 해도 돼요).
