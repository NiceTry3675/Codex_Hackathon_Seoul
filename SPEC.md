# SynQ — SPEC.md

> 결정 전에, 무엇을 더 확인할까요?
> 팀의 평가를 모으고 중요도가 달라질 때 결과를 비교하는 웹 서비스

이 문서는 초기 Consensus의 해커톤 6시간 MVP 계획을 바탕으로 유지한 명세다. 시간표와 선택 기능은 당시 계획이며, v2 기능 전체의 구현 완료를 뜻하지 않는다. 사용자에게 보여 주는 용어와 설명은 [제품 언어 가이드](PRODUCT_LANGUAGE.md)를 따른다.

---

## 1. 제품 요약

팀원이 선택지를 어떻게 평가했는지 모아 보고, 판단 기준의 중요도가 달라질 때 평가 1위가 어떻게 바뀌는지 살펴본다. 가장 자주 1위가 된 선택(`robust_choice`, Most Robust Choice)은 계산한 조건에서의 결과이며, 모든 변화에 같은 결과가 나온다는 보장은 아니다.

핵심 출력: **조건별 1위 비율**(Stability), **평가가 갈린 기준**(Hidden Conflict), **결과가 바뀌는 조건**(Flip Point).

원칙:
- SynQ는 현재 평가 1위와 조건을 바꿔 계산한 결과를 보여 준다. 이를 바탕으로 무엇을 선택할지는 팀이 판단한다.
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
  context: str             # 배경 맥락 (선택, 최대 50,000자; 한 줄 메모부터 회의록 전문까지)
  expected_members: int    # 기본 4, 대기 화면 완료 판단용
  created_at: datetime
  expires_at: datetime     # 기본 24시간, 생성 시 1~168시간 설정
  version: int             # DynamoDB 조건부 제출 쓰기용
  used_anonymous_token_hashes: list[str]  # 원문 토큰은 저장하지 않음
  submissions: list[Submission]
  decision_record: DecisionRecord | None

Submission:
  id: str                  # uuid
  participant_name: str?   # 실명 방에서만 저장
  scores: dict[option, dict[criterion, int]]   # 1~5
  weights: dict[criterion, int]                # 1~100; 신규 UI는 합계가 정확히 100%
  first_choice: str
  reason: str              # 자유 텍스트 (선택)
  parsed: ParsedOpinion | None                 # GPT 구조화 결과

ParsedOpinion:              # GPT 출력 — 전부 범주형, 숫자 없음
  preferred_option: str
  positive: list[str]      # 언급된 긍정 기준
  concerns: list[str]      # 언급된 우려 기준

DecisionRecord:
  initial_majority_choice: str
  analysis_winner: str
  robust_choice: str
  final_choice: str
  final_reason: str
  decided_at: datetime
  changed_from_initial: bool
```

---

## 4. API

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/auth/config` | Google 로그인 활성화 여부와 공개 Client ID |
| POST | `/api/auth/google` | `credential` ID 토큰 검증 후 HttpOnly 세션 생성 |
| GET | `/api/auth/me` | 로그인 상태와 검증된 사용자 프로필 |
| POST | `/api/auth/logout` | 세션 쿠키 제거 |
| POST | `/api/criteria/suggestions` | question·options·context 기반 판단 기준·설명·1점/5점 anchor 제안 (LLM, 실패 시 범용 폴백) |
| POST | `/api/options/suggestions` | question·context 기반 선택지 후보 제안 (LLM, 실패 시 범용 폴백) |
| POST | `/api/assistant/message` | 작성 중인 방 설정을 바탕으로 질문·선택지·판단 기준을 대화형으로 정리 |
| POST | `/api/rooms` | 방 생성 (question, options, criteria, context, expires_in_hours) → room code |
| GET | `/api/rooms/{code}` | 방 정보 + 제출 수; 익명 방은 HttpOnly 참여 쿠키 발급 |
| POST | `/api/rooms/{code}/submit` | 의견 제출 (내부에서 GPT 구조화 호출) |
| GET | `/api/rooms/{code}/analysis` | 전체 분석 결과 (아래 §5 출력 전부) |
| GET | `/api/rooms/{code}/debate` | 동결 증거·질문·답변·판정 transcript 조회 |
| POST | `/api/rooms/{code}/debate/defend` | 질문별 Defender 답변 제출 및 최종 판정 |
| GET | `/api/rooms/{code}/decision-record` | 저장된 최종 결정 기록 조회 |
| POST | `/api/rooms/{code}/decision-record` | 분석 완료 후 불변 최종 결정 기록 생성 |

`/analysis` 응답 스키마:

