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
      if (typeof body.detail === "string") {
        message = body.detail;
      } else if (body.detail) {
        message = JSON.stringify(body.detail);
      }
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
