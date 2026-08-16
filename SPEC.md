# Consensus — SPEC.md

> Agree less. Decide better.
> 팀 의사결정의 안정성을 수치로 검증하는 웹 서비스 (해커톤 6시간 MVP)

---

## 1. 제품 요약

표면적 합의 뒤에 숨은 의견 차이를 찾아내고, 조건이 변해도 뒤집히지 않는 **Most Robust Choice**를 제시한다.

핵심 출력: **Decision Stability Score**, **Hidden Conflict**, **Flip Point**.

원칙:
- Consensus는 결정을 추천하지 않는다. 결정의 견고성을 보여줄 뿐이다.
- 계산은 Python(통계), 의미 이해는 GPT. GPT는 숫자를 만들지 않는다.
- 방 생성자가 **익명 또는 실명 제출**을 선택한다. 개인 점수·의견은 어느 모드에서도 공개하지 않는다.
- Google 로그인 계정은 Submission에 자동 연결하지 않는다. 실명 모드에서는 사용자가
  입력한 `participant_name`만 제출 완료 여부에 사용한다.

---

## 2. 아키텍처

```
[React SPA] ──HTTP──> [FastAPI] ──> [Stats Engine (numpy)]
                          │
                          └──> [OpenAI API (구조화 전용)]

[Google Identity Services] ──ID token──> [FastAPI 검증] ──> [서명 세션 쿠키]

배포: Docker 단일 컨테이너 (FastAPI가 React 빌드 정적 서빙)
      → AWS App Runner (권장) 또는 EC2
저장: 로컬은 인메모리 dict, App Runner는 DynamoDB (`consensus-rooms`)
```

- 단일 컨테이너, 단일 프로세스. 로컬은 인메모리 fallback을 쓰고 배포 환경은
  DynamoDB만 사용한다. Redis와 별도 큐는 두지 않는다.
- 방(room) 단위 세션: 6자리 코드로 생성/참여. 링크 공유 → 팀원 각자 폰에서 입력.
- 계정 세션은 Google 로그인만 지원한다. 서버가 ID 토큰을 검증하고 `sub`를 사용자 키로
  사용한다. 닉네임·사용자 DB는 배포 담당 서버에서 이 키에 연결한다.
- 의견 제출 데이터에는 Google `sub`와 이메일을 저장하지 않는다. 실명 모드에서만
  사용자가 직접 입력한 `participant_name`을 저장한다.

---

## 3. 데이터 모델

```python
rooms: dict[str, Room]  # 로컬 fallback; 배포 환경은 DynamoDB

Room:
  code: str                # "X7K2P9"
  question: str            # "해커톤 아이디어 선택"
  options: list[str]       # ["A. AI 보안 도구", "B. 의사결정 도구", ...]
  criteria: list[str]      # ["창의성", "구현 가능성", "발표 임팩트"]
  expected_members: int    # 기본 4, 대기 화면 완료 판단용
  submissions: list[Submission]

Submission:
  id: str                  # uuid
  participant_name: str?   # 실명 방에서만 저장
  scores: dict[option, dict[criterion, int]]   # 1~5
  weights: dict[criterion, int]                # 1~10 슬라이더
  first_choice: str
  reason: str              # 자유 텍스트 (선택)
  parsed: ParsedOpinion | None                 # GPT 구조화 결과

ParsedOpinion:              # GPT 출력 — 전부 범주형, 숫자 없음
  preferred_option: str
  positive: list[str]      # 언급된 긍정 기준
  concerns: list[str]      # 언급된 우려 기준
```

---

