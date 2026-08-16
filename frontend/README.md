# 싱큐 (SynQ) frontend

React + Vite + TypeScript + Tailwind로 만든 싱큐의 SPA 프런트엔드입니다.

- **방 만들기**: 질문, 선택지, 평가 기준, 참여 인원, 익명/실명 제출 방식을 설정합니다.
- **의견 입력**: 6자리 방 코드로 참여해 선택과 판단 근거를 제출합니다.
- **제출 현황**: 팀원의 제출 완료 여부를 확인하고 분석을 시작합니다.
- **분석 결과**: Hidden Conflict, Decision Stability, Flip Point와 Devil's Advocate 공방을 확인합니다.

방 생성 폼은 빈 상태로 시작하며 각 입력란의 예시 placeholder를 참고해 내용을 입력합니다.

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
