# Consensus — PLAN.md

> 6시간 구현 계획. 스펙은 SPEC.md, 서사는 CONTEXT.md 참조.
> 체제: **Insight 2명 + Build 2명**. 전원이 Codex 에이전트의 발주자·검수자.

---

## 1. 역할 분배

| 역할 | 담당 | 책임 |
|---|---|---|
| **Build-F** | Frontend + Stats | 화면 1·2·3, 가중치 슬라이더 라이브 시연, `stats.py`(Stability·Flip Point) + 단위 테스트 |
| **Build-B** | Backend + 통합 오너 | FastAPI, GPT 연동(llm.py), 3h 통합 주도 |
| **Insight-D** | 배포 + Red Team QA | Docker→ECR→App Runner, Devil's Advocate 프롬프트 설계, 공격적 테스트 |
| **Insight-P** | 제품 + 발표 | 데모 데이터 설계, 결과 문구/UX 검증, 발표 준비·리허설 주도 |

원칙:
- 파일 소유권은 1인 1모듈. 남의 파일을 고치지 말고 소유자에게 요청.
- Insight 2명은 "코딩 안 하는 사람"이 아니라 **검증 계층**이다.
  Insight-D는 시스템을 공격하고, Insight-P는 사용자 관점에서 제품을 공격한다.

---

## 2. 저장소 구조 & 소유권

```
consensus/
├── backend/
│   ├── main.py            # FastAPI 앱 + 라우터        [Build-B]
│   ├── models.py          # Room/Submission dataclass  [Build-B]
│   ├── stats.py           # 통계 엔진 (numpy only)      [Build-F]
│   ├── llm.py             # GPT 구조화 + Devil's Adv.  [Build-B, 프롬프트는 Insight-D]
│   └── tests/
│       └── test_stats.py  # 손계산 기대값 대조 필수     [Build-F]
├── frontend/              # React + Tailwind (Vite)    [Build-F]
│   └── src/
│       ├── pages/         # Submit / Waiting / Results
│       └── mock.ts        # API 목데이터 (계약 = SPEC §4)
├── Dockerfile             #                             [Insight-D]
├── demo_data.json         # 사전 입력 데모 시나리오      [Insight-P]
└── SPEC.md / CONTEXT.md / PLAN.md
```

---

## 3. 첫 30분: 계약 동결 (전원)

1. SPEC §4 API 스키마를 넷이 같이 읽고 필드명까지 확정 → 이후 변경 금지.
2. `frontend/src/mock.ts`에 분석 응답 예시 JSON을 박제 → 프론트는 백엔드 없이 개발 시작.
3. 데모 시나리오 합의: 옵션 3개·기준 3개·팀원 4명 입력값의 초안 (Insight-P 주도).
   **갈등이 선명해야 함** — 표는 갈리고, 한 기준의 agreement가 확실히 LOW이고,
   flip point가 한 자릿수 %로 나오도록 Insight-P + Build-F가 숫자를 역설계.
4. 저장소 생성, 브랜치 전략은 main 직push (해커톤이므로 PR 금지, 충돌은 소유권으로 방지).

---

## 4. 타임라인

| 시간 | Build-F | Build-B | Insight-D | Insight-P |
|---|---|---|---|---|
| 0:00–0:30 | ── 전원: 계약 동결 (§3) ── ||||
| 0:30–1:30 | 화면 1 (에이전트 발주) + stats.py 골격·점수 | rooms/submit API + models | Dockerfile 작성, ECR 준비 | 데모 데이터 수치 확정, 결과 문구 초안 |
| 1:30–2:00 | 화면 2 + stats.py: agreement | llm.py: GPT 구조화 | **hello-world 컨테이너 배포 검증** ⭐ | 발표 스켈레톤 (CONTEXT §4 기반) |
| 2:00–3:00 | 화면 3 (목데이터) + stats.py: Stability·Flip Point + 테스트 | /analysis 조립 + Devil's Advocate 연동 | Devil's Advocate 프롬프트 → Build-B에 전달 | 화면 1·3 문구 검수 (목데이터 화면 보며) |
| 3:00–4:00 | ── **통합** (Build-B 주도, Build-F 지원) ── || API 공격 테스트 (빈 입력·동점·1명 제출) | demo_data.json을 실서비스에 입력 = E2E 테스트 |
| 4:00–5:00 | 슬라이더 라이브 시연 폴리싱 | 엣지케이스 수정 | **본 배포 + URL 발급** ⭐ | 발표 자료 완성 |
| 5:00–6:00 | ── 전원: 배포본으로 리허설 2회 (Insight-P 진행) ── ||||

