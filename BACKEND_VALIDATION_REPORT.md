# 백엔드 종합 검증 보고서

- 검증일: 2026-08-16 (KST)
- 기준 브랜치: `main`
- 기준 커밋: `61ecb0eb5e204b0af9654a8b3509cffc273e1ad1`
- 검증 대상: FastAPI API, 입력 모델, 통계 연동, Google 인증 경계, 메모리/DynamoDB 저장 경계, 선택적 LLM 장애 격리, Docker 배포 이미지
- 최종 결과: **PASS — 자동화 테스트 84개 및 Docker 릴리스 게이트 통과**

## 1. 요약

원격 최신 기준선의 기존 46개 테스트에 백엔드 경계·공격·장애 케이스 38개를 추가했다. 확장 테스트의 최초 실행에서 결함 2종(실패 테스트 3개)을 발견했고 수정 후 신규 38개와 전체 84개가 모두 통과했다.

치명적 또는 높은 우선순위의 미해결 런타임 오류는 이번 로컬 검증 범위에서 발견되지 않았다. 다만 실제 OpenAI, Google, AWS 계정이 필요한 통합 검증은 로컬 대체 테스트만 수행했으므로 배포 환경에서 별도 확인해야 한다.

## 2. 실행 결과

| 검증 | 명령/경로 | 결과 |
|---|---|---|
| 기존 기준선 | `.venv/bin/python -m pytest -q --ignore=backend/tests/test_backend_validation.py` | `46 passed` |
| 신규 백엔드 확장 테스트 | `.venv/bin/python -m pytest -q backend/tests/test_backend_validation.py` | `38 passed` |
| 전체 회귀 테스트 | `.venv/bin/python -m pytest -q` | `84 passed` |
| Python 컴파일 | `.venv/bin/python -m compileall -q backend scripts` | PASS |
| Python 의존성 무결성 | `.venv/bin/python -m pip check` | `No broken requirements found` |
| diff 형식 검사 | `git diff --check` | PASS |
| 프런트 프로덕션 빌드 | `tsc -b && vite build` | PASS, 34 modules |
| Docker 이미지 빌드 | `consensus:release-gate` | PASS |
| 컨테이너 헬스체크 | `GET /api/health` | PASS |
| 컨테이너 LIVE API 번들 검사 | `scripts/release_gate.sh` 6단계 | PASS |
| 실제 HTTP 데모 계약 | `scripts/load_demo.py` + `scripts/check_demo_result.py` | PASS |
| OpenAI 실호출 스모크 | `scripts/smoke_openai.py` | SKIP — 로컬 키 없음 |

Docker 내부 데모 계약의 대표 결과는 `current=A`, `robust=B`, Stability `47.4/52.6`, 최소 flip point `1%p`였으며 계약 검사에 통과했다.

## 3. 추가한 테스트 케이스

### 3.1 방 생성 입력 경계

다음 14개 잘못된 입력이 모두 `422`를 반환하고 방 상태를 생성하지 않는지 확인했다.

- 빈 본문, 정의되지 않은 추가 필드
- 공백 질문
- 옵션 1개 또는 11개
- trim 후 중복 옵션, 공백 옵션
- 기준 0개 또는 11개
- 예상 인원 0명 또는 101명
- 허용하지 않는 제출 모드
- 200자를 초과하는 옵션 또는 기준 라벨

### 3.2 방 코드 경계

5자, 7자, 특수문자가 포함된 코드를 조회·제출·분석 API에 각각 전달했을 때 모두 `422`로 차단되는지 확인했다. 존재하지 않는 정상 형식의 방에 대한 제출은 `404`를 반환했다.

### 3.3 제출 스키마와 상태 보존

다음 13개 잘못된 제출이 모두 `422`를 반환하며 제출 슬롯을 소비하지 않는지 확인했다.

