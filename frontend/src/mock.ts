import type {
  AnalysisResponse,
  ChallengerQuestion,
  ChallengerResolutionMessage,
  CreateRoomPayload,
  CreateRoomResponse,
  CriteriaSuggestPayload,
  CriteriaSuggestResponse,
  DebateState,
  DefenderMessage,
  DefenderTurnPayload,
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
  context: "",
  expected_members: 4,
  submission_mode: "anonymous",
  participant_names: [],
  submission_count: 3,
  is_complete: false,
};

const MOCK_CRITERIA_SUGGESTIONS = [
  { name: "사용자 가치", why: "심사위원이 아니라 실제 사용자가 왜 쓰는지 설명할 수 있는지 봅니다." },
  { name: "기술 리스크", why: "제한 시간 안에 막힐 수 있는 기술 요소가 얼마나 많은지 확인합니다." },
  { name: "차별성", why: "비슷한 도구와 비교했을 때 한 문장으로 다른 점을 말할 수 있는지 봅니다." },
  { name: "확장 가능성", why: "해커톤 이후에도 이어서 발전시킬 여지가 있는지 따집니다." },
  { name: "구현 가능성", why: "네 명이 남은 시간 안에 실제로 만들 수 있는지 봅니다." },
];

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

const EVIDENCE_KEYS = ["target", "low_agreement", "concerns", "hidden_conflicts", "discussion_agenda"];
const MOCK_SNAPSHOT_ID = "snapshot-mock0000000000";

function createMockDebate(): DebateState {
  const challenges = MOCK_ANALYSIS.devils_advocate?.challenges ?? [];
  return {
    evidence_snapshot: {
      id: MOCK_SNAPSHOT_ID,
      target: optionA,
      low_agreement: ["구현 가능성", `${optionA} / 구현 가능성`],
      concerns: ["구현 가능성", "구현 가능성", "구현 가능성"],
      hidden_conflicts: [...MOCK_ANALYSIS.hidden_conflicts],
      discussion_agenda: [...MOCK_ANALYSIS.discussion_agenda],
    },
    messages: challenges.map<ChallengerQuestion>((question, index) => ({
      sequence: index + 1,
      challenge_id: `c${index + 1}`,
      turn: 1,
      role: "challenger",
      evidence_snapshot_id: MOCK_SNAPSHOT_ID,
      evidence_keys: [...EVIDENCE_KEYS],
      question,
    })),
    completed: false,
    challenger_source: "fallback",
    resolution_source: null,
  };
}

let debate: DebateState = createMockDebate();

/** 백엔드 project_open_agenda와 동일하게 open/reframed 질문만 안건으로 투영한다. */
function projectOpenAgenda(state: DebateState): string[] {
  if (!state.completed) return [];
  const questions = new Map(
    state.messages
      .filter((message): message is ChallengerQuestion => message.role === "challenger" && message.turn === 1)
      .map((message) => [message.challenge_id, message.question]),
  );
  return state.messages
    .filter((message): message is ChallengerResolutionMessage => message.role === "challenger" && message.turn === 2)
    .flatMap((message) => {
      if (message.resolution === "open") return [questions.get(message.challenge_id) ?? ""];
      if (message.resolution === "reframed" && message.reframed_question) return [message.reframed_question];
      return [];
    })
    .filter(Boolean);
}

export const mockApi = {
  async suggestCriteria(payload: CriteriaSuggestPayload): Promise<CriteriaSuggestResponse> {
    await delay(700);
    const existing = new Set(payload.existing_criteria.map((item) => item.replace(/\s+/g, "")));
    return {
      criteria: MOCK_CRITERIA_SUGGESTIONS.filter((item) => !existing.has(item.name.replace(/\s+/g, ""))),
      source: "fallback",
    };
  },

  async createRoom(payload: CreateRoomPayload): Promise<CreateRoomResponse> {
    await delay();
    debate = createMockDebate();
    room = {
      code: DEFAULT_ROOM_CODE,
      question: payload.question,
      options: payload.options,
      criteria: payload.criteria,
      context: payload.context ?? "",
      expected_members: payload.expected_members ?? 4,
      submission_mode: payload.submission_mode ?? "anonymous",
      participant_names: [],
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
      participant_names:
        room.submission_mode === "named" && _payload.participant_name
          ? [...room.participant_names, _payload.participant_name]
          : room.participant_names,
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
    const analysis = structuredClone(MOCK_ANALYSIS);
    for (const item of projectOpenAgenda(debate)) {
      if (!analysis.discussion_agenda.includes(item)) analysis.discussion_agenda.push(item);
    }
    return analysis;
  },

  async getDebate(_code: string): Promise<DebateState> {
    await delay(200);
    return structuredClone(debate);
  },

  async defendDecision(_code: string, payload: DefenderTurnPayload): Promise<DebateState> {
    await delay(900);
    if (debate.completed) throw new Error("debate is already complete");
    const questions = debate.messages.filter(
      (message): message is ChallengerQuestion => message.role === "challenger" && message.turn === 1,
    );
    const expected = new Set(questions.map((question) => question.challenge_id));
    const actual = payload.answers.map((answer) => answer.challenge_id);
    if (actual.length !== new Set(actual).size || actual.some((id) => !expected.has(id)) || actual.length !== expected.size) {
      throw new Error("answers must match every challenge_id");
    }

    const next = structuredClone(debate);
    const answerById = new Map(payload.answers.map((answer) => [answer.challenge_id, answer]));
    for (const question of questions) {
      const answer = answerById.get(question.challenge_id)!;
      next.messages.push({
        sequence: next.messages.length + 1,
        turn: 1,
        role: "defender",
        challenge_id: question.challenge_id,
        evidence_snapshot_id: MOCK_SNAPSHOT_ID,
        evidence_keys: [...EVIDENCE_KEYS],
        status: answer.status,
        evidence: answer.evidence,
        unknowns: answer.unknowns,
        mitigation: answer.mitigation,
      } satisfies DefenderMessage);
    }
    for (const question of questions) {
      const answer = answerById.get(question.challenge_id)!;
      const hasEvidence = answer.evidence.trim().length > 0 && answer.mitigation.trim().length > 0;
      const verdict: ChallengerResolutionMessage = {
        sequence: next.messages.length + 1,
        turn: 2,
        role: "challenger",
        challenge_id: question.challenge_id,
        evidence_snapshot_id: MOCK_SNAPSHOT_ID,
        evidence_keys: [...EVIDENCE_KEYS],
        ...(answer.status === "mitigated" && hasEvidence
          ? {
              resolution: "resolved" as const,
              reason: "확인된 근거와 대응책이 실패 조건을 직접 해소합니다.",
              reframed_question: null,
            }
          : answer.status === "invalid"
            ? {
                resolution: "reframed" as const,
                reason: "질문 전제를 반박했지만 검증 방법은 아직 없어 더 작은 질문으로 좁힙니다.",
                reframed_question: "이 전제가 틀렸다는 것을 가장 먼저 확인할 수 있는 신호는 무엇인가요?",
              }
            : {
                resolution: "open" as const,
                reason: "검증 가능한 근거가 아직 없어 이 쟁점은 열린 상태로 유지됩니다.",
                reframed_question: null,
              }),
      };
      next.messages.push(verdict);
    }
    next.completed = true;
    next.resolution_source = "fallback";
    debate = next;
    return structuredClone(debate);
  },
};
