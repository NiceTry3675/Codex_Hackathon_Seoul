# SynQ Slack 연결

기존 웹과 Slack에서 **같은 6자리 결정 방**을 사용한다. Slack에서 결정을 만들고,
지정한 스레드로 AI 초안을 추천받고, 평가를 제출할 수 있다. 웹에서는 기존 분석·논의·재검토·
최종 결정 기록을 이어간다. 전원 제출 완료는 생성 채널에 자동으로 알린다.
Slack 개인 기록을 웹에서 보려면 본인이 Google 계정 연결을 확인해야 한다.

## 앱 설정

1. Slack 앱의 OAuth & Permissions → Bot Token Scopes에 `chat:write`, `commands`를 추가한다.
   스레드 추천에는 공개 채널용 `channels:history`가 필요하다. 비공개 채널에서도 사용할 때만
   `groups:history`를 추가한다. 권한을 추가했다면 앱을 재설치하고, 토큰이 바뀌면 서버 값도 갱신한다.
2. Bot User OAuth Token과 Basic Information의 Signing Secret을 서버 환경변수에 넣는다.
3. 해당 봇의 `auth.test` 결과에 있는 `team_id`를 `SLACK_TEAM_ID`로 설정한다.
4. 이 변경을 배포하는 웹의 HTTPS origin을 `SYNQ_PUBLIC_URL`로 설정한다. 경로·쿼리는 넣지 않는다.
5. Slash Commands → Create New Command에서 **`/synq` 하나만** 등록한다.
   - Command: `/synq`
   - Request URL: `https://<백엔드 도메인>/api/slack/commands`
   - Short Description: `결정 만들기, 평가 참여와 내 기록`
   - Usage Hint: `new | from 스레드링크 | join 방코드 | rooms | link`
6. Interactivity & Shortcuts → Interactivity를 켜고 Request URL을
   `https://<백엔드 도메인>/api/slack/interactions`로 설정한다. Shortcuts를 추가할 필요는 없다.
7. Socket Mode는 끄고, 사용할 채널에서 `/invite @SynQ`를 실행한다.

Event Subscriptions는 필요 없다. 앱을 새로 만들 때는
[`backend/slack.manifest.json`](backend/slack.manifest.json)의 `YOUR_HOST`를 배포 도메인으로
바꿔 가져올 수 있다. manifest에는 공개 채널 스레드 읽기 권한이 포함되어 있다.
실제 Slack 요청을 받으려면 해당 코드가 배포된 HTTPS 주소가 필요하다.

## 서버 환경변수

[`backend/slack.env.example`](backend/slack.env.example)을 참고한다. 실제 토큰은 커밋하지 않는다.
기존 운영 환경의 네 설정을 그대로 사용할 수 있다.

| 설정 | 용도 |
|---|---|
| `SLACK_BOT_TOKEN` | Slack Bot User OAuth Token |
| `SLACK_SIGNING_SECRET` | Slack 요청 서명 검증 |
| `SLACK_TEAM_ID` | 허용하는 단일 워크스페이스 |
| `SYNQ_PUBLIC_URL` | 웹 HTTPS origin 및 공유 링크 기준 주소 |
| `SLACK_PUBLIC_BASE_URL` | `SYNQ_PUBLIC_URL`의 호환용 대체 이름 |
| `SLACK_APP_ID` | 선택 사항. 설정하면 Slack 앱 ID도 검증 |
| `SLACK_HISTORY_RETENTION_DAYS` | 개인 기록 보관 기간. 기본 90일, 7~365일 |

Google 연결은 기존 `GOOGLE_CLIENT_ID`, `SESSION_SECRET`, `SESSION_COOKIE_SECURE` 설정을
재사용한다. 운영 HTTPS에서는 `SESSION_COOKIE_SECURE=true`를 사용한다.
Google OAuth 클라이언트의 승인된 JavaScript 원본에는 실제 웹 origin이 있어야 한다.

AI 스레드 추천과 의견 처리는 기존 서버의 `OPENAI_API_KEY`, `OPENAI_MODEL`,
`OPENAI_TIMEOUT_SECONDS`를 사용한다. 별도 Slack용 AI 키나 추가 서버는 필요 없다.
키가 없거나 AI 호출이 실패하면 자동 초안 대신 직접 입력하고, 분석은 기존 대체 동작을 따른다.

## 명령어

