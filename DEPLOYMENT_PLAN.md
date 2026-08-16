# Consensus AWS Deployment Plan — Insight-D

> 상태 기준: 2026-08-16. App Runner, ECR, DynamoDB와 전용 IAM 역할이 생성되어 운영 중이다.
> 목표: 단일 Docker 이미지 → Private ECR → AWS App Runner, 인스턴스 1개 고정.

## 1. 현재 상태와 배포 차단 요인

### 확인 완료

- AWS CLI 인증 성공, 현재 기본 리전은 `us-east-1`.
- `us-east-1`과 `ap-northeast-1`에서 App Runner API 접근 가능.
- ECR 저장소, App Runner 서비스, App Runner용 IAM 역할은 아직 없음.
- 프론트 production build 성공.
- 백엔드/API 테스트와 데모 계약·동시성 회귀 테스트가 로컬에서 통과한다.
- Dockerfile은 React 빌드 + FastAPI 런타임의 2-stage 단일 컨테이너 구조이며 `/api/health`가 있음.

### 배포 전 반드시 해결

1. **현재 AWS CLI 주체가 계정 root ARN이다.** 해커톤 배포에 root를 사용하기로 명시적으로 확정했으므로 작업 범위를 이 서비스 리소스로 제한하고 실행 전후 대상 ARN을 확인한다.
2. **해결 완료:** Docker CLI와 Colima 런타임을 설치·기동했고 전체
   `./scripts/release_gate.sh`가 이미지 build, 컨테이너 health, LIVE API 번들,
   HTTP 데모 계약까지 통과했다.
3. **해결 완료:** Dockerfile의 frontend build 단계가 `VITE_USE_MOCK_API=false`, 빈 `VITE_API_BASE_URL`로 live API 번들을 만든다. 릴리스 게이트에서 번들의 `LIVE API` 표시를 재검증한다.
4. `.env`의 `OPENAI_API_KEY` 존재를 값 노출 없이 확인한다.
5. Google 로그인 사용 시 `GOOGLE_CLIENT_ID`, 32자 이상의 `SESSION_SECRET`,
   `SESSION_COOKIE_SECURE=true`를 런타임 환경변수로 설정한다. Google OAuth 승인된
   JavaScript 원본에는 최종 HTTPS 서비스 원본을 등록한다.

## 2. 권장 결정안

| 항목 | 권장안 | 이유 |
|---|---|---|
| 런타임 | App Runner | HTTPS와 운영 부담이 가장 작고 SPEC의 기본 경로와 일치 |
| 리전 | `ap-northeast-1` (Tokyo) | 서울 발표장에서 지연이 낮음. Seoul은 App Runner endpoint가 없고, 단기 데모라 US 대비 비용 차이는 작음 |
| 이미지 저장소 | Private ECR, scan-on-push, immutable tag | 이미지 추적과 롤백이 쉬움 |
| 이미지 태그 | Git SHA (`consensus:<sha>`) | `latest` 덮어쓰기 방지, 직전 정상 이미지로 즉시 롤백 가능 |
| 자동 배포 | `main` → GitHub Actions → ECR `deploy` → App Runner | 반복 수동 배포를 없애고, 발표 30분 전에는 `main` push를 동결 |
| 인스턴스 | 1 vCPU / 2 GB, min=1, max=1 | DynamoDB 영속화 후에도 데모 비용과 동작 예측성을 위해 1개 유지 |
| room 저장소 | DynamoDB `consensus-rooms`, on-demand | App Runner 교체·재시작 후에도 방과 제출을 유지 |
| 상태 확인 | HTTP `/api/health`, port `8080` | 애플리케이션 준비 상태를 직접 확인 |
| OpenAI 키 | App Runner 평문 runtime environment variable | 해커톤 속도를 위해 사용자가 확정; 저장소·이미지·CLI 로그에는 넣지 않음 |
| OpenAI 모델 | `gpt-5.6-sol` | 최종 데모용 고정 모델 ID |
| 배포 권한 | 현재 AWS root CLI 세션 | 사용자가 확정한 단기 해커톤 운영 방식 |
| EC2 폴백 | `EC2_FALLBACK.md` runbook만 준비 | 인스턴스는 App Runner 실패 시에만 생성 |

