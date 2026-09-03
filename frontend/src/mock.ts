import type {
  AnalysisResponse,
  ChallengerQuestion,
  ChallengerResolutionMessage,
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
  DefenderMessage,
  DefenderTurnPayload,
  OptionSuggestPayload,
  OptionSuggestResponse,
  Room,
  SubmissionPayload,
  SubmitResponse,
} from "./types";
import { calculateRanking } from "./calculations.ts";

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
  created_at: new Date().toISOString(),
  expires_at: new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString(),
  participant_names: [],
  submission_count: 3,
  is_complete: false,
};

const MOCK_CRITERIA_SUGGESTIONS = [
  { name: "사용자 가치", why: "실제 사용자가 왜 쓰는지 설명할 수 있는지 봅니다.", description: "사용자의 문제를 실질적으로 해결하는 정도입니다.", one_point: "사용자에게 거의 도움이 되지 않음", five_point: "사용자 문제를 매우 잘 해결함" },
  { name: "기술 대응력", why: "기술 문제가 생겨도 제한 시간 안에 해결하거나 우회할 수 있는지 확인합니다.", description: "기술적 장애를 해결하거나 우회할 수 있는 정도입니다.", one_point: "문제가 생기면 진행하기 어려움", five_point: "대체 경로로 쉽게 대응 가능" },
  { name: "차별성", why: "비슷한 도구와 비교했을 때 다른 점이 분명한지 봅니다.", description: "기존 대안과 구별되는 가치가 있는 정도입니다.", one_point: "기존 대안과 거의 같음", five_point: "차별점이 매우 분명함" },
  { name: "확장 가능성", why: "해커톤 이후에도 이어서 발전시킬 여지가 있는지 따집니다.", description: "초기 결과를 더 큰 제품으로 발전시킬 수 있는 정도입니다.", one_point: "추가 발전이 매우 어려움", five_point: "자연스럽게 확장할 수 있음" },
  { name: "구현 가능성", why: "남은 시간 안에 실제로 만들 수 있는지 봅니다.", description: "현재 인력과 시간으로 완성할 수 있는 정도입니다.", one_point: "완성 가능성이 매우 낮음", five_point: "충분히 완성할 수 있음" },
];