- `scores` 누락
- 옵션 누락 또는 알 수 없는 옵션 추가
- 옵션별 기준 누락
- 알 수 없는 가중치 기준 추가
- 점수 범위 `0`, `6`
- 가중치 범위 `0`, `11`
- 존재하지 않거나 공백인 `first_choice`
- 2,000자를 초과하는 `reason`
- 정의되지 않은 추가 필드

추가로 실명 방의 동일 참가자명 중복 제출은 첫 요청만 `201`, 두 번째는 `409`이며 제출 수가 1로 유지되는지 검증했다.

### 3.4 통계와 공격 입력

- 완전 동점 데이터를 반복 분석해 옵션 순서상 첫 항목 `A`가 항상 승자가 되는지 확인
- 동일 데이터의 전체 분석 JSON이 반복 요청에서 동일한지 확인
- `vote_share`, `team_weights`, `option_scores`, `stability`가 모두 유한수인지 확인
- Stability 합이 1인지 확인
- 프롬프트 인젝션 sentinel이 점수 기반 승자를 `B`로 바꾸지 못하는지 확인
- 원본 공격 문자열이 방 조회 또는 분석 응답에 반사되지 않는지 확인
- Devil's Advocate 생성이 반복·동시 호출에서 한 번만 수행되고 캐시되는 기존 테스트 재확인
- 동시 최종 제출이 정원을 초과하지 않는 기존 테스트 재확인

### 3.5 인증 경계

- Google 검증 서비스 장애를 `503`으로 변환하고 세션 쿠키를 만들지 않는지 확인
- `SESSION_COOKIE_SECURE=true`일 때 `Secure` 속성이 설정되는지 확인
- 세션 TTL이 최소 300초, 최대 30일로 제한되는지 확인
- 잘못된 TTL 문자열은 기본 7일로 복구되는지 확인
- 기존 테스트로 잘못된 Google 토큰, 미검증 이메일, 세션 변조·만료, 로그아웃을 재확인

### 3.6 저장소 경계

- 인메모리 저장소의 생성·충돌·대소문자 무시 조회 재확인
- 가짜 DynamoDB 테이블로 조건부 생성, 코드 충돌, consistent read, 저장 후 재조회, 미존재 조회 검증
- 실제 제출/분석 흐름의 저장 호출을 전체 API 회귀 테스트로 확인

### 3.7 배포 이미지

- Node 빌드 단계와 Python 3.12 런타임 단계가 포함된 Docker 이미지 생성
- 임의 로컬 포트로 컨테이너 실행 후 헬스체크
- 정적 SPA가 MOCK MODE가 아닌 LIVE API 번들인지 확인
- 컨테이너 HTTP API에 `demo_data.json` 전체를 제출하고 결과 계약 확인

## 4. 발견 및 수정한 결함

### F-01. 선택적 LLM 파서의 예상 밖 예외가 제출 전체를 중단

- 최초 결과: FAIL, 처리되지 않은 `RuntimeError`가 API 밖으로 전파됨
- 영향: OpenAI 어댑터 내부에서 예상하지 못한 오류가 발생하면 핵심 제출 경로가 5xx로 실패할 수 있음
- 수정: `backend/main.py`에서 의견 구조화 호출을 예외 격리하고 `parsed=None`으로 제출 지속
- 회귀 테스트: `test_unexpected_optional_llm_failure_does_not_break_submission`
- 최종 결과: PASS

이 수정은 공격자 프롬프트 명세나 `backend/llm.py` 구현을 변경하지 않는다. 선택 기능 실패가 핵심 숫자·제출 경로에 영향을 주지 않도록 API 경계만 보강했다.

### F-02. 방 라벨 길이 무제한

- 최초 결과: FAIL, 201자의 옵션·기준 라벨로 방 생성 가능
- 영향: `first_choice` 최대 길이 200자와 계약이 어긋나며, 과도하게 큰 중첩 제출 키를 만들 수 있음
- 수정: `backend/models.py`에서 옵션·기준 라벨을 각각 최대 200자로 제한
- 회귀 테스트: `option-label-too-long`, `criterion-label-too-long`
- 최종 결과: PASS

