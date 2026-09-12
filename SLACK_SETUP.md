# SynQ Slack 파일럿 연결

단일 워크스페이스용 파일럿이다. 슬랙 입력 창에서 결정을 만들거나, 지정한 스레드를 읽어
AI가 제안한 질문·선택지·판단 기준을 확인한 뒤 만들 수 있다. 생성 시 같은 채널에 평가 링크를
게시하고 마지막 평가가 제출되면 완료를 알린다. 독립 평가·분석·논의·최종 기록은 기존 웹에서 한다.
최종 결정 공유는 사용자가 명령어로 실행한다.

## 앱 설정

1. Slack 앱의 OAuth & Permissions → Bot Token Scopes에 `chat:write`, `commands`를 추가하고 설치한다.
   스레드 추천에는 공개 채널용 `channels:history`를 추가한다. 비공개 채널에서도 사용할 때만
   `groups:history`를 추가한다. 권한 추가 후 앱을 재설치하고 토큰이 바뀌었다면 서버 값도 갱신한다.
2. Bot User OAuth Token과 Basic Information의 Signing Secret을 서버 환경변수에 넣는다.
3. 해당 봇의 `auth.test` 결과에 있는 `team_id`를 `SLACK_TEAM_ID`로 설정한다.
4. **이 변경이 배포된** 웹의 HTTPS origin을 `SYNQ_PUBLIC_URL`로 설정한다. 경로·쿼리는 넣지 않는다.
5. Slash Commands → Create New Command:
   - Command: `/synq`
   - Request URL: `https://<백엔드 도메인>/api/slack/commands`
   - Short Description: `팀의 결정 전 점검과 결과 공유`
   - Usage Hint: `[new | from 스레드링크 | share 방코드 | result 방코드 | record 방코드]`
6. Interactivity & Shortcuts → Interactivity를 켜고 Request URL에
   `https://<백엔드 도메인>/api/slack/interactions`를 설정한다. Shortcuts를 추가할 필요는 없다.
7. 슬랙 테스트 채널에서 `/invite @SynQ`를 실행한다.

Event Subscriptions와 Socket Mode 설정은 필요 없다.
Request URL은 서버 배포 후 입력한다. 기존 운영 주소에 코드가 있다고 가정하지 않는다.

## 실행과 검증

로컬 `.env`는 자동 로드되지 않는다. uvicorn으로 실행할 때 명시적으로 로드한다.
로컬 테스트는 `CONSENSUS_TABLE_NAME`을 비워 인메모리 저장소를 사용한다.
실제 슬랙 호출에는 접근 가능한 HTTPS 서버가 필요하다.
프런트엔드는 `VITE_USE_MOCK_API=false`로 빌드해야 실제 방 링크가 작동한다.
Dockerfile은 이미 이 설정을 적용한다.

```bash
.venv/bin/uvicorn backend.main:app --env-file .env --host 0.0.0.0 --port 8000
.venv/bin/python -m pytest backend/tests/test_slack.py -q
```

| 명령 | 결과 |
|---|---|
| `/synq` | 실행자에게만 사용법과 웹 생성 링크 표시 |
| `/synq new` | 질문·선택지·기준·참여 인원·보관 기간·배경을 입력하는 슬랙 창 열기 |
| `/synq from 스레드링크` | 지정 스레드의 텍스트로 AI 초안을 만들고 수정 가능한 생성 창 표시 |
| `/synq share ABC123` | 해당 채널에 결정 제목·제출 수·평가 링크 게시 |
| `/synq result ABC123` | 전원 제출 후 현재 평가 1위·평가가 갈린 기준·확인 질문 게시 |
| `/synq record ABC123` | 웹에 이미 저장된 최종 선택과 이유 게시 |

방 코드는 실제 생성한 코드로 바꾼다. `share/result/record`는 채널에 게시하는 명시적 동작이다.
방 코드로 웹에 접근하는 기존 정책을 따른다. 링크를 받은 사람이 방에 접근할 수 있으므로
해당 결정을 공유할 채널에서 실행한다. 슬랙 계정과 개인 평가를 연결하거나 저장하지 않는다.
원문 개인 의견과 개인 점수는 게시하지 않는다. AI가 생성한 확인 질문은 기존 분석 결과를 사용한다.
방과 결정 기록은 기존 만료 정책(기본 24시간, 최대 168시간)을 따른다.

## 스레드 추천 사용