Tokyo App Runner의 공개 단가는 provisioned memory `$0.009/GB-hour`, active CPU
`$0.081/vCPU-hour`이다. 1 vCPU/2 GB 서비스를 6시간 유지하고 그중 1시간을 active로
가정하면 App Runner compute는 약 `$0.19`이며, ECR 저장·전송·OpenAI 사용료는 별도다.
N. Virginia의 같은 가정은 약 `$0.15`라서 단기 데모에서는 지연시간을 우선하는 편이 낫다.

## 3. 실행 순서와 체크포인트

### Phase 0 — 배포 주체와 대상 확인 (5분)

1. `aws sts get-caller-identity`에서 확정된 계정의 root ARN인지 확인한다.
2. 리전을 모든 명령에서 `ap-northeast-1`로 명시한다.
3. 생성 대상 이름을 `consensus`, `consensus-demo`, `ConsensusAppRunnerEcrAccessRole`로 제한한다.
4. `.env`는 Git과 Docker build context에서 제외된 상태로 유지한다.

**통과 조건:** 대상 계정·리전이 맞고 `.env`가 `git check-ignore`와 `.dockerignore` 양쪽에서 제외된다.

### Phase 1 — 로컬 release gate (15분)

1. Colima가 실행 중인지 `colima status`와 `docker info`로 확인.
2. Dockerfile frontend build 단계에 live API 빌드 환경을 설정.
3. 아래 원커맨드 릴리스 게이트를 통과시킨다.

```bash
./scripts/release_gate.sh
```

4. 브라우저 헤더가 `LIVE API`인지 확인한다. `MOCK MODE`면 배포 중단.
5. 릴리스 게이트가 로컬 컨테이너에 데모 데이터를 적재하고 current A, robust B,
   stability 47.4%/52.6%, 구현 가능성 1%p flip, Devil's Advocate 결과를 자동 검증한다.

**통과 조건:** 테스트, 이미지 빌드, health, live API 데모 적재가 모두 성공한다.

### Phase 2 — AWS 파이프라인 canary (20~30분, 2:00 이전)

1. 선택 리전에 `consensus` ECR 저장소를 만든다.
   - tag immutability: `IMMUTABLE`
   - scan on push: `true`
2. 현재 Git SHA로 이미지 태그를 만들고 ECR에 push한다.
3. App Runner가 private ECR 이미지를 읽는 access role을 만든다.
   - trust principal: `build.apprunner.amazonaws.com`
   - managed policy: `AWSAppRunnerServicePolicyForECRAccess`
4. `.env`에서 읽은 값을 출력하지 않고 App Runner plain-text runtime environment variable로 주입한다.
   - `OPENAI_API_KEY`: 실제 키
   - `OPENAI_MODEL`: `gpt-5.6-sol`
   - `OPENAI_TIMEOUT_SECONDS`: `60`
   - `CONSENSUS_TABLE_NAME`: `consensus-rooms`
   - `GOOGLE_CLIENT_ID`: Google OAuth 웹 Client ID
   - `SESSION_SECRET`: 운영용 무작위 값(최소 32자)
   - `SESSION_COOKIE_SECURE`: `true`
   - 키를 tracked 파일, 이미지 layer, shell history, 로그에 기록하지 않는다.
5. autoscaling config를 `MinSize=1`, `MaxSize=1`로 생성한다.
6. App Runner service `consensus-demo`를 생성한다.
   - ECR image: Git SHA tag
   - auto deployments: off
   - port: `8080`
   - health check: HTTP `/api/health`
   - CPU/memory: 1 vCPU / 2 GB
   - OpenAI 키와 모델을 plain-text runtime environment variables로 설정

**통과 조건:** service가 `RUNNING`, HTTPS health가 200, 루트 화면이 `LIVE API`.

**2:00 중단 규칙:** IAM/ECR/App Runner 문제를 20분 안에 해소하지 못하면 더 파고들지 말고 Phase 6의 EC2 폴백으로 전환한다.

### Phase 3 — 최종 이미지 자동 배포 (통합 완료 직후)

1. `main`에 push하면 GitHub Actions가 OIDC 임시 자격 증명으로 로그인한다. 장기 AWS access key는 GitHub에 저장하지 않는다.
2. Actions가 Docker 이미지를 build하고 ECR의 mutable `deploy` 태그를 갱신한다.
3. 같은 manifest를 immutable Git SHA 태그로 보존해 롤백 지점을 만든다.
4. App Runner가 `deploy` 태그 변경을 감지해 자동 배포한다.
5. service가 `RUNNING`이 되고 health가 안정될 때까지 기다린다.
6. ECR 이미지 scan 결과에 critical/high 취약점이 있는지 확인한다.

