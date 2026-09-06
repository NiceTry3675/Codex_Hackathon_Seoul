# 싱큐 (SynQ)

> **합의보다, 더 나은 선택.**
> 서로 다른 판단을 드러내 더 나은 의견 일치를 돕는 의사결정 도구

> [!NOTE]
> **Built entirely with [OpenAI Codex](https://developers.openai.com/codex/).**
> 아이디어 구체화, 제품·아키텍처 설계, 프롬프트 작성, 프런트엔드·백엔드 구현,
> 테스트, 배포 자동화, 문서화까지 이 프로젝트의 모든 개발 작업을 Codex로 수행했습니다.
> 팀은 목표와 제약을 정하고 Codex의 결과를 검토하며 제품 의사결정을 내렸습니다.

## 🔗 라이브 데모

| | URL |
|---|---|
| **서비스** | <https://9rvtpygxvv.ap-northeast-1.awsapprunner.com> |
| API 문서 (Swagger) | <https://9rvtpygxvv.ap-northeast-1.awsapprunner.com/docs> |
| 상태 확인 | <https://9rvtpygxvv.ap-northeast-1.awsapprunner.com/api/health> |

AWS App Runner(도쿄 리전) 단일 컨테이너로 배포되어 있으며, `main` 브랜치 push 시 GitHub Actions가 ECR 이미지 빌드와 배포를 자동 수행합니다.

## 🎬 데모 영상

**[video/demo_final.mp4](video/demo_final.mp4)** — 자막·더빙 포함 2분 24초.

팀 4명이 실제로 사용하는 전체 흐름을 담았습니다: 실명 방 생성 → 메인 발표자 의견 제출 → 나머지 팀원 3명이 각자 화면에서 제출(배속) → 대기실 4/4 → 결정 안정성 분석. 표로는 A가 75%로 만장일치처럼 보이지만, 가중 합산 1위는 B였고 조건을 흔들어도 B가 1위를 유지하는 과정 — 그리고 Devil's Advocate가 그 결정을 공격하는 질문까지 이어집니다.

## 문제: 가짜 합의

회의 끝에 4명 전원이 A안에 동의했다 — 만장일치. 하지만 한 명은 사실 다른 안을 원했고, 한 명은 A가 불가능하다고 생각한다. 반대는 근거·대안·감정 비용을 요구하기 때문에 침묵 속으로 사라지고(애빌린 패러독스, 집단사고), 문제는 실행 단계에서 "사실 저는 처음부터…"로 터진다.

기존 투표 앱은 "왜 찍었는지"를 보지 않고, 회의 요약 AI는 말하지 않은 반대를 기록할 수 없다. **싱큐는 익명 입력으로 침묵을 데이터로 바꾸고, 서로 다른 판단과 우려를 함께 살펴 더 나은 의견 일치에 도달하도록 돕습니다.**

## 무엇을 보여주는가

1. **Hidden Conflict** — 찬성표 뒤에 숨은 우려. "전원이 A에 찬성했지만, 전원이 구현 가능성을 걱정한다."
2. **Decision Stability** — 평가 기준 가중치를 Dirichlet 섭동으로 1,000번 흔들었을 때 현재 1위가 살아남는 비율. 표면적 합의 100%가 실질 안정성 47%일 수 있다.
3. **Flip Point** — 기준 비중을 올리거나 내렸을 때 결정이 뒤집히는 최소 조건. ±15%p 이내는 가까운 조건으로, 그 밖은 상세 화면의 이론적 조건으로 구분합니다.
4. **Most Robust Choice** — 가장 많은 표를 받은 답이 아니라, 평가 조건이 흔들려도 1위를 유지할 확률이 가장 높은 답.

여기에 **Devil's Advocate 공방**과 **Decision Record**가 붙습니다. 분석 결과를 동결한 증거로 삼아 Challenger가 검증 가능한 질문을 던지고, 팀(Defender)이 답변하면 최대 2라운드 안에 각 쟁점을 `resolved` / `open` / `reframed`로 판정합니다. 논의 뒤에는 최초 다수 선택, 분석 당시 1위, Most Robust Choice, 최종 선택과 이유를 함께 보존합니다.

**싱큐는 결정을 대신하지 않습니다. 결정이 얼마나 견고한지 보여줄 뿐입니다.** 판단과 책임은 팀에 남기고, 판단의 조건만 드러냅니다.

## 아키텍처

```text
자연어 익명 입력
   │
   ▼
GPT 구조화 (범주형 라벨만 — 숫자를 만들지 않음)
   │
   ▼
통계 엔진 (numpy, 결정적) ──► Stability / Flip Point / Hidden Conflict
   │
   ▼
Devil's Advocate 공방 (증거 동결, append-only transcript, 실패 시 통계 결과 유지)
```

- **계산과 이해의 분리**: 모든 수치는 사용자 입력 + 결정적 통계에서만 나옵니다. LLM은 자연어 구조화와 반론 생성만 담당하고, LLM이 실패해도 분석은 폴백으로 동작합니다.
- **백엔드**: FastAPI + numpy. 로컬은 인메모리, 프로덕션은 DynamoDB로 방·제출 영속화. WebSocket 없이 polling.
- **프런트엔드**: React (Vite) SPA — 항목형 방 만들기 / 의견 입력 / 제출 현황 / 분석 결과 4화면. 가중치 슬라이더는 나머지 기준을 비례 조정해 합계를 정확히 100%로 유지합니다.
- **인증**: Google 로그인(ID 토큰을 `google-auth`로 서버 검증, HttpOnly 서명 쿠키 세션). 실명 제출 방 생성은 로그인 사용자만 가능하며, 익명 제출 방은 로그인 없이 만들고 참여할 수 있습니다.
- **익명 중복 방지**: 방별 HttpOnly 참여 쿠키를 발급하고 서버에는 해시만 저장합니다. 같은 브라우저의 반복 제출은 차단하지만 시크릿 창·쿠키 삭제·다른 기기를 이용한 우회까지 식별하지는 않습니다. IP나 Google 계정은 익명 Submission에 저장하지 않습니다.
- **배포**: 단일 Docker 이미지(React 빌드 + FastAPI 런타임) → ECR → App Runner, GitHub Actions 자동 배포 + 불변 롤백 태그.

## API 요약

| Method | Path | 설명 |
|---|---|---|
| `POST` | `/api/criteria/suggestions` | 질문·선택지·배경 맥락으로 평가 기준 제안 (팀이 최종 선택) |
| `POST` | `/api/options/suggestions` | 질문·배경 맥락으로 서로 다른 선택지 후보 제안 |
| `POST` | `/api/assistant/message` | 작성 중인 질문·선택지·평가 기준을 대화로 다듬는 생성 도우미 |
| `POST` | `/api/rooms` | 방 생성 (배경 맥락·1~168시간 만료 설정) |
| `GET` | `/api/rooms/{code}` | 방 정보와 제출 현황, 익명 참여 쿠키 발급 |
| `POST` | `/api/rooms/{code}/submit` | 익명/실명 의견 제출 |
| `GET` | `/api/rooms/{code}/analysis` | 안정성·갈등·flip point 분석 (+ Challenger 질문 생성) |
| `GET` | `/api/rooms/{code}/debate` | 동결 증거와 공방 transcript 조회 |
| `POST` | `/api/rooms/{code}/debate/defend` | Defender 답변 제출 후 최종 판정 |
| `GET/POST` | `/api/rooms/{code}/decision-record` | 불변 최종 결정 기록 조회·생성 |
| `GET/POST` | `/api/auth/*` | Google 로그인 설정·세션 |

## 개발 방식

이 프로젝트는 해커톤 기간 동안 모든 개발 작업을 OpenAI **Codex**로 수행했습니다. 사람은 문제와 목표, 제약 조건을 정의하고 결과를 검수했으며, Codex가 제품 명세 작성부터 코드 구현, 테스트, 장애 진단, 배포 자동화, 문서 정리까지 실행했습니다. Backend / Stats / Frontend / QA 역할로 작업을 나누고, 구현 계약([`SPEC.md`](SPEC.md))과 프롬프트 명세([`prompt/`](prompt/))를 먼저 고정해 각 작업이 같은 경계 안에서 이어지도록 했습니다. 런타임의 Devil's Advocate까지 포함하면, 에이전트 기반 작업 방식을 개발 과정과 제품 양쪽에 적용한 셈입니다.

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
- [`SPEC.md`](SPEC.md) — 구현 계약
- [`prompt/04_devils_advocate_prompt.md`](prompt/04_devils_advocate_prompt.md) — Devil's Advocate 공방 명세
- [`demo_data.json`](demo_data.json) — 발표용 익명 입력 예시