```json
{
  "vote_share":        {"A": 0.5, "B": 0.5},
  "team_weights":      {"창의성": 0.38, "구현 가능성": 0.4, "발표 임팩트": 0.22},
  "weight_agreement":  {"창의성": "HIGH", "구현 가능성": "LOW", ...},
  "score_agreement":   {"A": {"창의성": "HIGH", "구현 가능성": "LOW"}, ...},
  "option_scores":     {"A": 3.91, "B": 3.84},
  "mean_scores":       {"A": {"창의성": 4.5, "구현 가능성": 2.5}, ...},
  "hidden_conflicts":  ["A의 구현 가능성에 대한 평가가 갈립니다."],
  "stability":         {"A": 0.46, "B": 0.54},
  "current_winner":    "A",
  "robust_choice":     "B",
  "flip_points": [
    {"type": "weight", "criterion": "구현 가능성", "from": 0.30, "to": 0.34,
     "change": 0.04, "direction": "increase", "proximity": "nearby", "new_winner": "B"},
    {"type": "member", "description": "응답 하나를 제외하면 현재 평가 1위가 달라집니다."}
  ],
  "discussion_agenda": ["10분 동안 A의 구현 가능성에 대한 평가가 갈린 이유를 함께 확인해 보세요."],
  "devils_advocate": {
    "target": "A",
    "challenges": [
      "구현 가능성 우려가 2건 있습니다. 6시간 안에 완성하지 못하면 어떤 대안을 쓸 수 있나요?",
      "발표 임팩트를 기대하려면 데모가 어느 수준까지 완성되어야 하나요?"
    ]
  }
}
```

---

## 5. 통계 엔진 (`stats.py`, numpy만 사용)

1. **팀 중요도**(Team Weights): 개인 weight 슬라이더 평균 → largest-remainder 방식의 정수 퍼센트 보정. 합계는 항상 100%. 개인 간 분산 = 기준 합의도.
2. **평가의 일치 정도**(Agreement Score): 기준별 점수의 표준편차. σ ≤ 0.8 HIGH / ≤ 1.5 MID / 그 외 LOW.
3. **현재 평가 점수**: `score(option) = Σ_c team_weight[c] × mean(scores[option][c])`. 이 점수가 가장 높은 선택지가 현재 평가 1위(`current_winner`)다.
4. **조건별 1위 비율**(Stability, Sensitivity Analysis)
   - 팀 가중치를 중심으로 Dirichlet 노이즈 섭동 → 1,000회 재계산.
   - MVP 기본값은 concentration 50, seed 42로 고정해 데모와 테스트를 재현 가능하게 한다.
   - `stability(option) = 해당 옵션이 1위인 시뮬레이션 비율`
   - `robust_choice = argmax(stability)`
   - 선택지별 비율이며, 가장 자주 1위가 된 선택(`robust_choice`)과 현재 평가 1위(`current_winner`)는 다를 수 있다. 현재 평가 1위의 유지 비율을 표시할 때는 `stability[current_winner]`를 사용한다. 어느 값도 성공 확률이나 팀의 동의 비율을 뜻하지 않는다.
5. **결과가 바뀌는 조건 — 중요도**(Flip Point, weight)
   - 각 기준의 가중치를 1%p씩 증가·감소시키고 나머지를 비례 재분배하며 1위가 바뀌는 최소 지점을 탐색한다.
   - 현재 값에서 ±15%p 이내는 `nearby`, 그보다 먼 조건은 `theoretical`로 분류한다.
   - 이론적 조건만 있으면 기본 결과에는 "각 판단 기준의 중요도를 현재 값에서 ±15%p 이내로 바꿔 계산한 범위에서는 평가 1위가 바뀌는 조건을 찾지 못했습니다."를 표시한다.
6. **결과가 바뀌는 조건 — 응답 제외**(Flip Point, member)
   - MVP에서는 제출을 하나씩 제거해 재계산한다. 1순위만 바꾸는 반사실 계산은 점수 변경 규칙을 정한 뒤 확장한다.
   - 응답 하나를 제외한 결과를 비교하는 것이며, 한 사람이 의견을 바꾼 상황을 계산한 것은 아니다.
7. **평가가 갈린 기준**(Hidden Conflict)
   - 1위 옵션에 대해: 다수가 first_choice로 골랐지만 특정 기준 점수가 LOW agreement
     또는 GPT `concerns`에 다수 등장 → 충돌 문구 생성.
8. **함께 논의할 내용**(Discussion Agenda): flip point 기준 + hidden conflict를 문장으로 변환.

주의: n이 4~6명이라 모든 지표는 서술적(descriptive) 용도. 통계적 유의성 주장 금지.

---

## 6. GPT 사용 (`llm.py`)

초기 두 용도는 다음과 같다. 현재는 선택지·판단 기준 후보, 설정 도움말, 팀 답변 검토에도 사용한다. 점수·승자 계산은 통계 엔진 전용이다.

