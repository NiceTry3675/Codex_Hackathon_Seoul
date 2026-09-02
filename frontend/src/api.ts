import { mockApi } from "./mock";
import type {
  AnalysisResponse,
  AuthConfig,
  AuthState,
  CreateRoomPayload,
  CreateRoomResponse,
  DebateState,
  DefenderTurnPayload,
  Room,
  SubmissionPayload,
  SubmitResponse,
} from "./types";

export const USE_MOCK_API = import.meta.env.VITE_USE_MOCK_API !== "false";
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

/** FastAPI의 detail은 문자열, pydantic 오류 배열, 또는 {message, missing, unexpected} 객체다. */
function formatDetail(detail: unknown): string | undefined {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const lines = detail
      .map((item: { loc?: unknown[]; msg?: string }) => {
        const field = (item.loc ?? []).filter((part) => part !== "body").join(".");
        return field ? `${field}: ${item.msg ?? ""}` : item.msg ?? "";
      })
      .filter(Boolean);
    if (lines.length) return lines.join("\n");
  }
  if (detail && typeof detail === "object" && "message" in detail) {
    return String((detail as { message: unknown }).message);
  }
  return undefined;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let message = "요청을 처리하지 못했습니다.";
    try {
      const body = (await response.json()) as { detail?: unknown };
      message = formatDetail(body.detail) ?? message;
    } catch {
      // JSON 오류 본문이 아니면 기본 메시지를 사용한다.
    }
    throw new Error(message);
  }

  return response.json() as Promise<T>;
}

export const api = {
  getAuthConfig(): Promise<AuthConfig> {
    return request("/api/auth/config");
  },

  getAuthState(): Promise<AuthState> {
    return request("/api/auth/me");
  },

  loginWithGoogle(credential: string): Promise<AuthState> {
    return request("/api/auth/google", {
      method: "POST",
      body: JSON.stringify({ credential }),
    });
  },

  logout(): Promise<{ ok: true }> {
    return request("/api/auth/logout", { method: "POST" });
  },

  createRoom(payload: CreateRoomPayload): Promise<CreateRoomResponse> {
    if (USE_MOCK_API) return mockApi.createRoom(payload);
    return request("/api/rooms", { method: "POST", body: JSON.stringify(payload) });
  },

  getRoom(code: string): Promise<Room> {
    if (USE_MOCK_API) return mockApi.getRoom(code);
    return request(`/api/rooms/${encodeURIComponent(code)}`);
  },

  submitOpinion(code: string, payload: SubmissionPayload): Promise<SubmitResponse> {
    if (USE_MOCK_API) return mockApi.submitOpinion(code, payload);
    return request(`/api/rooms/${encodeURIComponent(code)}/submit`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  getAnalysis(code: string): Promise<AnalysisResponse> {
    if (USE_MOCK_API) return mockApi.getAnalysis(code);
    return request(`/api/rooms/${encodeURIComponent(code)}/analysis`);
  },

  getDebate(code: string): Promise<DebateState> {
    if (USE_MOCK_API) return mockApi.getDebate(code);
    return request(`/api/rooms/${encodeURIComponent(code)}/debate`);
  },

  defendDecision(code: string, payload: DefenderTurnPayload): Promise<DebateState> {
    if (USE_MOCK_API) return mockApi.defendDecision(code, payload);
    return request(`/api/rooms/${encodeURIComponent(code)}/debate/defend`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
};