체크포인트 (놓치면 즉시 범위 축소):
- **2:00** 배포 파이프라인 검증 완료 — 실패 시 EC2 폴백 즉시 전환
- **3:00** stats.py 테스트 통과 — 실패 시 member flip 컷, weight flip만
- **4:00** E2E 1회 성공 — 실패 시 화면 2 컷 (생성자가 대신 입력하는 데모로 전환)

---

## 5. Codex 에이전트 초기 프롬프트

각자 자기 모듈의 에이전트에게 첫 발주. 공통 헤더: *"SPEC.md의 해당 섹션을 따를 것.
스키마 필드명 변경 금지. 외부 의존성 최소화."*

- **Frontend 에이전트** (Build-F):
  "React+Vite+Tailwind SPA. 화면 3개(SPEC §8). API는 mock.ts를 fetch 래퍼로 감싸
  실제 API와 스위치 가능하게. 화면 3의 가중치 슬라이더는 클라이언트에서 점수를
  실시간 재계산해 순위 변동을 즉시 보여줄 것 (서버 왕복 없이)."
- **Backend 에이전트** (Build-B):
  "FastAPI, 인메모리 dict 저장, SPEC §3 모델·§4 엔드포인트. CORS 허용.
  React 빌드 산출물 StaticFiles 서빙. GPT 호출은 llm.py로 분리, 실패 시 None 폴백."
- **Stats 에이전트** (Build-F):
  "numpy만 사용. SPEC §5의 1~8 구현. 순수 함수로 작성 (입력: submissions,
  출력: analysis dict). test_stats.py에 손계산 검증 케이스 3개 포함."
- **QA 에이전트** (Insight-D):
  "배포된 API에 대해 비정상 입력 시나리오 스크립트 작성: 제출 0건 분석 요청,
  동점, 단일 기준, 특수문자 이유 텍스트. 각 케이스의 기대 동작을 표로 정리."

---

## 6. 리스크 & 플랜 B

| 리스크 | 플랜 B |
|---|---|
| GPT 장애/지연 | 설계상 비필수 경로 (parsed=None 진행). Devil's Advocate는 데모 데이터용 응답을 demo_data.json에 캐시해두고 폴백 |
| App Runner 권한/실패 | 2:00 검증에서 걸러짐 → EC2 t3.small + docker run 폴백 (Insight-D가 절차 사전 숙지) |
| 통합 지연 | 화면 2 컷, member flip 컷. **화면 3 + weight flip + stability는 사수** — 이게 제품의 최소 단위 |
| 데모 중 라이브 입력 실패 | 데모는 항상 사전 입력 데이터로 시작. 라이브는 슬라이더 조작만 (실패 불가능한 시연) |
| 숫자 오류 | test_stats.py 손계산 대조 + 리허설에서 Insight-P가 결과 화면 수치를 데모 데이터와 교차 확인 |

---

## 7. Stretch Goal: 2라운드 재투표 (착수 조건부)

**4:00 체크포인트에서 코어 전부 작동 시에만 착수.** 설계 요지:
결과 공개 후 [토론 후 재투표] → 쟁점 요약+반론만 보이는 화면(득표 비공개, 앵커링 방지)
→ 프리필 재입력 → Stability before/after 비교. 미착수 시 발표에서 "다음 단계"로만
언급하고, Q&A에서 앵커링 역설(결과를 보여주고 재투표하면 동조를 유발하므로
쟁점만 공개) 답변 카드로 활용.