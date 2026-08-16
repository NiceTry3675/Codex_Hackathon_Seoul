# Consensus

> Agree less. Decide better.

익명 입력을 바탕으로 팀 결정의 안정성, 숨은 갈등, 뒤집힘 조건을 보여주는 해커톤 MVP입니다.

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
  main.py              FastAPI 라우터와 인메모리 room 저장소
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
| `POST` | `/api/rooms` | 방 생성 |
| `GET` | `/api/rooms/{code}` | 방 정보와 제출 현황 |
| `POST` | `/api/rooms/{code}/submit` | 익명 의견 제출 |
| `GET` | `/api/rooms/{code}/analysis` | 안정성·갈등·flip point 분석 |

저장은 프로세스 메모리만 사용하므로 서버 재시작 시 초기화됩니다. DB, 로그인, WebSocket은 이 MVP 범위에 포함하지 않습니다.

## 다음 작업 우선순위

1. `demo_data.json`의 수치를 발표 서사에 맞게 최종 조정
2. Devil's Advocate 실제 OpenAI 호출 및 데모 폴백 문구 확정
3. 빈 입력·동점·잘못된 옵션/기준에 대한 API 테스트 보강
4. 배포 환경에서 인스턴스 수 1개 고정 후 E2E 리허설