const MOCK_OPTION_SUGGESTIONS = [
  { name: "현재 방식 유지", why: "변화하지 않는 경우도 같은 조건에서 비교할 수 있습니다." },
  { name: "핵심 기능만 직접 개발", why: "제한된 시간 안에 가장 중요한 가설에 집중할 수 있습니다." },
  { name: "기존 도구 조합", why: "이미 검증된 구성요소를 활용하는 접근을 비교할 수 있습니다." },
  { name: "작게 시험 운영", why: "작은 범위에서 반응을 확인한 뒤 확대 여부를 판단할 수 있습니다." },
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
    [optionA]: 0.477,
    [optionB]: 0.523,
    [optionC]: 0,
  },
  current_winner: optionA,
  robust_choice: optionB,
  flip_points: [
    {
      type: "weight",
      criterion: "구현 가능성",
      from: 0.71,
      to: 0.72,
      change: 0.01,
      direction: "increase",
      proximity: "nearby",
      new_winner: optionB,
    },
    {
      type: "member",
      description: "1명의 의견을 제외하면 결과가 B. 팀 의사결정 도구(으)로 바뀜",
    },
  ],
  discussion_agenda: [
    "구현 가능성 비중이 1%p 오르면 B. 팀 의사결정 도구(으)로 바뀝니다. 이 기준을 먼저 논의하세요.",
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
let decisionRecord: DecisionRecord | undefined;
let decisionRecheck: DecisionRecheck | undefined;

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
  async suggestOptions(payload: OptionSuggestPayload): Promise<OptionSuggestResponse> {
    await delay(650);
    const existing = new Set(payload.existing_options.map((item) => item.replace(/\s+/g, "")));
    return {
      options: MOCK_OPTION_SUGGESTIONS.filter((item) => !existing.has(item.name.replace(/\s+/g, ""))),
      source: "fallback",
    };
  },

  async suggestCriteria(payload: CriteriaSuggestPayload): Promise<CriteriaSuggestResponse> {
    await delay(700);
    const existing = new Set(payload.existing_criteria.map((item) => item.replace(/\s+/g, "")));
    return {
      criteria: MOCK_CRITERIA_SUGGESTIONS.filter((item) => !existing.has(item.name.replace(/\s+/g, ""))),
      source: "fallback",
    };
  },

  async messageAssistant(payload: DecisionAssistantPayload): Promise<DecisionAssistantResponse> {
    await delay(500);
    const message = !payload.question.trim()
      ? "먼저 팀이 답해야 할 결정 질문을 한 문장으로 적어 주세요."
      : payload.options.length < 2
        ? "선택지는 팀이 실제로 고를 후보예요. 서로 겹치지 않는 대안을 두 개 이상 적어 보세요."
        : payload.criteria.length === 0
          ? "평가 기준은 모든 선택지를 비교하는 공통 잣대예요. 실행 가능성이나 사용자 가치부터 생각해 보세요."
          : "선택지는 후보, 평가 기준은 후보를 비교하는 잣대예요. 지금 항목들이 서로 겹치지 않는지 함께 확인해 볼까요?";
    return { message, source: "fallback" };
  },

  async createRoom(payload: CreateRoomPayload): Promise<CreateRoomResponse> {
    await delay();
    debate = createMockDebate();
    decisionRecord = undefined;
    decisionRecheck = undefined;
    room = {
      code: DEFAULT_ROOM_CODE,
      question: payload.question,
      options: payload.options,
      criteria: payload.criteria,
      context: payload.context ?? "",
      expected_members: payload.expected_members ?? 4,
      submission_mode: payload.submission_mode ?? "anonymous",
      created_at: new Date().toISOString(),
      expires_at: new Date(Date.now() + (payload.expires_in_hours ?? 24) * 60 * 60 * 1000).toISOString(),
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

  async getDecisionRecord(_code: string): Promise<DecisionRecord> {
    await delay(120);
    if (!decisionRecord) throw new Error("decision record not found");
    return structuredClone(decisionRecord);
  },

  async createDecisionRecord(_code: string, payload: DecisionRecordPayload): Promise<DecisionRecord> {
    await delay(220);
    if (decisionRecord) throw new Error("decision record already exists");
    decisionRecord = {
      initial_majority_choice: optionA,
      analysis_winner: MOCK_ANALYSIS.current_winner,
      robust_choice: MOCK_ANALYSIS.robust_choice,
      final_choice: payload.final_choice,
      final_reason: payload.final_reason,
      decided_at: new Date().toISOString(),
      changed_from_initial: payload.final_choice !== optionA,
    };
    return structuredClone(decisionRecord);
  },

  async getDecisionRecheck(_code: string): Promise<DecisionRecheck> {
    await delay(120);
    if (!decisionRecheck) throw new Error("decision recheck not found");
    return structuredClone(decisionRecheck);
  },

  async createDecisionRecheck(_code: string, payload: DecisionRecheckPayload): Promise<DecisionRecheck> {
    await delay(260);
    if (decisionRecheck) throw new Error("decision recheck already exists");
    const after = structuredClone(MOCK_ANALYSIS);
    after.team_weights = Object.fromEntries(Object.entries(payload.weights).map(([key, value]) => [key, value / 100]));
    after.current_winner = calculateRanking(
      room.options,
      room.criteria,
      after.mean_scores ?? {},
      payload.weights,
    )[0]?.option ?? after.current_winner;
    decisionRecheck = {
      before: structuredClone(MOCK_ANALYSIS),
      after,
      revised_weights: { ...payload.weights },
      final_choice: payload.final_choice,
      consensus_note: payload.consensus_note,
      checked_at: new Date().toISOString(),
    };
    return structuredClone(decisionRecheck);
  },
};