## 4. API

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/auth/config` | Google 로그인 활성화 여부와 공개 Client ID |
| POST | `/api/auth/google` | `credential` ID 토큰 검증 후 HttpOnly 세션 생성 |
| GET | `/api/auth/me` | 로그인 상태와 검증된 사용자 프로필 |
| POST | `/api/auth/logout` | 세션 쿠키 제거 |
| POST | `/api/rooms` | 방 생성 (question, options, criteria) → room code |
| GET | `/api/rooms/{code}` | 방 정보 + 제출 수 |
| POST | `/api/rooms/{code}/submit` | 의견 제출 (내부에서 GPT 구조화 호출) |
| GET | `/api/rooms/{code}/analysis` | 전체 분석 결과 (아래 §5 출력 전부) |

`/analysis` 응답 스키마:

```json
{
  "vote_share":        {"A": 0.5, "B": 0.5},
  "team_weights":      {"창의성": 0.38, "구현 가능성": 0.4, "발표 임팩트": 0.22},
  "weight_agreement":  {"창의성": "HIGH", "구현 가능성": "LOW", ...},
  "score_agreement":   {"A": {"창의성": "HIGH", "구현 가능성": "LOW"}, ...},
  "option_scores":     {"A": 3.91, "B": 3.84},
  "mean_scores":       {"A": {"창의성": 4.5, "구현 가능성": 2.5}, ...},
  "hidden_conflicts":  ["A의 가치에는 동의하지만 구현 가능성 신뢰가 낮음"],
  "stability":         {"A": 0.46, "B": 0.54},
  "current_winner":    "A",
  "robust_choice":     "B",
  "flip_points": [
    {"type": "weight", "criterion": "구현 가능성", "from": 0.30, "to": 0.34,
     "new_winner": "B"},
    {"type": "member", "description": "1명이 A→B로 바꾸면 결과가 뒤집힘"}
  ],
  "discussion_agenda": ["A의 구현 가능성이 유일한 실질 쟁점 — 10분 논의 권장"],
  "devils_advocate": {
    "target": "A",
    "challenges": [
      "구현 가능성 우려가 2건인데 6시간 내 실패 시 대안은?",
      "A 지지 이유가 전부 '발표 임팩트'인데, 임팩트는 완성된 데모가 전제 아닌가?"
    ]
  }
}
```

---

## 5. 통계 엔진 (`stats.py`, numpy만 사용)

1. **팀 가중치**: 개인 weight 슬라이더 평균 → 정규화. 개인 간 분산 = 기준 합의도.
2. **Agreement Score**: 기준별 점수의 표준편차. σ ≤ 0.8 HIGH / ≤ 1.5 MID / 그 외 LOW.
3. **현재 점수**: `score(option) = Σ_c team_weight[c] × mean(scores[option][c])`
4. **Stability (Sensitivity Analysis)** ⭐
   - 팀 가중치를 중심으로 Dirichlet 노이즈 섭동 → 1,000회 재계산.
   - MVP 기본값은 concentration 50, seed 42로 고정해 데모와 테스트를 재현 가능하게 한다.
   - `stability(option) = 해당 옵션이 1위인 시뮬레이션 비율`
   - `robust_choice = argmax(stability)`
5. **Flip Point (weight)** ⭐
   - 각 기준의 가중치를 1%p씩 증가(나머지 비례 감소)시키며 1위가 바뀌는 최소 지점 탐색.
6. **Flip Point (member)**
   - MVP에서는 제출을 하나씩 제거해 재계산한다. 1순위만 바꾸는 반사실 계산은 점수 변경 규칙을 정한 뒤 확장한다.
7. **Hidden Conflict**
   - 1위 옵션에 대해: 다수가 first_choice로 골랐지만 특정 기준 점수가 LOW agreement
     또는 GPT `concerns`에 다수 등장 → 충돌 문구 생성.
8. **Discussion Agenda**: flip point 기준 + hidden conflict를 문장으로 변환.

주의: n이 4~6명이라 모든 지표는 서술적(descriptive) 용도. 통계적 유의성 주장 금지.

---

## 6. GPT 사용 (`llm.py`)

용도 두 가지. 어느 쪽도 숫자를 만들지 않는다 (점수·승자 판정은 통계 엔진 전용).

1. **구조화**: `reason` 자유 텍스트 → `ParsedOpinion` (JSON mode, 범주형만).
2. **Devil's Advocate 에이전트** ⭐ (멀티 에이전트 요소)
   - 분석 완료 후 1회 호출: 통계 결과(1위 옵션, LOW agreement 기준, concerns 목록)를
     입력으로 받아 1위 옵션을 공격하는 반론 질문 2~3개 생성.
   - 출력은 정성적 질문만. Red Team 사고방식("이 결정은 어떤 조건에서 깨지는가")의
     LLM 버전이자, 통계적 Flip Point의 정성 버전.
   - 결과 화면에서 Discussion Agenda와 한 블록으로 표시.

- 실패/타임아웃 시 해당 필드 없이 진행 (GPT는 필수 경로가 아님).
- 모델: `gpt-5.6-sol`. 모델 ID는 환경변수 `OPENAI_MODEL`, 키는 `OPENAI_API_KEY`로 주입.
- (옵션, 시간 남으면) 페르소나 토론 시뮬레이션: 각 익명 제출을 에이전트로 만들어
  토론시키는 확장. 출력 비결정성 때문에 라이브 데모에는 넣지 말 것.

---

## 7. MCP 서버 (시간 남으면, 우선순위 최하)

FastAPI 로직을 그대로 노출: `submit_preference()`, `analyze_consensus()`,
`simulate_decision()`, `find_flip_point()`. 데모에서 "Codex → MCP 호출" 시연용.

---

## 8. 프론트엔드 (React + Tailwind, 3화면)

1. **입력**: 방 만들기/코드 참여 → 옵션별 기준 점수(1~5) + 기준 중요도 슬라이더(1~10) + 이유 텍스트. 방 생성자가 익명/실명 모드를 선택한다.
2. **대기/현황**: 제출 인원 수만 표시 (개별 답변 비공개). 전원 제출 시 분석 버튼 활성화.
3. **결과** ⭐: 득표 → Stability 게이지 → Hidden Conflict → Flip Point → Robust Choice → Discussion Agenda + Devil's Advocate 반론 순서로 스크롤 스토리텔링. 가중치 슬라이더 라이브 조작 → 순위 뒤집힘 시연 가능하게.

Team Map(2D 산점도)은 시간 남을 때만. 첫 번째 컷 대상.

---

## 9. AWS 배포

### 권장: App Runner (관리 최소, HTTPS 자동)

```
1. Dockerfile: python:3.12-slim
   - React 빌드 산출물(dist/)을 FastAPI StaticFiles로 서빙
   - CMD: uvicorn main:app --host 0.0.0.0 --port 8080