1. **구조화**: `reason` 자유 텍스트 → `ParsedOpinion` (JSON mode, 범주형만).
2. **결정 전 확인 질문**(Devil's Advocate 에이전트, 멀티 에이전트 요소)
   - 분석 완료 후 1회 호출: 통계 결과(1위 옵션, LOW agreement 기준, concerns 목록)를
     입력으로 받아 현재 평가 1위를 선택하기 전에 확인할 질문 2~3개 생성.
   - 출력은 정성적 질문만. 선택의 전제와 우려를 확인하도록 돕는다. 질문 자체가
     결과가 바뀌는 조건(Flip Point)을 계산하거나 증명하지는 않는다.
   - 결과 화면에서 함께 논의할 내용(Discussion Agenda)과 한 블록으로 표시.

- 실패/타임아웃 시 기능별 기본 질문·예시·안내를 사용하며, 답변 검토 실패는 추가 확인이 필요한 상태로 남긴다. 출처가 기본 처리임을 표시한다. 자연어 구조화 실패는 빈 범주로 처리한다. 기존 통계 결과를 AI가 덮어쓰지 않는다.
- 모델: `gpt-6-astra`. 모델 ID는 환경변수 `OPENAI_MODEL`, 키는 `OPENAI_API_KEY`로 주입.
- (옵션, 시간 남으면) 페르소나 토론 시뮬레이션: 각 익명 제출을 에이전트로 만들어
  토론시키는 확장. 출력 비결정성 때문에 라이브 데모에는 넣지 말 것.

---

## 7. MCP 서버 (시간 남으면, 우선순위 최하)

FastAPI 로직을 그대로 노출: `submit_preference()`, `analyze_consensus()`,
`simulate_decision()`, `find_flip_point()`. 데모에서 "Codex → MCP 호출" 시연용.

---

## 8. 프론트엔드 (React + Tailwind, 3화면)

1. **입력**: 항목형 방 만들기/코드 참여 → 선택지별 판단 기준 점수(1=부정적, 5=긍정적) + 합계 100% 연동 중요도 슬라이더 + 이유 텍스트. 방 생성자가 익명/실명 모드를 선택한다.
2. **대기/현황**: 익명 모드에서는 제출 인원 수만 표시하고, 실명 모드에서는 제출자 이름도 표시한다. 전원 제출 시 결과 확인 버튼이 활성화된다.
3. **결과**: 현재 평가 1위(Current Winner)·조건별 1위 비율(Stability)·평가가 갈린 기준(Hidden Conflict)·가까운 범위에서 결과가 바뀌는 조건(Flip Point)을 먼저 표시하고 상세 계산·이론적 Flip Point는 접는다. 연동 중요도 슬라이더, 결정 전 확인 질문(Devil's Advocate)과 답변, 함께 논의할 내용(Discussion Agenda), 최종 결정 기록(Decision Record)을 제공한다.

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

- DynamoDB로 room을 영속화한다. `expires_at` Number 속성에 TTL을 활성화하고, `version` 조건부 쓰기로 동시 제출을 직렬화한다.
- `ANONYMOUS_TOKEN_SECRET`은 모든 App Runner 인스턴스에 동일한 32자 이상 비밀값으로 설정한다. 토큰 원문, IP, Google 계정은 익명 Submission에 저장하지 않는다.
- 익명 중복 방지는 같은 브라우저의 쿠키를 기준으로 하므로 시크릿 창, 쿠키 삭제, 다른 기기를 통한 우회 가능성을 UI와 문서에 알린다.
- 배포는 코딩 완료 기다리지 말고 **2시간 차에 hello-world 컨테이너로 먼저** 파이프라인 검증.

---

## 10. 범위 제외

자체 비밀번호 로그인, Google 이외 소셜 로그인, 사용자·닉네임 DB 구현,
Submission과 로그인 계정 연결, Slack/채팅 연동, 실시간 음성 분석, 조직 관리,
WebSocket(현황 갱신은 3초 폴링으로 충분), 복잡한 NLP.

---

## 11. 초기 MVP 역할 분담 & 타임라인 (6h, 당시 계획)

| 시간 | Backend | Stats | Frontend | 비전공 |
|---|---|---|---|---|
| 0–1h | 방/제출 API | stats.py 골격 + 단위 테스트 | 화면 1 | 기준·문구 정의 |
| 1–3h | GPT 구조화 + Devil's Advocate, /analysis | Stability·Flip Point | 화면 3 | 데모 데이터 작성 |
| 3–4h | 통합 | member flip, agenda | 슬라이더 라이브 시연 | 결과 문구 검수 |
| 4–5h | **AWS 배포** | 엣지케이스(동점 등) | 폴리싱 | 발표 준비 |
| 5–6h | 버퍼 | 버퍼 | 버퍼 | 리허설 |

데모는 사전 입력 데이터로 시작, 라이브는 가중치 슬라이더 조작만.