| 명령 | 결과 |
|---|---|
| `/synq` | 실행자에게만 전체 사용법과 웹 생성 링크 표시 |
| `/synq new` 또는 `/synq create` | 질문·선택지·기준·참여 인원·마감·배경을 입력하는 생성 창 |
| `/synq from 스레드링크` | 지정 스레드에서 AI 초안을 만들고 수정 가능한 생성 창 표시 |
| `/synq join ABC123` | 같은 방의 평가 창 열기. 지원 범위를 넘으면 웹 참여 링크 표시 |
| `/synq status ABC123` | 실행자에게 제출 현황 표시 |
| `/synq results ABC123` | 실행자에게 전원 제출 후 분석 결과 표시 |
| `/synq rooms` | 본인이 만든 방과 제출한 방의 개인 기록 |
| `/synq link` | 실행자에게만 Google 계정 연결 링크 표시 |
| `/synq share ABC123` | 해당 채널에 결정 제목·제출 수·웹 평가 링크 게시 |
| `/synq result ABC123` | 해당 채널에 전원 제출 후 평가 1위·평가가 갈린 기준·확인 질문 게시 |
| `/synq record ABC123` | 해당 채널에 웹에 저장한 최종 선택과 이유 게시 |

`ABC123`은 실제 방 코드로 바꾼다. `result`는 채널 공유이고, `results`는 개인 조회다.
`share/result/record`는 사용자가 선택한 채널에 게시하는 동작이다. 링크와 코드를 받은 사람이
공개 접근 기간 안에 웹 방을 볼 수 있으므로 해당 결정을 공유할 채널에서 실행한다.
개인 점수·원문 의견·Slack 사용자 ID는 채널에 게시하지 않는다.

Slack 평가는 익명 방의 선택지 2~5개·판단 기준 1~5개 범위에서 제공한다.
선택지는 항목당 72자, 판단 기준은 200자, 배경은 3,000자까지 지원하며 참여 인원은 최대 100명이다.
이 범위를 넘는 방이나 실명 방은 같은 방의 웹 화면에서 참여한다. 창을 열었다가 닫아도 정원을 차지하지 않는다.
실제로 저장된 평가만 제출 인원에 포함된다. 점수·기준 중요도·첫 선택·이유는 웹과 동일한
제출 및 분석 경로를 사용하므로, 이유도 기존 서버의 의견 처리에 반영된다.

## 스레드 추천

1. 원본 메시지 또는 해당 스레드 답글에서 메시지 링크를 복사한다.
2. **그 스레드가 있는 채널**에서 `/synq from https://워크스페이스.slack.com/archives/채널ID/p메시지ID`를 실행한다.
3. 준비 창이 열린 뒤 AI의 질문·선택지·기준·배경 요약 초안을 확인한다.
4. 내용을 수정하고 `만들기`를 누르면 같은 채널에 평가 참여 안내가 게시된다.
5. 팀원은 Slack 또는 웹에서 평가하고, 전원 제출 후 같은 채널에서 완료 알림을 받는다.

`from`은 지정한 스레드 텍스트를 서버에 설정된 OpenAI 모델에 보내는 동작이다.
링크의 호스트에 접속하지 않고 검증한 채널 ID와 메시지 타임스탬프로 Slack 공식 API만 호출한다.
다른 채널의 링크와 DM 링크는 받지 않는다.

스레드는 최대 100개 메시지, 20,000자, 10페이지까지 읽고 제한에 걸리면 일부만 읽었음을 표시한다.
읽는 도중의 메시지 추가·편집까지 일관된 스냅샷을 보장하지는 않는다.
파일·첨부 링크 내용과 봇 메시지는 수집하지 않는다. 작성자 ID는 AI 입력에 넣지 않고,
본문의 Slack 사용자 멘션은 `[참여자]`로 바꾼다. 본문에 직접 적힌 이름은 남을 수 있다.
스레드 원문은 방·로그에 저장하지 않으며 사용자가 확인한 초안만 방에 저장한다.
생성 전 초안은 실행자에게만 보인다. 창을 닫으면 방 생성이나 채널 게시가 없다.
권한 부족·조회 제한·AI 실패 시 이유를 알리고 직접 입력할 수 있게 한다.

## 개인 기록과 계정 연결

1. Slack에서 `/synq link`를 실행하고 본인에게 표시된 링크를 연다. 링크는 10분 동안 유효하다.
2. 연결할 Google 계정으로 로그인하고 화면에서 연결을 명시적으로 확인한다.
3. 이후 웹 상단의 **내 Slack 기록** 또는 `/slack/link`에서 로그인 후 본인의 기록을 확인한다.

이메일이 같다는 이유로 자동 연결하지 않는다. 워크스페이스 안에서 Slack 계정과 Google 계정은
1:1로 연결하며 연결 해제·계정 변경 화면은 아직 제공하지 않는다.
Google 연결 없이도 Slack 평가와 `/synq rooms`를 사용할 수 있다.
개인 목록은 보관 기간 안의 최근 200개 방까지 제공한다. 현재 워크스페이스당 연결은 최대
1,000개이며, 계정 연결 정보의 저장 기간은 방 기록과 별도로 10년이다.

