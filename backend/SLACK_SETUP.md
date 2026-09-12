# SynQ Slack 앱 설치 및 검증

하나의 Slack 워크스페이스에서 방 생성, 모달 의견 제출, 개인 참여 기록, Google 계정 연결을 사용하는 백엔드 확장입니다. 설치·토큰 발급은 워크스페이스 관리자가 직접 진행합니다. 이 문서의 설정 예시는 실제 Slack 설치 또는 실서버 검증 완료를 의미하지 않습니다.

## 1. 테스트 워크스페이스 만들기

1. [Slack 워크스페이스 만들기](https://slack.com/get-started#/createnew)를 엽니다.
2. Google 계정 또는 이메일로 시작하고, 이메일 확인을 요청하면 인증 코드를 입력합니다.
3. 워크스페이스 이름을 지정합니다. 테스트라면 `SynQ 테스트`처럼 정해도 됩니다.
4. 테스트에 참여할 팀원 한 명을 초대하고 `#synq-test` 채널을 만듭니다.

이미 설치 권한이 있는 팀 워크스페이스가 있으면 그것을 사용해도 됩니다. [Slack 공식 워크스페이스 생성 안내](https://slack.com/help/articles/206845317-Create-a-Slack-workspace)를 참고하세요.

## 2. 백엔드 공개 주소와 저장소 설정

기존 FastAPI 서버에 다음 주소가 추가됩니다.

- Slack 명령 수신: `POST /api/slack/commands`
- 버튼·모달 수신: `POST /api/slack/interactions`
- Google 계정 연결 및 개인 기록 페이지: `GET /slack/link`
- 본인 Slack 연결: `POST /api/slack/link`
- 본인 방 목록: `GET /api/slack/me/rooms?limit=20&cursor=...`
- 본인 방 상세 및 저장된 집계 분석: `GET /api/slack/me/rooms/{code}`

Slack이 접근할 수 있는 HTTPS 백엔드 주소를 준비하고 `SLACK_PUBLIC_BASE_URL`에 설정합니다. 도메인과 포트까지 실제 브라우저에서 열 주소와 일치해야 합니다. 경로를 붙이지 않습니다. 로컬 HTTP 주소는 로컬 페이지·API 테스트용이며 Slack 서버가 개발자의 `localhost`로 접속할 수는 없습니다. 외부 Slack 검증에는 HTTPS 배포 주소나 개발용 HTTPS 터널이 필요합니다.

[`slack.env.example`](slack.env.example)의 값들을 기존 로컬 `.env` 또는 배포 환경변수에 추가합니다. `.env`를 사용할 때는 프로젝트 루트에서 다음처럼 명시적으로 로드합니다.

```bash
.venv/bin/python -m uvicorn backend.main:app --env-file .env --reload --port 8000
```

`CONSENSUS_TABLE_NAME`이 설정되면 기존 DynamoDB 테이블을 사용합니다. 이 환경변수 이름은 기존 백엔드 설정과의 호환성을 위해 유지하며 앱 이름은 SynQ입니다. 파티션 키는 문자열 `code`, TTL 속성은 숫자 `expires_at`이며 Slack 데이터는 `SLACK#` 접두사 키를 사용합니다. 기존 공개 방 저장과 구분되므로 테이블·인프라를 새로 만들 필요는 없습니다. 운영 실행 역할에는 이 테이블에 대한 읽기·쓰기 및 구현에서 사용하는 조건부 갱신 권한이 필요합니다.

테이블 이름이 비어 있으면 프로세스 메모리에만 저장됩니다. 로컬 개발용이며 서버를 재시작하면 Slack 계정 연결, 참여 기록, 방, 제출이 사라집니다. `SLACK_HISTORY_RETENTION_DAYS`는 기본 90일, 허용 범위 7~365일입니다. 제출 마감과 기록 보관 기한은 별도로 관리되므로 수집이 끝난 방도 보관 기한까지 기록에서 볼 수 있습니다.

개인 목록에는 최근 200개 방을 인덱싱하고, Google 연결은 워크스페이스당 최대 1,000개 계정까지 지원합니다. 계정 연결 정보는 방 기록의 보관 기한과 별도로 유지되며 현재 저장 TTL은 10년입니다. 사용자 직접 연결 해제·계정 변경 기능은 아직 포함하지 않습니다.

## 3. Slack 앱 만들고 설치하기

1. [Slack 앱 관리](https://api.slack.com/apps)에서 **Create New App → From a manifest**를 선택하고 테스트 워크스페이스를 고릅니다.
2. [`slack.manifest.json`](slack.manifest.json)을 JSON 모드에 붙여 넣습니다. 두 군데의 `https://YOUR_HOST`를 실제 `SLACK_PUBLIC_BASE_URL` 값으로 바꾸고 생성합니다.
3. **Basic Information**에서 **App ID**와 **Signing Secret**을 확인합니다. 각각 `SLACK_APP_ID`, `SLACK_SIGNING_SECRET`에 설정합니다.
4. **OAuth & Permissions → Install to Workspace**로 설치합니다. 승인된 **Bot User OAuth Token**(`xoxb-`로 시작)을 `SLACK_BOT_TOKEN`에 설정합니다.
5. 브라우저로 해당 워크스페이스를 열어 URL의 `https://app.slack.com/client/T.../C...` 중 `T...` 값을 `SLACK_TEAM_ID`에 설정합니다. 워크스페이스 표시 이름이나 도메인 이름을 넣지 않습니다.
6. 실행 환경에 설정을 반영한 뒤 서버를 재시작합니다.
7. 테스트 채널에서 `/invite @SynQ`로 봇을 초대합니다.
8. **Slash Commands**의 `/synq` URL과 **Interactivity & Shortcuts**의 URL이 각각 `/api/slack/commands`, `/api/slack/interactions`로 끝나는지 확인합니다.

요청 범위는 `commands`, `chat:write` 두 개입니다. 메시지 기록, 멤버 프로필·이메일 조회 권한은 요청하지 않습니다. 봇이 참여하지 않은 채널에 글을 쓰는 `chat:write.public`도 없으므로 사용할 채널에 봇을 초대해야 합니다. 이 버전은 설정된 워크스페이스 하나만 받으며 다른 회사가 직접 설치하는 공개 배포 OAuth 흐름은 포함하지 않습니다. [Slack manifest 명세](https://docs.slack.dev/reference/app-manifest/)와 [Slash Commands 안내](https://docs.slack.dev/interactivity/implementing-slash-commands/)에서 설정 필드를 확인할 수 있습니다.

토큰과 Signing Secret은 채팅·스크린샷·Git에 올리지 마세요. 저장소에 있는 예제 파일에는 실제 값을 쓰지 않고 기존 비밀값 관리 방식으로 설정합니다.

## 4. Google 계정과 연결하기

기존 Google 로그인의 `GOOGLE_CLIENT_ID`와 `SESSION_SECRET`을 사용합니다. Google OAuth 웹 클라이언트의 승인된 JavaScript 원본에 `SLACK_PUBLIC_BASE_URL`과 동일한 원본을 등록합니다. HTTPS 환경에서는 `SESSION_COOKIE_SECURE=true`가 필요합니다. 자세한 Google 설정은 기존 [`DEPLOYMENT_PLAN.md`](../DEPLOYMENT_PLAN.md) 및 [Google 공식 설정 안내](https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid)를 참고하세요.

1. Slack에서 `/synq link`를 실행합니다.
2. 본인에게만 표시된 링크를 엽니다. 연결 토큰은 URL fragment에 있고, 페이지가 읽은 즉시 주소에서 제거합니다.
3. 공식 Google 로그인 버튼으로 로그인합니다. 이미 로그인했으면 현재 계정 이름과 이메일이 표시됩니다.
4. 표시된 계정이 맞는지 확인하고 **이 계정에 Slack 연결**을 누릅니다. 로그인만으로 자동 연결하지 않습니다.
5. 연결 이후에는 `/slack/link`를 다시 열어 본인 참여 방 목록과 저장된 팀 분석을 확인합니다.

연결 링크를 새로고침하거나 닫으면 메모리의 토큰이 사라집니다. Slack에서 `/synq link`를 다시 실행하면 됩니다. Slack에서의 방 생성·참여·개인 기록 조회는 Google 연결 없이도 사용할 수 있고, Google 연결은 같은 기록을 웹에서 보는 데 사용합니다. Slack 이메일과 Google 이메일을 비교하여 자동으로 계정을 합치지 않습니다.

## 5. 사용 흐름과 API 계약

- `/synq create`: 현재 채널에 연결된 새 방을 모달에서 만듭니다.
- `/synq join CODE`: 방을 만든 채널에서 의견 입력 모달을 엽니다.
- `/synq status CODE`: 본인이 참여한 방의 제출 현황을 확인합니다.
- `/synq results CODE`: 전원 제출 후 팀 분석을 생성하거나 저장된 분석을 확인합니다.
- `/synq rooms`: 본인이 참여한 방을 본인에게만 표시하고 결과 상세를 엽니다.
- `/synq link`: Google 계정 연결 링크를 본인에게만 표시합니다.

Slack 방 코드는 10자리이며 기존 공개 웹 방의 6자리 코드와 분리됩니다. 생성·참여는 방의 원래 채널에서 진행하고, 개인 히스토리와 결과는 참여 권한이 있는 사용자에게만 ephemeral 응답 또는 모달로 전달합니다. 참여자는 방별 1회만 제출하며, 정원 초과·중복 제출과 전원 제출 전 분석은 거절됩니다. 생성자는 방을 만들었다는 이유로 의견이 자동 제출되지는 않습니다.

Slack 입력 한도는 참여자 20명, 선택지 2~5개, 기준 1~5개, 선택지·기준 이름 각각 80자입니다. 점수는 1~5, 중요도는 1~100 범위로 입력합니다. 모달을 연 뒤 실제 제출 전에 마감되거나 정원이 찬 경우에도 서버가 다시 확인합니다.

웹 기록 API는 Google 세션의 연결된 Slack 사용자로 접근 권한을 확인합니다. 클라이언트가 다른 `user_id`를 지정하는 기능은 없습니다. 목록은 `{rooms: [...], next_cursor: ...}`, 상세는 `{room: {...}, analysis: {...} | null}`이며 개별 답변·이메일·Slack 사용자 ID를 방 응답에 포함하지 않습니다. 전원 제출된 방의 상세를 처음 열면 통계 집계를 계산·저장하고, 이후에는 저장된 분석을 재사용합니다. Slack 명령에서도 같은 집계를 사용하며 이 과정에서 외부 LLM을 호출하지 않습니다. 기존 웹 방의 참여 기록과 Slack 방 기록을 합치는 기능은 포함하지 않습니다.

익명성의 범위는 **팀원에게 개별 답변 작성자를 비공개**입니다. 서비스는 중복 제출 방지 및 개인 기록 제공을 위해 Slack 사용자와 방 참여 관계를 저장하고, 연결 시 Google 계정과도 연결합니다. 소수 인원의 집계나 자유 서술 내용으로 작성자를 추정할 가능성까지 없애는 기능은 아닙니다.

## 6. 실제 워크스페이스 수동 검증

서로 다른 두 Slack 계정 A·B와, 방을 만들지 않은 별도 채널을 준비합니다.

1. A가 `#synq-test`에서 `/synq create`로 정원 2명, 선택지 2개, 기준 2개 방을 만듭니다. 채널 안내에 방 코드가 나오고 개인 입력 내용은 나오지 않아야 합니다.
2. A가 참여·제출 후 같은 방에 다시 제출하면 거절되는지 확인합니다. B의 제출 전 분석도 거절되어야 합니다.
3. 다른 채널에서 같은 코드로 참여하면 거절되는지 확인합니다. 원래 채널에서 B가 모달에 점수·중요도·1순위·이유를 입력해 제출합니다.
4. A와 B 모두 현황에서 `2/2`, 결과에서 팀 집계를 확인합니다. 개별 작성자와 제출 원문 목록은 보이지 않아야 합니다. 같은 결과를 다시 요청해 저장된 분석을 읽는지 확인합니다.
5. A가 새 방을 하나 더 만든 뒤 `/synq rooms`에서 여러 주제가 보이는지 확인합니다. B의 기록에는 B가 참여하지 않은 두 번째 방이 없어야 합니다.
6. A가 `/synq link`로 Google 계정을 명시적으로 연결합니다. 웹에서 참여 목록·상세를 확인하고, 주소에서 `#token=...`가 사라지는지 확인합니다. 새 브라우저에서는 Google 로그인이 필요해야 합니다.
7. 연결에 사용한 같은 토큰을 같은 Google 계정으로 재요청해도 중복 연결이 생기지 않는지 확인합니다. 다른 Google 계정에서 해당 토큰을 사용하거나 이미 연결된 Slack 계정을 재연결하려고 하면 거절되어야 합니다. 로그아웃 상태의 개인 API 접근도 거절되어야 합니다.
8. 본인이 참여하지 않은 방 상세, 잘못된 방 코드, 제출 마감 후 입력을 확인합니다. 저장 기간이 지난 기록이 개인 목록과 상세에서 표시되지 않아야 합니다.
9. DynamoDB를 사용한 별도 테스트 환경에서 서버를 재시작하고 계정 연결·기존 방·제출·분석 기록이 유지되는지 확인합니다. 메모리 모드에서는 이 보존 검증을 통과할 수 없습니다.

## 7. 오류 복구

Slack 요청은 빠르게 접수 응답을 반환하고 일부 작업은 서버의 백그라운드에서 계속합니다. 영속 작업 큐는 없으므로 접수 직후 서버가 재시작되면 후속 처리가 끝나지 않을 수 있습니다. 제출 현황을 먼저 확인한 뒤 사용자 명령을 다시 실행하세요. 사용자 투표를 자동 재전송하지 않습니다. Slack 요청 재시도와 중복 클릭에 대한 방어는 별도로 적용됩니다. [Slack 상호작용 처리 안내](https://docs.slack.dev/interactivity/handling-user-interaction/)를 참고하세요.

방·제출 저장은 요청별로 중복을 방지합니다. 완료된 요청의 모달 표시만 실패하면 저장된 완료 화면을 재전송하며 채널 안내를 다시 게시하지 않습니다. 단, Slack에 메시지가 도착한 직후 서버 종료나 저장소 장애가 발생하면 전송 성공 여부를 확정할 수 없으므로 안내 메시지의 엄격한 1회 전송까지 보장하지는 않습니다. 생성된 방은 `/synq rooms`에서 복구할 수 있습니다.

`not_in_channel`이면 봇 초대를, `invalid_auth`면 토큰을, 서명 오류면 Signing Secret 및 서버 시간을 확인합니다. 개인 기록 페이지에서 연결 만료 메시지가 나오면 Slack에서 새 링크를 발급합니다. 비밀값·연결 토큰·개별 의견을 오류 로그에 복사하지 않습니다.
