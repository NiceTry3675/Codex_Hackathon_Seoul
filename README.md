# 싱큐 (SynQ)

SynQ는 중요한 팀 결정을 확정하기 전, 의견이 갈린 기준과 결과가 바뀌는 조건을 확인하는 의사결정 점검 도구입니다.

주로 4~10명 팀이 실행 전에 선택지와 판단 기준을 함께 점검할 때 사용합니다. 각자 중요도와 평가, 이유를 제출하고, 결과를 보며 함께 논의할 내용을 정한 뒤 최종 결정을 기록합니다.

[OpenAI Codex](https://developers.openai.com/codex/)로 개발했으며, 팀은 목표와 제약을 정하고 결과를 검토했습니다.

## 라이브 데모

| | URL |
|---|---|
| **서비스** | <https://9rvtpygxvv.ap-northeast-1.awsapprunner.com> |
| API 문서 (Swagger) | <https://9rvtpygxvv.ap-northeast-1.awsapprunner.com/docs> |
| 상태 확인 | <https://9rvtpygxvv.ap-northeast-1.awsapprunner.com/api/health> |

AWS App Runner(도쿄 리전) 단일 컨테이너로 배포되어 있으며, `main` 브랜치 push 시 GitHub Actions가 ECR 이미지 빌드와 배포를 자동 수행합니다.

## 데모 영상

**[video/demo_final.mp4](video/demo_final.mp4)** — 자막·더빙 포함 2분 24초.

기존 시연 설명: 팀 4명이 실명 방 생성, 각자 평가 제출, 제출 현황 4/4 확인, 결과 분석과 결정 전 확인 질문으로 이어지는 흐름입니다. 당시 설명에는 A의 선택 비율이 75%, 가중 합산 1위가 B인 사례가 포함되어 있습니다. 75%는 4명 중 3명의 선택을 뜻합니다. 이 영상은 이전 시연 기록이며, 이번 문서 정리에서는 영상을 재검토하지 않았습니다.

## 사용 흐름

같은 선택지를 골라도 중요하게 보는 기준이나 실행 가능성에 대한 평가는 다를 수 있습니다. SynQ는 각자가 제출한 평가와 우려를 모아, 결정을 확정하기 전에 확인할 차이를 보여줍니다.

1. **결정 만들기**: 질문, 선택지, 판단 기준과 배경을 정하고 참여 링크를 공유합니다.
2. **평가 참여**: 각자 기준의 중요도, 선택지별 평가와 이유를 제출합니다. 결정 생성 시 정한 익명 또는 실명 방식으로 참여합니다.
3. **제출 현황**: 참여 인원과 제출 여부를 확인합니다.
4. **결과 확인**: 평가가 갈린 기준과 결과가 바뀌는 조건을 살펴보고, 결정 전 확인 질문에 답하며 함께 논의할 내용을 정리합니다.
5. **논의 후 다시 계산**: 팀이 중요도를 직접 조정하고 최종 선택과 결정 이유를 입력하면, 변경 전후 결과를 비교합니다. 이유를 적는 것만으로 수치가 바뀌지는 않으며, 현재 다시 계산한 결과는 방마다 한 번 저장할 수 있습니다.
6. **최종 결정 기록**: 최초 다수 선택, 분석 당시 1위, 조건별 계산에서 가장 자주 1위인 선택, 팀의 최종 선택과 이유를 저장합니다. 저장 후에는 수정할 수 없습니다.

## 결과 읽기

| 화면에서 확인할 내용 | 의미 |
|---|---|
| 현재 평가 1위 (`current_winner`) | 제출된 선택지별 평균 평가에 팀의 현재 중요도를 적용한 점수가 가장 높은 선택지 |
| 조건별 1위 비율 (`stability[option]`) | 중요도를 Dirichlet 분포로 달리한 1,000회 계산에서 해당 선택지가 1위인 비율 |
| 가장 자주 1위가 된 선택 (`robust_choice`) | 위 계산에서 1위인 비율이 가장 높은 선택지. 현재 평가 1위와 다를 수 있음 |
| 평가가 갈린 기준 | 참여자 사이에 평가 차이가 크거나 제출한 우려에서 확인할 내용이 있는 기준 |
| 결과가 바뀌는 조건 (`flip_points`) | 기준 중요도를 바꿨을 때 현재 평가 1위가 달라지는 조건. ±15%p 이내와 그 밖의 조건을 구분 |

조건별 1위 비율은 입력한 평가와 계산 조건에 따른 결과이며, 선택이 옳을 확률이나 실제 성공 확률을 뜻하지 않습니다. 한 사람의 제출을 제외했을 때 1위가 바뀌는지도 계산합니다. 이는 해당 참여자가 마음을 바꿨다는 뜻이 아닙니다.

AI는 분석 시점의 데이터를 바탕으로 결정 전 확인 질문을 만들고, 팀이 답하면 각 항목을 `resolved` / `open` / `reframed`로 자동 분류합니다. 질문·답변·분류 결과는 기록에 남으며, `open`과 `reframed` 항목을 함께 논의할 내용으로 표시합니다. 현재 이 상태 분류에는 별도의 사람 확인 단계가 없습니다. AI 분류를 참고해 무엇을 추가로 확인하고 어떤 선택을 할지는 팀이 판단합니다.

## 아키텍처

```text
참여자 평가·중요도·이유 제출
   │
   ▼
GPT 구조화 (범주형 라벨만 — 숫자를 만들지 않음)
   │
   ▼
통계 엔진 (numpy, 고정 seed) ──► 조건별 1위 비율 / 결과가 바뀌는 조건 / 평가 차이
   │
   ▼
결정 전 확인 질문 → 팀 답변 → AI 상태 분류 (분석 시점 데이터와 대화 기록 보존)
```

- **계산과 언어 처리**: 점수와 순위는 사용자 입력과 통계 계산에서 나옵니다. LLM은 자연어 구조화, 확인 질문 생성과 답변 상태 분류를 담당합니다. LLM이 실패하면 대체 처리로 분석을 제공하고, 분류를 확인할 수 없는 항목은 `open`으로 남깁니다.
- **백엔드**: FastAPI + numpy. 로컬은 인메모리, 프로덕션은 DynamoDB로 방·제출 영속화. WebSocket 없이 polling.
- **프런트엔드**: React (Vite) SPA — 결정 만들기 / 평가 참여 / 제출 현황 / 결과 확인 4화면. 중요도 슬라이더는 나머지 기준을 비례 조정해 합계를 100%로 유지합니다.
- **인증**: Google 로그인(ID 토큰을 `google-auth`로 서버 검증, HttpOnly 서명 쿠키 세션). 실명 제출 방 생성은 로그인 사용자만 가능하며, 익명 제출 방은 로그인 없이 만들고 참여할 수 있습니다.
- **익명 중복 방지**: 방별 HttpOnly 참여 쿠키를 발급하고 서버에는 해시만 저장합니다. 같은 브라우저의 반복 제출은 차단하지만 시크릿 창·쿠키 삭제·다른 기기를 이용한 우회까지 식별하지는 않습니다. IP나 Google 계정은 익명 Submission에 저장하지 않습니다.
- **배포**: 단일 Docker 이미지(React 빌드 + FastAPI 런타임) → ECR → App Runner, GitHub Actions 자동 배포 + 불변 롤백 태그.

## API 요약

| Method | Path | 설명 |
|---|---|---|
| `POST` | `/api/criteria/suggestions` | 질문·선택지·배경 맥락으로 판단 기준 제안 (팀이 최종 선택) |
| `POST` | `/api/options/suggestions` | 질문·배경 맥락으로 서로 다른 선택지 후보 제안 |
| `POST` | `/api/assistant/message` | 작성 중인 질문·선택지·판단 기준을 대화로 다듬는 도우미 |
| `POST` | `/api/rooms` | 방 생성 (배경 맥락·1~168시간 만료 설정) |
| `GET` | `/api/rooms/{code}` | 방 정보와 제출 현황, 익명 참여 쿠키 발급 |
| `POST` | `/api/rooms/{code}/submit` | 익명/실명 평가 제출 |
| `GET` | `/api/rooms/{code}/analysis` | 조건별 1위 비율·평가 차이·결과가 바뀌는 조건 분석과 확인 질문 생성 |
| `GET` | `/api/rooms/{code}/debate` | 분석 시점 데이터와 질문·답변 기록 조회 |
| `POST` | `/api/rooms/{code}/debate/defend` | 팀 답변 제출 후 AI 상태 분류 |
| `GET/POST` | `/api/rooms/{code}/decision-record/recheck` | 변경한 중요도로 다시 계산한 결과와 최종 선택·이유 조회·저장 |
| `GET/POST` | `/api/rooms/{code}/decision-record` | 불변 최종 결정 기록 조회·생성 |
| `GET/POST` | `/api/auth/*` | Google 로그인 설정·세션 |

## 개발 방식

해커톤 기간 동안 Codex로 제품 명세, 코드, 테스트, 배포 자동화와 문서를 작성했습니다. 팀은 문제와 제약 조건을 정하고 결과를 검수했습니다. Backend / Stats / Frontend / QA로 작업을 나누고, 구현 계약([`SPEC.md`](SPEC.md))과 프롬프트 명세([`prompt/`](prompt/))를 공유했습니다.

Codex가 작성하고 실행한 자동화 스크립트가 동일한 품질 게이트를 반복 검증합니다:

```bash
bash scripts/release_gate.sh   # 테스트 → 프런트 빌드 → Docker health → LIVE API → 데모 계약
```

## 로컬 실행

```bash
# 터미널 1: 백엔드
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn backend.main:app --reload --port 8000

# 터미널 2: 프런트엔드
cd frontend
npm install
npm run dev   # http://localhost:5173

# 터미널 3, 프로젝트 루트: 데모 데이터 적재
# 방 생성 + 익명 의견 4건 제출 + 분석 출력
.venv/bin/python scripts/load_demo.py
```

`OPENAI_API_KEY` 없이도 통계 분석과 결정적 폴백 경로가 전부 동작합니다. Google 로그인·Docker·배포 상세는 [`DEPLOYMENT_PLAN.md`](DEPLOYMENT_PLAN.md)를 참고하세요.

로컬에서는 방이 메모리에 저장되며 접근 시 만료 데이터를 정리합니다. 운영 환경은 `CONSENSUS_TABLE_NAME`을 설정하고 DynamoDB TTL 속성을 `expires_at`으로 활성화해야 합니다. 다중 인스턴스에서 익명 쿠키를 검증하려면 모든 인스턴스에 동일한 `ANONYMOUS_TOKEN_SECRET`을 설정하세요.

## 문서

- [`CONTEXT.md`](CONTEXT.md) — 문제 배경과 제품 철학
- [`PRODUCT_LANGUAGE.md`](PRODUCT_LANGUAGE.md) — 제품 소개와 화면 용어 기준
- [`SPEC.md`](SPEC.md) — 구현 계약
- [`prompt/04_devils_advocate_prompt.md`](prompt/04_devils_advocate_prompt.md) — 결정 전 확인 질문과 답변 상태 분류 명세
- [`demo_data.json`](demo_data.json) — 발표용 익명 입력 예시