## 5. 문서 계약 불일치

### D-01. 1명만 제출한 4명 방의 부분 분석

`scenario/01_공격자_시나리오.md`의 A-04는 `expected_members=4`인 방에 1명만 제출한 뒤 분석이 `200`이라고 적혀 있다. 현재 API와 기존 테스트는 전원 제출 전 분석을 `409 all expected members must submit before analysis`로 일관되게 차단한다.

이번 검증에서는 현재 제품 흐름과 기존 API 계약을 유지해 `409`를 정상 동작으로 판정했다. 부분 분석을 허용할지 여부는 통계·프런트·백엔드가 함께 결정하고 시나리오 문서를 갱신해야 한다.

### D-02. LLM 실패 시 Devil's Advocate 처리

SPEC §6은 실패 시 필드를 생략한다고 설명하지만 현재 구현은 결정적 fallback 질문을 생성해 캐시한다. 런타임은 안정적이고 테스트도 통과하지만, 발표 문구와 API 계약은 `생략` 또는 `fallback 제공` 중 하나로 통일하는 편이 좋다.

### D-03. 공격 시나리오의 과거 테스트 수

공격 시나리오 문서의 `13 passed`는 현재 테스트 수와 맞지 않는다. 이번 검증 기준 전체 결과는 `84 passed`이다. 해당 문서는 담당자 작업과 충돌하지 않도록 이번 변경에서 직접 수정하지 않았다.

## 6. 남은 리스크와 배포 후 확인 항목

| 우선순위 | 항목 | 현재 검증 | 권장 확인 |
|---|---|---|---|
| 높음 | 다중 인스턴스 DynamoDB 제출 경쟁 | 단일 프로세스 lock과 가짜 테이블만 검증 | App Runner 인스턴스를 1로 유지하거나 조건부 원자 업데이트 도입 |
| 높음 | 실제 OpenAI adversarial 출력 | 키가 없어 실호출 생략 | 배포 환경에서 `scripts/smoke_openai.py` 및 인젝션 케이스 1회 실행 |
| 중간 | 실제 Google ID 토큰 검증 | verifier mock과 서명 세션 단위 테스트 | 등록된 운영 origin에서 로그인·로그아웃·만료 E2E |
| 중간 | 실제 DynamoDB/IAM | 로컬 fake table 계약 테스트 | 운영 테이블 create/get/save와 재시작 후 방 복구 확인 |
| 중간 | 공개 방 코드 brute force/요청 남용 | 입력 형식만 검증, rate limit 없음 | API Gateway/WAF 또는 앱 rate limit과 관측 로그 추가 |
| 낮음 | 헬스체크 깊이 | 프로세스 `/api/health`만 확인 | 필요 시 DynamoDB 의존성 readiness를 별도 엔드포인트로 분리 |
| 낮음 | 테스트 클라이언트 deprecation 경고 | 기능 영향 없음 | FastAPI/Starlette 권장 버전에 맞춰 테스트 의존성 갱신 |
| 낮음 | Docker legacy builder 경고 | 이미지 빌드 성공 | CI에 Docker Buildx 활성화 |

## 7. 최종 판정

현재 변경분은 로컬 단위·통합·컨테이너 검증을 모두 통과했으며, 발견된 백엔드 결함 2종은 회귀 테스트와 함께 수정되었다. **단일 인스턴스 배포 및 외부 서비스 설정이 올바르다는 전제에서 데모 진행 가능 상태**다.

배포 승인 전 최소 확인 항목은 다음 세 가지다.

1. 운영 origin에서 Google 로그인 1회
2. 실제 DynamoDB에 방 생성·제출 후 컨테이너 재시작 및 재조회
3. 서버에 `OPENAI_API_KEY` 주입 후 OpenAI smoke와 인젝션 케이스 1회
