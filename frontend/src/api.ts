import { mockApi } from "./mock";
import type {
  AnalysisResponse,
  AuthConfig,
  AuthState,
  CreateRoomPayload,
  CreateRoomResponse,
  CriteriaSuggestPayload,
  CriteriaSuggestResponse,
  DebateState,
  DecisionAssistantPayload,
  DecisionAssistantResponse,
  DecisionRecheck,
  DecisionRecheckPayload,
  DecisionRecord,
  DecisionRecordPayload,
  DefenderTurnPayload,
  OptionSuggestPayload,
  OptionSuggestResponse,
  Room,
  SubmissionPayload,
  SubmitResponse,
} from "./types";

export const USE_MOCK_API = import.meta.env.VITE_USE_MOCK_API !== "false";
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

const API_ERROR_MESSAGES: Readonly<Record<string, string>> = {
  "room not found": "결정을 찾을 수 없습니다. 참여 코드와 만료 여부를 확인해주세요.",
  "room is full": "설정한 인원의 평가가 모두 제출됐습니다. 결과를 확인해주세요.",
  "authentication is required to create named rooms": "실명 제출을 받으려면 먼저 Google 계정으로 로그인해주세요.",
  "participant_name is required for named rooms": "제출자 이름을 입력해주세요.",
  "participant_name must be omitted for anonymous rooms": "익명 제출에서는 이름을 입력하지 않습니다.",
  "a valid room participation token is required": "참여 정보를 확인할 수 없습니다. 참여 코드로 다시 들어와주세요.",
  "this browser already submitted to this room": "이 브라우저에서 이미 평가를 제출했습니다. 제출 현황을 확인해주세요.",
  "participant name already submitted": "같은 이름으로 이미 제출한 평가가 있습니다. 이름을 확인해주세요.",
  "submission conflicted with another request; please retry": "다른 평가가 동시에 제출됐습니다. 잠시 후 다시 제출해주세요.",
  "submission failed": "평가를 제출하지 못했습니다. 잠시 후 다시 시도해주세요.",
  "first_choice must be one of the room options": "현재 선호하는 선택지를 목록에서 골라주세요.",
  "final_choice must be one of the room options": "최종 선택을 목록에서 골라주세요.",
  "scores keys must match the room definition": "현재 결정의 선택지와 판단 기준에 맞게 평가해주세요.",
  "weights keys must match the room definition": "현재 결정의 판단 기준에 맞게 중요도를 입력해주세요.",
  "weights must total 100": "중요도 합계가 100%가 되도록 조정해주세요.",
  "all expected members must submit before analysis": "설정한 인원의 평가가 모두 모이면 결과를 확인할 수 있습니다.",
  "all expected members must submit before recording a decision": "설정한 인원의 평가가 모두 모이면 결정 기록을 저장할 수 있습니다.",
  "decision record not found": "아직 저장한 결정 기록이 없습니다.",
  "decision record already exists": "이미 결정 기록을 저장했습니다. 저장한 기록을 확인해주세요.",
  "decision recheck not found": "아직 논의 후 다시 계산한 결과가 없습니다.",
  "decision recheck already exists": "이미 논의 후 다시 계산한 결과를 저장했습니다.",
  "analysis must be generated before the debate": "팀 결과를 먼저 확인한 뒤 질문에 답변해주세요.",
  "debate is already complete": "이미 답변 검토가 끝났습니다. 제출한 답변은 수정할 수 없습니다.",
  "each challenge_id must be answered once": "각 질문에 하나씩 답변해주세요.",
  "answers must match every challenge_id": "모든 질문에 답변해주세요.",
};

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
    throw new Error(API_ERROR_MESSAGES[message] ?? message);
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

  suggestCriteria(payload: CriteriaSuggestPayload): Promise<CriteriaSuggestResponse> {
    if (USE_MOCK_API) return mockApi.suggestCriteria(payload);
    return request("/api/criteria/suggestions", { method: "POST", body: JSON.stringify(payload) });
  },

  suggestOptions(payload: OptionSuggestPayload): Promise<OptionSuggestResponse> {
    if (USE_MOCK_API) return mockApi.suggestOptions(payload);
    return request("/api/options/suggestions", { method: "POST", body: JSON.stringify(payload) });
  },

  messageAssistant(payload: DecisionAssistantPayload): Promise<DecisionAssistantResponse> {
    if (USE_MOCK_API) return mockApi.messageAssistant(payload);
    return request("/api/assistant/message", { method: "POST", body: JSON.stringify(payload) });
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

  getDecisionRecord(code: string): Promise<DecisionRecord> {
    if (USE_MOCK_API) return mockApi.getDecisionRecord(code);
    return request(`/api/rooms/${encodeURIComponent(code)}/decision-record`);
  },

  createDecisionRecord(code: string, payload: DecisionRecordPayload): Promise<DecisionRecord> {
    if (USE_MOCK_API) return mockApi.createDecisionRecord(code, payload);
    return request(`/api/rooms/${encodeURIComponent(code)}/decision-record`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  getDecisionRecheck(code: string): Promise<DecisionRecheck> {
    if (USE_MOCK_API) return mockApi.getDecisionRecheck(code);
    return request(`/api/rooms/${encodeURIComponent(code)}/decision-record/recheck`);
  },

  createDecisionRecheck(code: string, payload: DecisionRecheckPayload): Promise<DecisionRecheck> {
    if (USE_MOCK_API) return mockApi.createDecisionRecheck(code, payload);
    return request(`/api/rooms/${encodeURIComponent(code)}/decision-record/recheck`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
};
