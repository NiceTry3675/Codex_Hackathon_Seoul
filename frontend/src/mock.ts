import type {
  AnalysisResponse,
  CreateRoomPayload,
  CreateRoomResponse,
  Room,
  SubmissionPayload,
  SubmitResponse,
} from "./types";

export const DEFAULT_ROOM_CODE = "X7K2P9";

const optionA = "A. AI 보안 도구";
const optionB = "B. 의사결정 도구";
const optionC = "C. 회의 요약 에이전트";

let room: Room = {
  code: DEFAULT_ROOM_CODE,
  question: "회의에 무엇을 우선할까요?",
  options: [optionA, optionB, optionC],
  criteria: ["창의성", "구현 가능성", "발표 임팩트"],
  expected_members: 4,
  submission_count: 3,
  is_complete: false,
};

export const MOCK_ANALYSIS: AnalysisResponse = {
  vote_share: {
    [optionA]: 0.5,
    [optionB]: 0.25,
    [optionC]: 0.25,
  },
  team_weights: {
    창의성: 0.54,
    "구현 가능성": 0.24,
    "발표 임팩트": 0.22,
  },
  weight_agreement: {
    창의성: "MID",
    "구현 가능성": "LOW",
    "발표 임팩트": "HIGH",
  },
  score_agreement: {
    [optionA]: { 창의성: "HIGH", "구현 가능성": "LOW", "발표 임팩트": "HIGH" },
    [optionB]: { 창의성: "MID", "구현 가능성": "HIGH", "발표 임팩트": "HIGH" },
    [optionC]: { 창의성: "MID", "구현 가능성": "MID", "발표 임팩트": "MID" },
  },
  hidden_conflicts: [
    "A를 1순위로 고른 팀원이 많지만, 구현 가능성 평가는 크게 갈렸습니다.",
    "구현 가능성의 중요도에 대해서도 팀의 합의가 낮습니다.",
  ],
  stability: {
    [optionA]: 0.39,
    [optionB]: 0.54,
    [optionC]: 0.07,
  },
  current_winner: optionA,
  robust_choice: optionB,
  flip_points: [
    {
      type: "weight",
      criterion: "구현 가능성",
      from: 0.24,
      to: 0.29,
      new_winner: optionB,
    },
    {
      type: "member",
      description: "1명의 평가가 A에서 B로 이동하면 현재 1위가 바뀝니다.",
    },
  ],
  discussion_agenda: [
    "A를 추진하기 위한 최소 조건을 먼저 합의하세요.",
    "구현 가능성에 29% 이상의 비중을 둘지 논의하세요.",
  ],
  devils_advocate: {
    target: optionA,
    challenges: [
      "구현 가능성 우려가 반복되는데, 계획대로 진행되지 않을 때의 대안은 무엇인가요?",
      "발표 임팩트가 기대만큼 나오지 않을 경우에도 이 선택이 설득력 있나요?",
    ],
  },
  mean_scores: {
    [optionA]: { 창의성: 4.8, "구현 가능성": 2.6, "발표 임팩트": 4.7 },
    [optionB]: { 창의성: 4.1, "구현 가능성": 4.5, "발표 임팩트": 4.2 },
    [optionC]: { 창의성: 3.9, "구현 가능성": 4.0, "발표 임팩트": 3.7 },
  },
};

const delay = (ms = 220) => new Promise((resolve) => setTimeout(resolve, ms));

export const mockApi = {
  async createRoom(payload: CreateRoomPayload): Promise<CreateRoomResponse> {
    await delay();
    room = {
      code: DEFAULT_ROOM_CODE,
      question: payload.question,
      options: payload.options,
      criteria: payload.criteria,
      expected_members: payload.expected_members ?? 4,
      submission_count: 0,
      is_complete: false,
    };
    return { ...room };
  },

  async getRoom(code: string): Promise<Room> {
    await delay(120);
    if (code.trim().toUpperCase() !== room.code) {
      throw new Error("방을 찾을 수 없습니다. 코드를 다시 확인해 주세요.");
    }
    return { ...room };
  },

  async submitOpinion(_code: string, _payload: SubmissionPayload): Promise<SubmitResponse> {
    await delay(320);
    room = {
      ...room,
      submission_count: Math.min(room.expected_members, room.submission_count + 1),
      is_complete: room.submission_count + 1 >= room.expected_members,
    };
    return {
      id: crypto.randomUUID(),
      submission_count: room.submission_count,
      expected_members: room.expected_members,
      is_complete: room.is_complete,
    };
  },

  async getAnalysis(_code: string): Promise<AnalysisResponse> {
    await delay(500);
    return structuredClone(MOCK_ANALYSIS);
  },
};
