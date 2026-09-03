export type Agreement = "HIGH" | "MID" | "LOW";

export interface AuthUser {
  google_sub: string;
  email: string;
  name: string;
  picture?: string | null;
}

export interface AuthState {
  authenticated: boolean;
  user: AuthUser | null;
}

export interface AuthConfig {
  enabled: boolean;
  client_id: string | null;
}

export interface Room {
  code: string;
  question: string;
  options: string[];
  criteria: string[];
  context?: string;
  expected_members: number;
  submission_mode: "anonymous" | "named";
  created_at: string;
  expires_at: string;
  participant_names: string[];
  submission_count: number;
  is_complete: boolean;
}

export interface CreateRoomPayload {
  question: string;
  options: string[];
  criteria: string[];
  context?: string;
  expected_members?: number;
  submission_mode?: "anonymous" | "named";
  expires_in_hours?: number;
}

export type CreateRoomResponse = Room;

/** 백엔드 RoomCreate.context / CriteriaSuggestRequest.context 상한과 동일. */
export const CONTEXT_MAX_LENGTH = 50_000;

export interface CriterionSuggestion {
  name: string;
  why: string;
  description: string;
  one_point: string;
  five_point: string;
}

export interface CriteriaSuggestPayload {
  question: string;
  options: string[];
  existing_criteria: string[];
  context: string;
}

export interface CriteriaSuggestResponse {
  criteria: CriterionSuggestion[];
  source: "live" | "fallback";
}

export interface OptionSuggestion {
  name: string;
  why: string;
}

export interface OptionSuggestPayload {
  question: string;
  existing_options: string[];
  context: string;
}

export interface OptionSuggestResponse {
  options: OptionSuggestion[];
  source: "live" | "fallback";
}

export interface AssistantMessage {
  role: "user" | "assistant";
  content: string;
}

export interface DecisionAssistantPayload {
  question: string;
  options: string[];
  criteria: string[];
  context: string;
  messages: AssistantMessage[];
}

export interface DecisionAssistantResponse {
  message: string;
  source: "live" | "fallback";
}

export interface SubmissionPayload {
  participant_name?: string;
  scores: Record<string, Record<string, number>>;
  weights: Record<string, number>;
  first_choice: string;
  reason: string;
}

export interface SubmitResponse {
  id: string;
  submission_count: number;
  expected_members: number;
  is_complete: boolean;
}

export interface WeightFlipPoint {
  type: "weight";
  criterion: string;
  from: number;
  to: number;
  change?: number;
  direction?: "increase" | "decrease";
  proximity?: "nearby" | "theoretical";
  new_winner: string;
}

export interface MemberFlipPoint {
  type: "member";
  description: string;
}

export type FlipPoint = WeightFlipPoint | MemberFlipPoint;

export interface DevilsAdvocate {
  target: string;
  challenges: string[];
}

export interface AnalysisResponse {
  vote_share: Record<string, number>;
  team_weights: Record<string, number>;
  weight_agreement: Record<string, Agreement>;
  score_agreement: Record<string, Record<string, Agreement>>;
  hidden_conflicts: string[];
  stability: Record<string, number>;
  current_winner: string;
  robust_choice: string;
  flip_points: FlipPoint[];
  discussion_agenda: string[];
  devils_advocate?: DevilsAdvocate | null;
  /** 클라이언트 가중치 시뮬레이터용 비파괴 확장 필드. */
  mean_scores?: Record<string, Record<string, number>>;
}

export interface DecisionRecordPayload {
  final_choice: string;
  final_reason: string;
}

export interface DecisionRecord {
  initial_majority_choice: string;
  analysis_winner: string;
  robust_choice: string;
  final_choice: string;
  final_reason: string;
  decided_at: string;
  changed_from_initial: boolean;
}

/** Devil's Advocate 공방 — 백엔드 DebateState 계약(backend/models.py)과 1:1 대응. */
export type DefenseStatus = "mitigated" | "open" | "invalid";
export type ChallengeResolution = "resolved" | "open" | "reframed";
export type DebateSource = "live" | "fallback";

export interface EvidenceSnapshot {
  id: string;
  target: string;
  low_agreement: string[];
  concerns: string[];
  hidden_conflicts: string[];
  discussion_agenda: string[];
}

interface DebateMessageBase {
  sequence: number;
  challenge_id: string;
  evidence_snapshot_id: string;
  evidence_keys: string[];
}

export interface ChallengerQuestion extends DebateMessageBase {
  role: "challenger";
  turn: 1;
  question: string;
}

export interface DefenderMessage extends DebateMessageBase {
  role: "defender";
  turn: 1;
  status: DefenseStatus;
  evidence: string;
  unknowns: string;
  mitigation: string;
}

export interface ChallengerResolutionMessage extends DebateMessageBase {
  role: "challenger";
  turn: 2;
  resolution: ChallengeResolution;
  reason: string;
  reframed_question: string | null;
}

export type DebateMessage = ChallengerQuestion | DefenderMessage | ChallengerResolutionMessage;

export interface DebateState {
  evidence_snapshot: EvidenceSnapshot;
  messages: DebateMessage[];
  completed: boolean;
  challenger_source: DebateSource;
  resolution_source: DebateSource | null;
}

export interface DefenderAnswer {
  challenge_id: string;
  status: DefenseStatus;
  evidence: string;
  unknowns: string;
  mitigation: string;
}

export interface DefenderTurnPayload {
  answers: DefenderAnswer[];
}
