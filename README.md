# Consensus

> Agree less. Decide better.

익명 또는 실명 입력을 바탕으로 팀 결정의 안정성, 숨은 갈등, 뒤집힘 조건을 보여주는 해커톤 MVP입니다.
Google 로그인은 계정 세션에만 사용하며, 제출에는 Google 계정을 자동으로 연결하지 않습니다.

현재 저장소는 팀원이 각 모듈을 바로 이어서 개발할 수 있는 **작동 가능한 초안 골격**을 목표로 합니다. 제품 배경은 [`CONTEXT.md`](CONTEXT.md), 구현 계약은 [`SPEC.md`](SPEC.md), 역할과 일정은 [`PLAN.md`](PLAN.md)를 참고하세요.

## 빠른 시작

### 백엔드

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn backend.main:app --reload --port 8000
```

- API 문서: <http://localhost:8000/docs>
- 상태 확인: <http://localhost:8000/api/health>
- `OPENAI_API_KEY`가 없어도 통계 분석은 동작합니다.

### Google 로그인 설정

Google Cloud Console에서 OAuth 2.0 Client ID의 유형을 **웹 애플리케이션**으로 만들고,
승인된 JavaScript 원본에 로컬 `http://localhost:5173`과 실제 배포 HTTPS 원본을 등록합니다.
그다음 서버 환경변수만 설정합니다.

```bash
export GOOGLE_CLIENT_ID="...apps.googleusercontent.com"
export SESSION_SECRET="$(openssl rand -hex 32)"
# HTTPS 배포 환경에서만 true
export SESSION_COOKIE_SECURE=true
```

- `GOOGLE_CLIENT_SECRET`은 사용하지 않습니다. 프런트가 받은 Google ID 토큰을 FastAPI가
  공식 `google-auth` 라이브러리로 검증하는 인증 전용 흐름입니다.
- Client ID는 공개 식별자이므로 `/api/auth/config`가 프런트에 전달합니다.
- 세션은 7일 만료의 `HttpOnly`, `SameSite=Lax` 서명 쿠키입니다.
- 배포 담당자가 추가할 사용자 DB에서는 이메일 대신 `/api/auth/me`의 `google_sub`를
  변경되지 않는 외부 사용자 키로 저장합니다.

### 프론트엔드

```bash
cd frontend
npm install
npm run dev
```

개발 화면은 <http://localhost:5173>에서 열립니다. 환경변수는 `frontend/.env.example`을 참고하세요.

### 테스트

```bash
.venv/bin/python -m pytest
cd frontend && npm run build
```

전체 릴리스 게이트(테스트 → build → Docker health → LIVE API → 데모 계약)는:

```bash
./scripts/release_gate.sh
```

Docker가 없는 개발 환경에서는 API·정적 SPA·데모 계약까지 같은 프로세스에서 검사할 수 있습니다.
이 모드는 컨테이너 검증을 대체하지 않으므로 배포 전에는 반드시 위의 전체 게이트도 실행합니다.

```bash
./scripts/release_gate.sh --skip-docker
```

`OPENAI_API_KEY`가 export되어 있으면 릴리스 게이트가 실제 GPT 구조화,
Devil's Advocate 질문, Defender 답변 판정을 각각 한 번 검증합니다. 키가 없으면 이 단계만 건너뛰고
결정적 폴백을 포함한 핵심 경로를 검증합니다. 실 API만 별도로 확인하려면:

```bash
.venv/bin/python scripts/smoke_openai.py
```

이 명령은 export된 환경변수를 우선 사용하고, 없으면 Git과 Docker context에서 제외된
프로젝트 루트의 `.env`에서 `OPENAI_API_KEY`, `OPENAI_MODEL`,
`OPENAI_TIMEOUT_SECONDS`만 읽습니다.

### 데모 데이터 넣기

백엔드를 실행한 뒤:

```bash
.venv/bin/python scripts/load_demo.py
```

새 방을 만들고 [`demo_data.json`](demo_data.json)의 4개 익명 의견을 제출한 다음 분석 결과를 출력합니다.

### Docker

```bash
docker build -t consensus .
docker run --rm -p 8080:8080 --env-file .env consensus
```

단일 컨테이너에서 FastAPI가 빌드된 React 앱을 함께 제공합니다.

## 저장소 구조

```text
backend/
  auth.py              Google ID 토큰 검증과 서명 세션
  main.py              FastAPI 라우터
  storage.py           DynamoDB room 저장소와 인메모리 fallback
  models.py            요청 및 저장 모델
  stats.py             numpy 통계 엔진
  llm.py               선택적 GPT 구조화/반론 경계
  tests/                통계·API 테스트
frontend/
  src/pages/            Submit / Waiting / Results
  src/api.ts            mock/real API 전환 지점
scripts/load_demo.py    데모 데이터 적재
demo_data.json          발표용 익명 입력 예시
Dockerfile              React 빌드 + FastAPI 런타임
```

## API 골격

| Method | Path | 설명 |
|---|---|---|
| `GET` | `/api/auth/config` | Google 로그인 공개 설정 |
| `POST` | `/api/auth/google` | Google ID 토큰 검증 후 세션 생성 |
| `GET` | `/api/auth/me` | 현재 로그인 사용자 |
| `POST` | `/api/auth/logout` | 세션 종료 |
| `POST` | `/api/rooms` | 방 생성 |
| `GET` | `/api/rooms/{code}` | 방 정보와 제출 현황 |
| `POST` | `/api/rooms/{code}/submit` | 익명 또는 실명 의견 제출 |
| `GET` | `/api/rooms/{code}/analysis` | 안정성·갈등·flip point 분석 |
| `GET` | `/api/rooms/{code}/debate` | 동결된 증거와 append-only 공방 transcript 조회 |
| `POST` | `/api/rooms/{code}/debate/defend` | 질문별 Defender 답변 제출 후 최종 판정 |

`/analysis`를 처음 조회하면 Challenger 질문과 증거 스냅샷이 생성됩니다. 이후
`/debate/defend`에 모든 `challenge_id`의 답변을 한 번에 제출하면 두 번째이자 마지막
Challenger 턴이 각 항목을 `resolved`, `open`, `reframed`로 판정합니다. `open`과
`reframed` 항목만 다음 `/analysis` 응답의 `discussion_agenda`에 추가됩니다. 원본 의견
`reason`은 공방 증거에 포함되지 않으며, LLM 실패 시 판정은 안전하게 `open`으로 유지됩니다.

로컬은 프로세스 메모리를 사용하고, App Runner에서는 DynamoDB로 방과 제출을 영속화합니다.
Google 로그인은 서명 쿠키 기반이며, 사용자 프로필 DB는 `/api/auth/me`의 `google_sub`를
기준으로 연결할 수 있습니다. WebSocket은 사용하지 않습니다.

## 다음 작업 우선순위

1. `OPENAI_API_KEY`를 주입한 실제 OpenAI 스모크 테스트
2. App Runner 인스턴스 수 1개 고정 후 배포본 릴리스 게이트
3. 모바일 2대에서 polling·결과 화면·라이브 슬라이더 리허설