익명은 **팀원에게 작성자를 공개하지 않는 것**을 뜻한다. 서버는 중복 제출 방지와 개인 기록을
위해 Slack 사용자 ID 및 참여 이력을 비공개로 저장한다. 연결된 Google 계정으로 웹에 로그인하여
제출하면 Slack과 같은 사용자로 중복 제출을 확인한다. 비연결 상태의 익명 웹 참여에는 기존
브라우저 쿠키를 사용하므로 다른 브라우저·기기로 바꾼 제출까지 동일인으로 판별하지는 못한다.
과거의 계정 정보 없는 익명 웹 제출은 연결 후에도 자동으로 본인 기록에 합쳐지지 않는다.

개인 기록에는 Slack 또는 연결된 Google 계정으로 만든 방과 성공적으로 제출한 방을 기록한다.
평가 창만 연 방은 추가하지 않는다. 방의 공개 접근·평가 마감은 기존 `expires_at` 정책
(기본 24시간, 최대 168시간)을 유지한다. 개인 기록 보관을 위해 저장소에는 더 오래 남을 수 있지만,
마감 뒤에는 기존 공개 방 API에서 접근할 수 없다. 보관 기간 안의 기록은 본인 확인을 거친
개인 기록 경로에서만 조회한다. 웹 개인 기록은 연결된 Google 계정의 로그인이 필요하다.
개인 기록 API는 다른 참여자의 Slack ID나 개인별 평가를 반환하지 않는다.

## 자동 완료 알림과 운영 한계

- Slack에서 생성한 방은 Slack·웹 어느 경로로 마지막 평가를 제출해도 생성 채널에 완료를 알린다.
  `/synq share`는 기존 웹 방에 자동 알림을 등록하지 않는다.
- 중간 제출·개인 점수·의견은 게시하지 않는다. 알림에는 결정 질문·완료 인원·결과 링크가 들어간다.
- Slack 전송 실패가 저장된 평가를 취소하지 않는다. 알림을 놓치면 `/synq result 방코드`로 공유한다.
- 원문 요청의 HMAC 서명·5분 타임스탬프·허용 워크스페이스를 검증한다.
- Slack 요청에 먼저 응답하고 느린 작업을 백그라운드에서 처리한다. 영속 작업 큐는 제공하지 않으며
  프로세스 중단 시 미완료 작업이나 알림을 놓칠 수 있다. 알림의 정확히 한 번 전달을 보장하지 않는다.
- Google 연결과 개인 기록은 기존 DynamoDB 테이블을 사용한다. `CONSENSUS_TABLE_NAME`을 비운
  개발 환경의 인메모리 데이터는 프로세스 재시작 시 사라진다.
- 자동 테스트는 Slack·Google·AI 외부 호출을 대체한다. 실제 모달 열기, 채널 게시, Google 연결,
  브라우저 화면 및 AWS 배포 동작은 배포 환경에서 별도로 확인해야 한다.

## 로컬 실행과 통합 범위

로컬 `.env`는 자동 로드되지 않는다. uvicorn 실행 시 명시적으로 로드한다.
프런트엔드는 `VITE_USE_MOCK_API=false`로 빌드해야 실제 방과 개인 기록을 사용할 수 있다.
Dockerfile은 이미 이 설정을 적용한다.

```bash
.venv/bin/uvicorn backend.main:app --env-file .env --host 0.0.0.0 --port 8000
.venv/bin/python -m pytest backend/tests -q
```

이번 통합은 `origin/codex/slack-bot-account-linking`의 `791f704`에 있던 Slack 평가 모달·
개인 기록·명시적 Google 연결을 기존 웹 방과 스레드 AI 추천 흐름에 맞춰 적용한다.
새 방은 웹과 Slack이 공유하는 6자리 코드다. 팀원 브랜치의 독립적인 `SLACK#ROOM#...`
10자리 방 데이터는 자동으로 변환하거나 병합하지 않는다. 이미 그 버전을 사용한 데이터가 있다면
별도의 이관이 필요하다.

공식 문서: [Slash Commands](https://docs.slack.dev/interactivity/implementing-slash-commands/),
[요청 서명 검증](https://docs.slack.dev/authentication/verifying-requests-from-slack/),
[모달](https://docs.slack.dev/surfaces/modals/),
[스레드 조회](https://docs.slack.dev/reference/methods/conversations.replies/).
