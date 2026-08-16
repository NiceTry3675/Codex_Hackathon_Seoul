# Consensus frontend

React + Vite + TypeScript + Tailwind로 만든 3화면 MVP 골격입니다.

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
- 라우터 없이 `App.tsx`의 `submit → waiting → results` 상태로만 화면을 전환합니다.
