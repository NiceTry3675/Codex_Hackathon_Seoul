import { useEffect, useState } from "react";
import { api, USE_MOCK_API } from "./api";
import GoogleLoginButton from "./components/GoogleLoginButton";
import { DEFAULT_ROOM_CODE } from "./mock";
import CreateRoomPage from "./pages/CreateRoomPage";
import ResultsPage from "./pages/ResultsPage";
import SubmitPage from "./pages/SubmitPage";
import WaitingPage from "./pages/WaitingPage";
import type {
  AnalysisResponse,
  AuthConfig,
  AuthState,
  CreateRoomPayload,
  Room,
  SubmissionPayload,
} from "./types";

type Stage = "create" | "submit" | "waiting" | "results";

const stages: Array<{ id: Stage; label: string }> = [
  { id: "create", label: "방 만들기" },
  { id: "submit", label: "의견 입력" },
  { id: "waiting", label: "제출 현황" },
  { id: "results", label: "분석 결과" },
];

function App() {
  const [stage, setStage] = useState<Stage>("submit");
  const [room, setRoom] = useState<Room>();
  const [analysis, setAnalysis] = useState<AnalysisResponse>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [authConfig, setAuthConfig] = useState<AuthConfig>();
  const [authState, setAuthState] = useState<AuthState>({ authenticated: false, user: null });
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState("");

  const loadRoom = async (code: string) => {
    setBusy(true);
    setError("");
    try {
      const nextRoom = await api.getRoom(code.trim().toUpperCase());
      setRoom(nextRoom);
      setAnalysis(undefined);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "방 정보를 불러오지 못했습니다.");
      throw cause;
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (USE_MOCK_API) {
      void loadRoom(DEFAULT_ROOM_CODE).catch(() => undefined);
      return;
    }
    void Promise.all([api.getAuthConfig(), api.getAuthState()])
      .then(([config, state]) => {
        setAuthConfig(config);
        setAuthState(state);
      })
      .catch(() => setAuthError("로그인 상태를 확인하지 못했습니다."));
  }, []);

  const loginWithGoogle = async (credential: string) => {
    setAuthBusy(true);
    setAuthError("");
    try {
      setAuthState(await api.loginWithGoogle(credential));
    } catch (cause) {
      setAuthError(cause instanceof Error ? cause.message : "Google 로그인에 실패했습니다.");
    } finally {
      setAuthBusy(false);
    }
  };

  const logout = async () => {
    setAuthBusy(true);
    setAuthError("");
    try {
      await api.logout();
      window.google?.accounts.id.disableAutoSelect();
      setAuthState({ authenticated: false, user: null });
    } catch (cause) {
      setAuthError(cause instanceof Error ? cause.message : "로그아웃하지 못했습니다.");
    } finally {
      setAuthBusy(false);
    }
  };

  const submit = async (payload: SubmissionPayload) => {
    if (!room) return;
    setBusy(true);
    setError("");
    try {
      await api.submitOpinion(room.code, payload);
      const nextRoom = await api.getRoom(room.code);
      setRoom(nextRoom);
      setStage("waiting");
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "의견을 제출하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  };

  const createRoom = async (payload: CreateRoomPayload) => {
    setBusy(true);
    setError("");
    try {
      const nextRoom = await api.createRoom(payload);
      setRoom(nextRoom);
      setAnalysis(undefined);
      setStage("submit");
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "방을 만들지 못했습니다.");
      throw cause;
    } finally {
      setBusy(false);
    }
  };

  const openAnalysis = async () => {
    if (!room) return;
    setBusy(true);
    setError("");
    try {
      const result = analysis ?? (await api.getAnalysis(room.code));
      setAnalysis(result);
      setStage("results");
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "분석 결과를 불러오지 못했습니다.");
    } finally {
      setBusy(false);
    }
  };

  const navigate = (next: Stage) => {
    if (next === "results") {
      if (!room?.is_complete) return;
      void openAnalysis();
      return;
    }
    if (next === "waiting" && !room) return;
    setStage(next);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b border-black/5 bg-[#f8f6f1]/90 backdrop-blur-xl">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-4 sm:flex-nowrap sm:px-6">
          <button className="text-left" type="button" onClick={() => navigate("submit")}>
            <span className="block text-lg font-bold tracking-[-0.04em]">싱큐</span>
            <span className="hidden text-[11px] text-stone-500 sm:block">합의보다, 더 나은 선택.</span>
          </button>

          <nav className="flex items-center rounded-full border border-black/5 bg-white p-1 shadow-sm" aria-label="화면 이동">
            {stages.map((item, index) => (
              (() => {
                const disabled =
                  (item.id === "waiting" && !room) ||
                  (item.id === "results" && !room?.is_complete);
                return (
              <button
                key={item.id}
                type="button"
                onClick={() => navigate(item.id)}
                disabled={disabled}
                className={`rounded-full px-3 py-2 text-xs font-semibold transition sm:px-4 ${
                  stage === item.id
                    ? "bg-ink text-white"
                    : "text-stone-500 hover:text-ink disabled:opacity-30"
                }`}
              >
                <span className="sm:hidden">{index + 1}</span>
                <span className="hidden sm:inline">{item.label}</span>
              </button>
                );
              })()
            ))}
          </nav>

          <div className="order-3 flex w-full min-w-28 justify-end sm:order-none sm:w-auto">
            {USE_MOCK_API ? (
              <span className="rounded-full bg-amber-100 px-3 py-1.5 text-xs font-bold text-amber-800">
                MOCK MODE
              </span>
            ) : authState.authenticated && authState.user ? (
              <div className="flex items-center gap-2 rounded-full border border-black/5 bg-white py-1 pl-2 pr-1 shadow-sm">
                <span
                  className="flex h-7 w-7 items-center justify-center rounded-full bg-moss-100 text-xs font-bold text-moss-700"
                  aria-hidden="true"
                >
                  {authState.user.name.slice(0, 1).toUpperCase()}
                </span>
                <span className="max-w-28 truncate text-xs font-semibold" title={authState.user.email}>
                  {authState.user.name}
                </span>
                <button
                  type="button"
                  onClick={() => void logout()}
                  disabled={authBusy}
                  className="rounded-full px-2.5 py-1.5 text-xs font-semibold text-stone-500 transition hover:bg-stone-100 hover:text-ink disabled:opacity-40"
                >
                  로그아웃
                </button>
              </div>
            ) : authConfig?.enabled && authConfig.client_id ? (
              <GoogleLoginButton
                clientId={authConfig.client_id}
                disabled={authBusy}
                onCredential={loginWithGoogle}
                onLoadError={() => setAuthError("Google 로그인 모듈을 불러오지 못했습니다.")}
              />
            ) : (
              <span className="rounded-full bg-stone-100 px-3 py-1.5 text-xs font-semibold text-stone-500">
                {authConfig ? "Google 로그인 미설정" : "LIVE API"}
              </span>
            )}
          </div>
        </div>
      </header>

      {authError && (
        <div className="mx-auto mt-4 flex max-w-3xl items-start justify-between gap-4 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900" role="status">
          <span>{authError}</span>
          <button type="button" onClick={() => setAuthError("")} aria-label="로그인 오류 닫기" className="font-bold">×</button>
        </div>
      )}

      {error && (
        <div className="mx-auto mt-4 flex max-w-3xl items-start justify-between gap-4 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
          <span>{error}</span>
          <button type="button" onClick={() => setError("")} aria-label="오류 닫기" className="font-bold">×</button>
        </div>
      )}

      <main>
        {stage === "create" && <CreateRoomPage loading={busy} onCreate={createRoom} />}
        {stage === "submit" && (
          <SubmitPage room={room} loading={busy} onJoin={loadRoom} onSubmit={submit} />
        )}
        {stage === "waiting" && room && (
          <WaitingPage
            room={room}
            loading={busy}
            onRoomChange={setRoom}
            onAnalyze={openAnalysis}
          />
        )}
        {stage === "results" && analysis && room && (
          <ResultsPage analysis={analysis} room={room} />
        )}
        {stage === "results" && busy && !analysis && (
          <div className="mx-auto flex min-h-[60vh] max-w-xl items-center justify-center px-4 text-center">
            <div>
              <div className="mx-auto h-10 w-10 animate-spin rounded-full border-4 border-moss-100 border-t-moss-600" />
              <p className="mt-4 font-semibold">결정의 안정성을 계산하고 있어요.</p>
              <p className="mt-1 text-sm text-stone-500">숫자는 통계 엔진이, 쟁점 정리는 AI가 맡습니다.</p>
            </div>
          </div>
        )}
      </main>

      <footer className="mx-auto max-w-6xl px-4 py-10 text-center text-xs text-stone-500 sm:px-6">
        싱큐는 결정을 대신하지 않습니다. 결정이 얼마나 견고한지 보여줍니다.
      </footer>
    </div>
  );
}

export default App;
