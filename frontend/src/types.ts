export type Agreement = "HIGH" | "MID" | "LOW";

export interface Room {
  code: string;
  question: string;
  options: string[];
  criteria: string[];
  expected_members: number;
  submission_mode: "anonymous" | "named";
  participant_names: string[];
  submission_count: number;
  is_complete: boolean;
}

export interface CreateRoomPayload {
  question: string;
  options: string[];
  criteria: string[];
  expected_members?: number;
  submission_mode?: "anonymous" | "named";
}

export type CreateRoomResponse = Room;

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
