import { FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type {
  ChallengeResolution,
  ChallengerQuestion,
  ChallengerResolutionMessage,
  DebateState,
  DefenderAnswer,
  DefenderMessage,
  DefenseStatus,
  DevilsAdvocate,
} from "../types";

interface DebatePanelProps {
  roomCode: string;
  /** 공방 API를 못 불러올 때 읽기 전용으로 보여줄 분석 응답의 질문. */
  fallbackAdvocate?: DevilsAdvocate | null;
  /** 판정이 끝나면 호출된다. 부모는 분석을 다시 받아 논의 안건을 갱신한다. */
  onCompleted: () => Promise<void> | void;
}

type Draft = Omit<DefenderAnswer, "challenge_id" | "status"> & { status?: DefenseStatus };
type DraftTextField = "evidence" | "unknowns" | "mitigation";

const MAX_TEXT = 2000;

const statusOptions: Array<{ value: DefenseStatus; label: string; hint: string }> = [
  { value: "mitigated", label: "확인 완료", hint: "근거와 대비책이 있어요" },
  { value: "open", label: "확인 필요", hint: "아직 검증하지 못했어요" },
  { value: "invalid", label: "해당 없음", hint: "우리 상황과 맞지 않아요" },
];

const statusLabel: Record<DefenseStatus, string> = {
  mitigated: "확인 완료",
  open: "확인 필요",
  invalid: "해당 없음",
};

const resolutionMeta: Record<ChallengeResolution, { label: string; badge: string; border: string }> = {
  resolved: { label: "문제 없음", badge: "bg-moss-600 text-white", border: "border-moss-500" },
  open: { label: "회의에서 확인", badge: "bg-amber-500 text-white", border: "border-amber-400" },
  reframed: { label: "다시 확인", badge: "bg-coral text-white", border: "border-coral" },
};

const responseFields: Record<DefenseStatus, Array<{ field: DraftTextField; label: string; placeholder: string }>> = {
  mitigated: [
    { field: "evidence", label: "확인한 근거", placeholder: "예: 지난 3개월 운영 데이터에서 문제가 없었어요." },
    { field: "mitigation", label: "문제가 생기면 할 일", placeholder: "예: 오류율이 5%를 넘으면 이전 방식으로 돌아가요." },
  ],
  open: [
    { field: "unknowns", label: "무엇을 확인해야 하나요?", placeholder: "예: 실제 사용자 5명에게 이번 주 안에 테스트해야 해요." },
  ],
  invalid: [
    { field: "evidence", label: "왜 우리 상황과 맞지 않나요?", placeholder: "예: 우리는 이미 이 조건을 계약 단계에서 제외했어요." },
  ],
};

const emptyDraft = (): Draft => ({ evidence: "", unknowns: "", mitigation: "" });

function isDraftComplete(draft: Draft) {
  if (!draft.status) return false;
  return responseFields[draft.status].every(({ field }) => draft[field].trim().length > 0);
}

function splitMessages(debate: DebateState) {
  const questions: ChallengerQuestion[] = [];
  const defenses = new Map<string, DefenderMessage>();
  const verdicts = new Map<string, ChallengerResolutionMessage>();
  for (const message of debate.messages) {
    if (message.role === "defender") defenses.set(message.challenge_id, message);
    else if (message.turn === 1) questions.push(message);
    else verdicts.set(message.challenge_id, message);
  }
  return { questions, defenses, verdicts };
}

function Spinner({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="mt-7 flex items-center gap-4 rounded-2xl bg-stone-50 p-5" role="status">
      <div className="h-8 w-8 shrink-0 animate-spin rounded-full border-4 border-moss-100 border-t-moss-600" />
      <div>
        <p className="font-semibold">{title}</p>
        <p className="mt-0.5 text-sm text-stone-500">{detail}</p>
      </div>
    </div>
  );
}

function ReadOnlyQuestions({ advocate, note }: { advocate?: DevilsAdvocate | null; note: string }) {
  return (
    <div className="mt-7">
      {advocate?.challenges?.length ? (
        <ul className="space-y-3">
          {advocate.challenges.map((challenge) => (
            <li key={challenge} className="rounded-2xl bg-ink p-4 text-sm leading-6 text-white/85">
              <span className="mr-2 text-coral">Q.</span>
              {challenge}
            </li>
          ))}
        </ul>
      ) : null}
      <div className="mt-3 rounded-2xl bg-stone-50 p-4 text-sm leading-6 text-stone-500">{note}</div>
    </div>
  );
}

function DebatePanel({ roomCode, fallbackAdvocate, onCompleted }: DebatePanelProps) {
  const [debate, setDebate] = useState<DebateState>();
  const [loadError, setLoadError] = useState("");
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [justCompleted, setJustCompleted] = useState(false);
  const [activeQuestionIndex, setActiveQuestionIndex] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setDebate(undefined);
    setLoadError("");
    setJustCompleted(false);
    setActiveQuestionIndex(0);
    api
      .getDebate(roomCode)
      .then((state) => {
        if (cancelled) return;
        setDebate(state);
        setDrafts(
          Object.fromEntries(
            state.messages
              .filter((message) => message.role === "challenger" && message.turn === 1)
              .map((message) => [message.challenge_id, emptyDraft()]),
          ),
        );
      })
      .catch((cause: unknown) => {
        if (cancelled) return;
        setLoadError(cause instanceof Error ? cause.message : "공방 정보를 불러오지 못했습니다.");
      });
    return () => {
      cancelled = true;
    };
  }, [roomCode]);

  const parts = useMemo(() => (debate ? splitMessages(debate) : undefined), [debate]);

  const updateDraft = (challengeId: string, patch: Partial<Draft>) =>
    setDrafts((current) => ({ ...current, [challengeId]: { ...(current[challengeId] ?? emptyDraft()), ...patch } }));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!debate || !parts || submitting) return;
    if (parts.questions.some((question) => !isDraftComplete(drafts[question.challenge_id] ?? emptyDraft()))) return;
    setSubmitting(true);
    setSubmitError("");
    try {
      const answers: DefenderAnswer[] = parts.questions.map((question) => {
        const draft = drafts[question.challenge_id] ?? emptyDraft();
        return {
          challenge_id: question.challenge_id,
          status: draft.status ?? "open",
          evidence: draft.evidence.trim(),
          unknowns: draft.unknowns.trim(),
          mitigation: draft.mitigation.trim(),
        };
      });
      const next = await api.defendDecision(roomCode, { answers });
      setDebate(next);
      setJustCompleted(true);
      await onCompleted();
    } catch (cause) {
      setSubmitError(cause instanceof Error ? cause.message : "답변을 제출하지 못했습니다.");
    } finally {
      setSubmitting(false);
    }
  };

  if (loadError) {
    return (
      <ReadOnlyQuestions
        advocate={fallbackAdvocate}
        note={`위험 점검을 불러오지 못해 질문만 표시합니다. 분석 결과에는 영향이 없습니다. (${loadError})`}
      />
    );
  }

  if (!debate || !parts) {
    return <Spinner title="위험 점검을 준비하고 있어요." detail="결정 전에 확인할 질문을 불러옵니다." />;
  }

  const target = debate.evidence_snapshot.target;

  if (debate.completed) {
    const counts = { resolved: 0, open: 0, reframed: 0 };
    for (const verdict of parts.verdicts.values()) counts[verdict.resolution] += 1;
    const needsDiscussion = counts.open + counts.reframed;

    return (
      <div className="mt-6 space-y-3">
        <div className={`rounded-3xl p-6 sm:flex sm:items-center sm:justify-between sm:gap-6 ${needsDiscussion > 0 ? "bg-amber-50" : "bg-moss-50"}`}>
          <div>
            <span className={`text-xs font-bold ${needsDiscussion > 0 ? "text-amber-800" : "text-moss-700"}`}>위험 점검 완료</span>
            <strong className="mt-2 block text-2xl tracking-[-0.03em]">
              {needsDiscussion > 0 ? `${needsDiscussion}가지는 회의에서 확인하세요.` : "추가로 확인할 위험이 없어요."}
            </strong>
            {justCompleted && needsDiscussion > 0 && <p className="mt-2 text-sm text-stone-600" role="status">확인할 내용은 아래 논의 안건에 자동으로 추가했습니다.</p>}
          </div>
          <div className="mt-4 flex gap-2 text-xs font-semibold sm:mt-0">
            <span className="rounded-full bg-white px-3 py-2 text-moss-700">문제 없음 {counts.resolved}</span>
            <span className="rounded-full bg-white px-3 py-2 text-amber-800">확인 필요 {needsDiscussion}</span>
          </div>
        </div>

        {parts.questions.map((question, index) => {
          const defense = parts.defenses.get(question.challenge_id);
          const verdict = parts.verdicts.get(question.challenge_id);
          const meta = verdict ? resolutionMeta[verdict.resolution] : undefined;
          return (
            <details key={question.challenge_id} className={`group overflow-hidden rounded-2xl border bg-white ${meta?.border ?? "border-black/5"}`}>
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4 p-4 text-sm font-semibold sm:p-5">
                <span className="min-w-0"><span className="mr-2 text-stone-400">{index + 1}</span>{question.question}</span>
                {meta && <span className={`shrink-0 rounded-full px-2.5 py-1 text-[11px] font-bold ${meta.badge}`}>{meta.label}</span>}
              </summary>
              <div className="border-t border-black/5 p-4 text-sm leading-6 sm:p-5">
                {verdict && <p className="font-medium">{verdict.reason}</p>}
                {verdict?.resolution === "reframed" && verdict.reframed_question && (
                  <p className="mt-3 rounded-2xl bg-red-50 p-3"><span className="mr-2 font-bold text-coral">다시 확인할 질문</span>{verdict.reframed_question}</p>
                )}
                {defense && (
                  <div className="mt-4 rounded-2xl bg-stone-50 p-4">
                    <span className="text-xs font-bold text-stone-500">팀 답변 · {statusLabel[defense.status]}</span>
                    <dl className="mt-2 space-y-2">
                      {[
                        ["확인한 근거", defense.evidence],
                        ["확인해야 할 것", defense.unknowns],
                        ["문제가 생기면 할 일", defense.mitigation],
                      ].filter(([, value]) => value).map(([label, value]) => (
                        <div key={label}><dt className="inline font-semibold">{label}: </dt><dd className="inline whitespace-pre-wrap">{value}</dd></div>
                      ))}
                    </dl>
                  </div>
                )}
              </div>
            </details>
          );
        })}

        {debate.resolution_source === "fallback" && <p className="text-xs text-stone-400">AI 확인을 완료하지 못해 모든 항목을 확인 필요 상태로 유지했습니다.</p>}
      </div>
    );
  }

  if (submitting) {
    return <Spinner title="답변을 확인하고 있어요." detail="회의에서 다시 볼 내용만 추리는 중입니다." />;
  }

  const questionCount = parts.questions.length;
  const safeQuestionIndex = Math.min(activeQuestionIndex, Math.max(0, questionCount - 1));
  const activeQuestion = parts.questions[safeQuestionIndex];
  const activeDraft = activeQuestion ? drafts[activeQuestion.challenge_id] ?? emptyDraft() : emptyDraft();
  const answeredCount = parts.questions.filter((question) => isDraftComplete(drafts[question.challenge_id] ?? emptyDraft())).length;
  const allComplete = questionCount > 0 && answeredCount === questionCount;

  return (
    <form onSubmit={(event) => void submit(event)} className="mt-6">
      <div className="rounded-2xl bg-moss-50 p-4 sm:flex sm:items-center sm:justify-between sm:gap-5">
        <div>
          <strong className="block text-sm text-moss-900">왜 이걸 하나요?</strong>
          <p className="mt-1 text-sm leading-6 text-stone-600"><strong className="text-ink">{target}</strong>을 실행하기 전에 놓친 위험이 없는지 질문 {questionCount}개로 확인합니다.</p>
        </div>
        <div className="mt-3 flex shrink-0 gap-2 sm:mt-0">
          <span className="inline-flex rounded-full bg-white px-3 py-1.5 text-xs font-semibold text-moss-700">약 1분</span>
          {debate.challenger_source === "fallback" && <span className="inline-flex rounded-full bg-white px-3 py-1.5 text-xs font-semibold text-stone-500" title="AI 연결이 원활하지 않아 준비된 기본 질문을 사용합니다.">기본 질문</span>}
        </div>
      </div>

      {activeQuestion ? (
        <fieldset className="mt-5 overflow-hidden rounded-3xl border border-black/10 bg-white">
          <legend className="sr-only">위험 점검 질문 {safeQuestionIndex + 1}</legend>
          <div className="border-b border-black/5 p-5 sm:p-7">
            <div className="flex items-center justify-between gap-4">
              <span className="text-xs font-bold text-moss-700">위험 점검 {safeQuestionIndex + 1} / {questionCount}</span>
              <div className="flex gap-1.5" aria-label={`${questionCount}개 중 ${answeredCount}개 답변 완료`}>
                {parts.questions.map((question, index) => (
                  <span key={question.challenge_id} className={`h-1.5 w-8 rounded-full ${index === safeQuestionIndex ? "bg-moss-600" : isDraftComplete(drafts[question.challenge_id] ?? emptyDraft()) ? "bg-moss-200" : "bg-stone-200"}`} />
                ))}
              </div>
            </div>
            <h3 className="mt-5 max-w-3xl text-xl font-semibold leading-8 tracking-[-0.02em] sm:text-2xl">{activeQuestion.question}</h3>
          </div>

          <div className="p-5 sm:p-7">
            <p className="text-sm font-semibold text-stone-700">현재 상태를 선택하세요.</p>
            <div className="mt-3 grid gap-2 sm:grid-cols-3">
              {statusOptions.map((option) => {
                const selected = activeDraft.status === option.value;
                return (
                  <label key={option.value} className={`cursor-pointer rounded-2xl border p-4 transition ${selected ? "border-moss-600 bg-moss-50 shadow-sm" : "border-black/10 bg-white hover:bg-stone-50"}`}>
                    <input
                      className="sr-only"
                      type="radio"
                      name={`status-${activeQuestion.challenge_id}`}
                      value={option.value}
                      checked={selected}
                      onChange={() => updateDraft(activeQuestion.challenge_id, { status: option.value })}
                    />
                    <span className="block text-sm font-bold">{option.label}</span>
                    <span className="mt-1 block text-xs text-stone-500">{option.hint}</span>
                  </label>
                );
              })}
            </div>

            {activeDraft.status && (
              <div className={`mt-5 grid gap-4 ${responseFields[activeDraft.status].length > 1 ? "sm:grid-cols-2" : ""}`}>
                {responseFields[activeDraft.status].map(({ field, label, placeholder }) => (
                  <label key={field} className="block">
                    <span className="mb-2 block text-sm font-semibold text-stone-700">{label}</span>
                    <textarea
                      className="min-h-28 w-full rounded-2xl border border-black/10 bg-stone-50 px-4 py-3 text-sm leading-6 placeholder:text-stone-400"
                      value={activeDraft[field]}
                      maxLength={MAX_TEXT}
                      placeholder={placeholder}
                      required
                      onChange={(event) => updateDraft(activeQuestion.challenge_id, { [field]: event.target.value })}
                    />
                  </label>
                ))}
              </div>
            )}
          </div>
        </fieldset>
      ) : <p className="mt-5 rounded-2xl bg-stone-50 p-4 text-sm text-stone-500">확인할 질문이 없습니다.</p>}

      {submitError && (
        <div className="mt-4 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
          {submitError}
        </div>
      )}

      <div className="mt-5 flex items-center justify-between gap-3">
        <button type="button" className="secondary-button" onClick={() => setActiveQuestionIndex((current) => Math.max(0, current - 1))} disabled={safeQuestionIndex === 0}>이전</button>
        {safeQuestionIndex < questionCount - 1 ? (
          <button type="button" className="primary-button" onClick={() => setActiveQuestionIndex((current) => Math.min(questionCount - 1, current + 1))} disabled={!isDraftComplete(activeDraft)}>다음 질문</button>
        ) : (
          <button type="submit" className="primary-button" disabled={submitting || !allComplete}>점검 결과 확인하기</button>
        )}
      </div>
      <p className="mt-3 text-right text-xs text-stone-400">제출 후에는 답변을 수정할 수 없습니다.</p>
    </form>
  );
}

export default DebatePanel;