GitHub OIDC 역할은 `NiceTry3675/Codex_Hackathon_Seoul` 저장소의 `main` 브랜치만 신뢰하며,
ECR push에 필요한 최소 권한만 가진다. ECR은 `deploy` 태그만 mutable이고 나머지 SHA 태그는 immutable이다.

**롤백:** 직전 정상 SHA로 App Runner source image를 되돌린다. room은 DynamoDB에 유지되지만 스키마 호환성을 확인하고 필요하면 데모 데이터를 다시 적재한다.

### Phase 4 — 배포본 E2E 및 데모 데이터 적재 (20분)

```bash
curl --fail https://SERVICE_URL/api/health
.venv/bin/python scripts/load_demo.py --base-url https://SERVICE_URL
```

다음 항목을 기록한다.

- 생성된 6자리 room code
- `/analysis` 전체 응답 JSON
- current winner, robust choice, stability, 첫 weight flip point
- Devil's Advocate가 live 응답인지 fallback/없음인지
- 모바일 2대에서 같은 room 조회와 3초 polling 동작
- 결과 화면의 live slider로 예상 지점에서 순위가 바뀌는지

**수용 기준:** health 200, 4명 제출, 분석 200, 결과 화면 수치와 API JSON 일치, `LIVE API` 표시, 새로고침/다른 기기 접근 성공.

### Phase 5 — 발표 freeze와 관찰 (발표 30분 전)

1. 최종 배포 후 `main` push를 중단해 코드/이미지 변경을 금지한다.
2. 마지막 배포 뒤 데모 room을 새로 만들고 room code와 결과 URL을 팀에 공유한다.
3. 리허설 2회 동안 App Runner 상태와 CloudWatch application/service logs를 확인한다.
4. 네트워크/GPT 실패에 대비해 분석 JSON과 결과 화면 캡처를 로컬에 보관한다.
5. 발표 직전 health를 한 번만 확인하고 데모 room을 재사용한다.

### Phase 6 — EC2 폴백

App Runner 실패 시 `t3.small` 1대와 기본 public subnet을 사용한다. 현재 권장 리전인
`ap-northeast-1`과 기본 리전인 `us-east-1` 모두 default VPC/public subnet이 있지만
EC2 key pair는 없다.

사전 준비:

- `EC2_FALLBACK.md`의 SSM 접속 경로를 사용하고 key pair는 만들지 않음
- 보안 그룹은 HTTP 80만 공개하고 SSH 22는 열지 않음
- instance role에는 SSM과 ECR pull 권한만 부여
- user-data로 Docker 설치 → ECR login/pull → `docker run -p 80:8080`

HTTPS 설정이 15분 안에 끝나지 않으면 발표용으로 HTTP URL을 우선 확보하고, App Runner 복구를 병행하지 않는다.

## 4. 데모 운영 리스크

- App Runner 배포/업데이트가 컨테이너를 교체해도 DynamoDB의 room 데이터는 유지된다.
- App Runner는 배포 중 일시적으로 용량을 추가할 수 있다. 발표 중 배포하지 않는다.
- `OPENAI_API_KEY`가 없어도 핵심 통계 경로는 동작한다. GPT 장애 때문에 배포를 되돌리지 않는다.
- mock build는 E2E 성공처럼 보일 수 있으므로 화면의 `LIVE API` 배지를 필수 검증한다.
- room은 DynamoDB에 저장하며 App Runner min/max instance는 데모 운영 정책상 1로 고정한다.

## 5. 종료 후 정리

발표 종료 후 24시간 유지한다. 필요한 URL·로그·분석 JSON을 보관한 뒤 App Runner service,
DynamoDB table, ECR images/repository, autoscaling configuration, 전용 ECR access/instance role, 생성된 EC2 fallback
자원을 제거한다. 사용자가 확정한 정책에 따라 OpenAI API 키 자체는 폐기하거나 교체하지 않는다.

## 6. 확정된 사용자 결정

1. 배포 리전: Tokyo(`ap-northeast-1`).
2. 배포 주체: 현재 AWS root CLI 세션.
3. OpenAI: `gpt-5.6-sol`, App Runner 평문 환경변수.
4. EC2: runbook만 사전 준비.
5. 서비스 유지: 발표 후 24시간.
6. OpenAI 키: 발표 후에도 폐기·교체하지 않음.
