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
const optionB = "B. 팀 의사결정 도구";
const optionC = "C. 회의 요약 도구";

let room: Room = {
  code: DEFAULT_ROOM_CODE,
  question: "6시간 해커톤에서 어떤 아이디어를 만들까요?",
  options: [optionA, optionB, optionC],
  criteria: ["창의성", "구현 가능성", "발표 임팩트"],
  expected_members: 4,
  submission_count: 3,
  is_complete: false,
};

export const MOCK_ANALYSIS: AnalysisResponse = {
  vote_share: {
    [optionA]: 0.75,
    [optionB]: 0.25,
    [optionC]: 0,
  },
  team_weights: {
    창의성: 0.1556,
    "구현 가능성": 0.7111,
    "발표 임팩트": 0.1333,
  },
  weight_agreement: {
    창의성: "HIGH",
    "구현 가능성": "LOW",
    "발표 임팩트": "HIGH",
  },
  score_agreement: {
    [optionA]: { 창의성: "HIGH", "구현 가능성": "LOW", "발표 임팩트": "HIGH" },
    [optionB]: { 창의성: "HIGH", "구현 가능성": "HIGH", "발표 임팩트": "HIGH" },
    [optionC]: { 창의성: "HIGH", "구현 가능성": "HIGH", "발표 임팩트": "HIGH" },
  },
  hidden_conflicts: [
    "A. AI 보안 도구은(는) 1순위 다수 선택이지만 구현 가능성 평가는 크게 갈립니다.",
  ],
  stability: {
    [optionA]: 0.474,
    [optionB]: 0.526,
    [optionC]: 0,
  },
  current_winner: optionA,
  robust_choice: optionB,
  flip_points: [
    {
      type: "weight",
      criterion: "구현 가능성",
      from: 0.7111,
      to: 0.7211,
      new_winner: optionB,
    },
    {
      type: "member",
      description: "1명의 의견을 제외하면 결과가 B. 팀 의사결정 도구(으)로 바뀜",
    },
  ],
  discussion_agenda: [
    "구현 가능성 중요도가 1%p 오르면 B. 팀 의사결정 도구(으)로 바뀝니다. 이 기준을 먼저 논의하세요.",
    "A. AI 보안 도구의 구현 가능성 평가가 갈리는 근거를 확인하세요.",
    "1명의 의견을 제외하면 결과가 B. 팀 의사결정 도구(으)로 바뀜.",
  ],
  devils_advocate: {
    target: optionA,
    challenges: [
      "구현 가능성 우려가 반복되는데, 계획대로 진행되지 않을 때의 대안은 무엇인가요?",
      "발표 임팩트가 기대만큼 나오지 않을 경우에도 이 선택이 설득력 있나요?",
    ],
  },
  mean_scores: {
    [optionA]: { 창의성: 4.75, "구현 가능성": 3.75, "발표 임팩트": 3.75 },
    [optionB]: { 창의성: 2.5, "구현 가능성": 4.75, "발표 임팩트": 1.0 },
    [optionC]: { 창의성: 1.75, "구현 가능성": 2.5, "발표 임팩트": 3.5 },
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