2. ECR에 push:
   aws ecr create-repository --repository-name consensus
   docker build -t consensus . && docker push <ecr-uri>
3. App Runner 서비스 생성 (콘솔 5분):
   - 소스: ECR 이미지 / 포트 8080 / 1 vCPU, 2GB
   - 환경변수: OPENAI_API_KEY
4. 발급된 https://xxx.awsapprunner.com 을 팀원에게 공유
```

### 대안: EC2 (App Runner 권한 없을 때)

t3.small + docker run, 보안그룹 80/443 오픈, 필요 시 Caddy로 HTTPS.

### 주의

- DynamoDB로 room을 영속화한다. 데모 비용과 동작 예측성을 위해 App Runner min/max instance는 1로 유지한다.
- 배포는 코딩 완료 기다리지 말고 **2시간 차에 hello-world 컨테이너로 먼저** 파이프라인 검증.

---

## 10. 범위 제외

자체 비밀번호 로그인, Google 이외 소셜 로그인, 사용자·닉네임 DB 구현,
Submission과 로그인 계정 연결, Slack/채팅 연동, 실시간 음성 분석, 조직 관리,
WebSocket(현황 갱신은 3초 폴링으로 충분), 복잡한 NLP.

---

## 11. 역할 분담 & 타임라인 (6h)

| 시간 | Backend | Stats | Frontend | 비전공 |
|---|---|---|---|---|
| 0–1h | 방/제출 API | stats.py 골격 + 단위 테스트 | 화면 1 | 기준·문구 정의 |
| 1–3h | GPT 구조화 + Devil's Advocate, /analysis | Stability·Flip Point | 화면 3 | 데모 데이터 작성 |
| 3–4h | 통합 | member flip, agenda | 슬라이더 라이브 시연 | 결과 문구 검수 |
| 4–5h | **AWS 배포** | 엣지케이스(동점 등) | 폴리싱 | 발표 준비 |
| 5–6h | 버퍼 | 버퍼 | 버퍼 | 리허설 |

데모는 사전 입력 데이터로 시작, 라이브는 가중치 슬라이더 조작만.
