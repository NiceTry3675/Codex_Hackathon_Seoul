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

type Draft = Omit<DefenderAnswer, "challenge_id">;

const MAX_TEXT = 2000;

const statusOptions: Array<{ value: DefenseStatus; label: string; hint: string }> = [
  { value: "mitigated", label: "대응책 있음", hint: "근거나 대응책으로 이 실패 조건을 막을 수 있습니다." },
  { value: "open", label: "아직 미확인", hint: "검증이 필요하며 지금은 답할 근거가 없습니다." },
  { value: "invalid", label: "질문 전제가 틀림", hint: "질문이 전제한 조건이 우리 상황과 맞지 않습니다." },
];

const statusLabel: Record<DefenseStatus, string> = {
  mitigated: "대응책 있음",
  open: "아직 미확인",
  invalid: "질문 전제가 틀림",
};

const resolutionMeta: Record<ChallengeResolution, { label: string; badge: string; border: string }> = {
  resolved: { label: "해소됨", badge: "bg-moss-600 text-white", border: "border-moss-500" },
  open: { label: "열린 쟁점", badge: "bg-amber-500 text-white", border: "border-amber-400" },
  reframed: { label: "질문 재구성", badge: "bg-coral text-white", border: "border-coral" },
};

const emptyDraft = (): Draft => ({ status: "open", evidence: "", unknowns: "", mitigation: "" });

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

  useEffect(() => {
    let cancelled = false;
    setDebate(undefined);
    setLoadError("");
    setJustCompleted(false);
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
    setSubmitting(true);
    setSubmitError("");
    try {
      const answers: DefenderAnswer[] = parts.questions.map((question) => {
        const draft = drafts[question.challenge_id] ?? emptyDraft();
        return {
          challenge_id: question.challenge_id,
          status: draft.status,
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
        note={`공방 기록을 불러오지 못해 질문만 표시합니다. 통계 분석 결과에는 영향이 없습니다. (${loadError})`}
      />
    );
  }

  if (!debate || !parts) {
    return <Spinner title="공방 기록을 불러오는 중이에요." detail="AI가 던진 질문과 팀의 답변을 확인합니다." />;
  }

  const target = debate.evidence_snapshot.target;

  if (debate.completed) {
    const counts = { resolved: 0, open: 0, reframed: 0 };
    for (const verdict of parts.verdicts.values()) counts[verdict.resolution] += 1;

    return (
      <div className="mt-7 space-y-4">
        <div className="flex flex-wrap items-center gap-2 text-xs font-semibold">
          <span className="rounded-full bg-moss-100 px-3 py-1.5 text-moss-700">해소 {counts.resolved}</span>
          <span className="rounded-full bg-amber-100 px-3 py-1.5 text-amber-800">열린 쟁점 {counts.open}</span>
          <span className="rounded-full bg-red-100 px-3 py-1.5 text-red-700">재구성 {counts.reframed}</span>
          {debate.resolution_source === "fallback" && (
            <span className="rounded-full border border-black/10 bg-white px-3 py-1.5 text-stone-500" title="AI 판정을 받지 못해 모든 쟁점을 열린 상태로 유지했습니다.">
              판정 폴백
            </span>
          )}
          {justCompleted && (
            <span className="ml-auto rounded-full bg-ink px-3 py-1.5 text-white" role="status">
              열린 쟁점이 논의 안건에 추가됐어요
            </span>
          )}
        </div>

        {parts.questions.map((question, index) => {
          const defense = parts.defenses.get(question.challenge_id);
          const verdict = parts.verdicts.get(question.challenge_id);
          const meta = verdict ? resolutionMeta[verdict.resolution] : undefined;
          return (
            <article key={question.challenge_id} className={`overflow-hidden rounded-3xl border-2 bg-white ${meta?.border ?? "border-black/5"}`}>
              <div className="bg-ink p-4 text-sm leading-6 text-white/85 sm:p-5">
                <span className="mr-2 text-xs font-bold uppercase tracking-[0.18em] text-moss-100">Challenger · Q{index + 1}</span>
                <p className="mt-2">{question.question}</p>
              </div>
              {defense && (
                <div className="border-b border-black/5 p-4 text-sm leading-6 sm:p-5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-bold uppercase tracking-[0.18em] text-stone-500">Defender · 팀</span>
                    <span className="rounded-full bg-stone-100 px-2.5 py-1 text-xs font-semibold">{statusLabel[defense.status]}</span>
                  </div>
                  <dl className="mt-3 grid gap-3 sm:grid-cols-3">
                    {[
                      ["확인된 근거", defense.evidence],
                      ["아직 모르는 점", defense.unknowns],
                      ["대응책", defense.mitigation],
                    ].map(([label, value]) => (
                      <div key={label} className="rounded-2xl bg-stone-50 p-3">
                        <dt className="text-xs font-bold text-stone-500">{label}</dt>
                        <dd className={`mt-1 whitespace-pre-wrap ${value ? "" : "text-stone-400"}`}>{value || "—"}</dd>
                      </div>
                    ))}
                  </dl>
                </div>
              )}
              {verdict && meta && (
                <div className="p-4 text-sm leading-6 sm:p-5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-bold uppercase tracking-[0.18em] text-stone-500">Challenger · 판정</span>
                    <span className={`rounded-full px-2.5 py-1 text-xs font-bold ${meta.badge}`}>{meta.label}</span>
                  </div>
                  <p className="mt-2">{verdict.reason}</p>
                  {verdict.resolution === "reframed" && verdict.reframed_question && (
                    <p className="mt-3 rounded-2xl border border-coral/40 bg-red-50/60 p-3">
                      <span className="mr-2 font-bold text-coral">다시 묻기</span>
                      {verdict.reframed_question}
                    </p>
                  )}
                </div>
              )}
            </article>
          );
        })}

        <p className="text-xs leading-5 text-stone-500">
          공방은 점수·안정성·1위를 바꾸지 않습니다. 해소되지 않은 쟁점만 아래 논의 안건으로 되돌아갑니다.
        </p>
      </div>
    );
  }

  if (submitting) {
    return <Spinner title="AI가 답변을 증거에 비춰 판정하고 있어요." detail="동결된 분석 증거만 사용합니다. 최대 1분 정도 걸릴 수 있어요." />;
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="mt-7 space-y-4">
      <p className="text-sm leading-6 text-stone-500">
        AI가 <strong className="text-ink">{target}</strong> 선택이 실패할 수 있는 조건을 질문합니다. 팀이 답하면 AI가 답변을 판정하고, 해소되지 않은 쟁점만 논의 안건으로 남깁니다.
        {debate.challenger_source === "fallback" && " (AI 질문 생성을 받지 못해 기본 질문을 사용합니다.)"}
      </p>

      {parts.questions.map((question, index) => {
        const draft = drafts[question.challenge_id] ?? emptyDraft();
        return (
          <fieldset key={question.challenge_id} className="overflow-hidden rounded-3xl border border-black/5 bg-white">
            <legend className="sr-only">질문 {index + 1}</legend>
            <div className="bg-ink p-4 text-sm leading-6 text-white/85 sm:p-5">
              <span className="text-xs font-bold uppercase tracking-[0.18em] text-moss-100">Challenger · Q{index + 1}</span>
              <p className="mt-2">{question.question}</p>
            </div>
            <div className="space-y-4 p-4 sm:p-5">
              <div className="grid gap-2 sm:grid-cols-3">
                {statusOptions.map((option) => {
                  const selected = draft.status === option.value;
                  return (
                    <label
                      key={option.value}
                      className={`cursor-pointer rounded-2xl border p-3 transition ${selected ? "border-moss-600 bg-moss-50" : "border-black/10 bg-stone-50"}`}
                    >
                      <input
                        className="sr-only"
                        type="radio"
                        name={`status-${question.challenge_id}`}
                        value={option.value}
                        checked={selected}
                        onChange={() => updateDraft(question.challenge_id, { status: option.value })}
                      />
                      <span className="block text-sm font-bold">{option.label}</span>
                      <span className="mt-1 block text-xs leading-5 text-stone-500">{option.hint}</span>
                    </label>
                  );
                })}
              </div>
              <div className="grid gap-3 sm:grid-cols-3">
                {(
                  [
                    ["evidence", "확인된 근거", "이미 확인된 사실만 적어요."],
                    ["unknowns", "아직 모르는 점", "검증이 필요한 부분을 적어요."],
                    ["mitigation", "대응책", "실패 시 무엇을 할지 적어요."],
                  ] as const
                ).map(([field, label, placeholder]) => (
                  <label key={field} className="block">
                    <span className="mb-1.5 block text-xs font-bold text-stone-600">{label}</span>
                    <textarea
                      className="min-h-24 w-full rounded-2xl border border-black/10 bg-stone-50 px-3 py-2.5 text-sm placeholder:text-stone-400"
                      value={draft[field]}
                      maxLength={MAX_TEXT}
                      placeholder={placeholder}
                      onChange={(event) => updateDraft(question.challenge_id, { [field]: event.target.value })}
                    />
                  </label>
                ))}
              </div>
            </div>
          </fieldset>
        );
      })}

      {submitError && (
        <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
          {submitError}
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-stone-500">답변은 한 번만 제출할 수 있고, 제출 후 AI가 최종 판정을 내립니다.</p>
        <button type="submit" className="primary-button" disabled={submitting || parts.questions.length === 0}>
          답변 제출하고 판정 받기
        </button>
      </div>
    </form>
  );
}

export default DebatePanel;
