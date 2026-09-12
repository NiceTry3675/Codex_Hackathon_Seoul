# 싱큐 (SynQ) frontend

React + Vite + TypeScript + Tailwind로 만든 싱큐의 SPA 프런트엔드입니다.

- **결정 만들기**: 결정할 질문·선택지·판단 기준을 입력하고 참여 인원과 익명/실명 제출 방식을 설정합니다. 실명 제출 방은 Google 로그인 사용자만 만들 수 있습니다.
- **평가 참여**: 6자리 참여 코드로 들어와 선택지별 점수, 기준 중요도, 현재 선호와 이유를 제출합니다.
- **제출 현황**: 팀원의 제출 완료 여부를 확인하고 분석을 시작합니다.
- **결과 확인**: 현재 평가 1위, 조건별 1위 비율, 평가가 갈린 기준, 결과가 바뀌는 조건과 확인 질문을 봅니다. 논의 후 중요도를 직접 바꿔 계산하고 최종 결정과 근거를 저장합니다.

결정 생성 폼은 빈 입력으로 시작합니다. 로컬 예시 모드에서는 사전 정의된 방과 분석 데이터를 사용합니다. 실제 생성·제출·재계산 검증은 FastAPI에 연결해 수행합니다.

화면 문구와 개발 용어의 대응은 [PRODUCT_LANGUAGE.md](../PRODUCT_LANGUAGE.md)를 따릅니다. 현재 평가 1위와 조건별 계산에서 가장 자주 1위가 된 선택은 서로 다를 수 있습니다.

```bash
npm install
npm run dev
```

기본값은 `src/mock.ts`를 사용하는 mock 모드입니다. 실제 FastAPI와 연결하려면
`.env.example`을 `.env.local`로 복사하고 아래처럼 바꿉니다.

```dotenv
VITE_USE_MOCK_API=false
VITE_API_BASE_URL=
```

- 개발 서버의 `/api` 요청은 `http://localhost:8000`으로 프록시됩니다.
- 배포 시 같은 origin에서 FastAPI가 정적 파일을 서빙하므로 `VITE_API_BASE_URL`은 비워둡니다.
- 결과 화면의 클라이언트 가중치 시뮬레이터는 분석 응답의 `mean_scores`(옵션×기준 평균 점수)를 사용합니다.
- 라우터 없이 `App.tsx`의 `create → submit → waiting → results` 상태로 화면을 전환합니다.