1. 원본 메시지 또는 해당 스레드 답글에서 메시지 링크를 복사한다.
2. **그 스레드가 있는 채널**에서 `/synq from https://워크스페이스.slack.com/archives/채널ID/p메시지ID`를 실행한다.
3. 준비 창이 열린 뒤 AI의 질문·선택지·기준·배경 요약 초안이 표시된다.
4. 내용을 수정·확인하고 `만들기`를 누르면 방을 생성하고 그 채널에 평가 링크를 게시한다.
5. 팀원들이 웹에서 평가하면 마지막 제출이 저장된 후 같은 채널에 완료 알림과 결과 링크가 게시된다.

`from`은 지정한 스레드 텍스트를 현재 설정된 OpenAI 모델에 보내 초안을 요청하는 동작이다.
슬랙 창과 도움말에 이 동작을 안내한다. 링크의 호스트에 접속하지 않고, 검증한 채널 ID와
메시지 타임스탬프로 Slack 공식 API만 호출한다. 다른 채널의 링크와 DM 링크는 받지 않는다.

스레드는 페이지를 따라 최대 100개 메시지, 20,000자, 10페이지까지 읽는다. 읽는 동안 새로
추가되거나 편집된 메시지까지 일관된 스냅샷을 보장하지는 않는다. 제한에 걸린 경우 일부만
읽었음을 표시한다. 파일·첨부 링크 내용과 봇 메시지는 수집하지 않는다. 작성자 ID는 AI 입력에
넣지 않고, 본문의 Slack 사용자 멘션은 `[참여자]`로 바꾼다. 본문에 직접 적힌 이름 등은 남을 수 있다.
스레드 원문을 방·로그에 저장하지 않는다. 사용자가 확인한 질문·선택지·기준·배경 요약만 방에 저장된다.
생성 전 AI 초안은 실행자에게만 보이며, 창을 닫으면 방을 생성하거나 채널에 게시하지 않는다.

권한 부족·조회 제한·AI 실패 시 이유를 알리고 빈 입력 폼을 제공한다. 실패한 추천을 성공한
추천처럼 표시하지 않는다. `OPENAI_API_KEY`가 없으면 자동 추천을 제공하지 못하며 직접 입력은 가능하다.
기존 `OPENAI_MODEL`과 `OPENAI_TIMEOUT_SECONDS` 설정을 재사용한다.

## 자동 완료 알림

- 슬랙 생성 창에서 만든 방에만 적용한다. `/synq share`는 기존 웹 방에 자동 알림을 등록하지 않는다.
- 방에 workspace ID와 생성 채널 ID만 저장한다. 생성자·평가자의 Slack 사용자 ID는 저장하지 않는다.
- 중간 제출은 알리지 않으며, 최종 제출을 원자적으로 저장한 요청에서만 알림을 예약한다.
- 알림에는 완료 인원·결정 질문·결과 링크가 들어간다. 개인 점수·의견이나 중간 순위는 게시하지 않는다.
- Slack 전송 실패가 평가 제출을 취소하지 않는다. 알림을 놓친 경우 `/synq result 방코드`로 결과를 공유할 수 있다.

## 구현 범위와 운영 한계

- 원문 요청에 대한 HMAC 서명과 5분 타임스탬프, 허용 workspace ID를 검증한다.
- 접수 응답을 먼저 보내고 방 조회·분석·Slack 전송을 FastAPI BackgroundTasks로 실행한다.
- Slack API 오류·네트워크 실패는 실행자에게만 알린다. 불확실한 전송을 자동 재시도하지 않는다.
- 같은 서명 요청은 프로세스 안에서 10분간 중복 실행을 막는다.
- 생성 폼 제출도 workspace ID와 view ID로 10분간 중복 생성을 막는다. 입력 검증에 실패한 폼은 수정 후 제출 가능하다.
- 백그라운드 작업과 중복 방지 상태는 영속화하지 않는다. 프로세스 재시작 시 작업을 잃을 수 있고,
  여러 인스턴스에서는 중복 게시가 발생할 수 있다. 이 버전은 단일 프로세스 파일럿 범위이며,
  다중 인스턴스 배포 전에는 영속 작업 큐와 공용 중복 방지 저장소를 추가해야 한다.
- 로컬 테스트는 Slack 전송을 대체한다. 실제 명령 수신·채널 게시·브라우저 동작은 배포 후 별도로 검증한다.

공식 문서: [Slash Commands](https://docs.slack.dev/interactivity/implementing-slash-commands/),
[요청 서명 검증](https://docs.slack.dev/authentication/verifying-requests-from-slack/),
[auth.test](https://docs.slack.dev/reference/methods/auth.test/),
[모달](https://docs.slack.dev/surfaces/modals/),
[스레드 조회](https://docs.slack.dev/reference/methods/conversations.replies/).
