import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { USE_MOCK_API } from "../api";
import { equalPercentages, rebalancePercentages } from "../calculations";
import { DEFAULT_ROOM_CODE } from "../mock";
import type { Room, SubmissionPayload } from "../types";

interface SubmitPageProps {
  room?: Room;
  loading: boolean;
  onJoin: (code: string) => Promise<void>;
  onSubmit: (payload: SubmissionPayload) => Promise<void>;
}

function createInitialScores(room: Room): SubmissionPayload["scores"] {
  return Object.fromEntries(room.options.map((option) => [option, {}]));
}

function sliderFill(value: number, min: number, max: number) {
  const ratio = ((value - min) / (max - min)) * 100;
  return { background: `linear-gradient(to right, #3b5e48 ${ratio}%, #e7e5e4 ${ratio}%)` };
}

function SubmitPage({ room, loading, onJoin, onSubmit }: SubmitPageProps) {
  const [code, setCode] = useState(room?.code ?? (USE_MOCK_API ? DEFAULT_ROOM_CODE : ""));
  const [scores, setScores] = useState<SubmissionPayload["scores"]>({});
  const [weights, setWeights] = useState<SubmissionPayload["weights"]>({});
  const [firstChoice, setFirstChoice] = useState("");
  const [reason, setReason] = useState("");
  const [participantName, setParticipantName] = useState("");
  const [copied, setCopied] = useState(false);
  const [attempted, setAttempted] = useState(false);
  const scoreSectionRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!room) return;
    setCode(room.code);
    setScores(createInitialScores(room));
    setWeights(equalPercentages(room.criteria));
    setFirstChoice("");
    setReason("");
    setParticipantName("");
    setAttempted(false);
  }, [room]);

  const completedScores = useMemo(() => {
    if (!room) return 0;
    return room.options.reduce(
      (total, option) =>
        total + room.criteria.filter((criterion) => scores[option]?.[criterion]).length,
      0,
    );
  }, [room, scores]);

  const totalScores = room ? room.options.length * room.criteria.length : 0;

  const joinRoom = (event: FormEvent) => {
    event.preventDefault();
    void onJoin(code).catch(() => undefined);
  };

  const submitForm = (event: FormEvent) => {
    event.preventDefault();
    if (!room || !firstChoice) return;
    if (completedScores !== totalScores) {
      setAttempted(true);
      scoreSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    if (room.submission_mode === "named" && !participantName.trim()) return;
    void onSubmit({
      scores,
      weights,
      first_choice: firstChoice,
      reason: reason.trim(),
      ...(room.submission_mode === "named" ? { participant_name: participantName.trim() } : {}),
    });
  };

  const copyCode = async () => {
    if (!room) return;
    await navigator.clipboard.writeText(room.code);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="mx-auto max-w-4xl px-4 py-10 sm:px-6 sm:py-16">
      <section className="mx-auto max-w-2xl text-center">
        <p className="eyebrow">Step 01 · Private input</p>
        <h1 className="mt-3 text-4xl font-semibold tracking-[-0.05em] sm:text-5xl">먼저, 각자의 판단을 남겨요.</h1>
        <p className="mx-auto mt-4 max-w-xl leading-7 text-stone-600">
          분위기에 휩쓸리지 않고, 내 소신대로 먼저 점수를 매겨보세요!
        </p>
      </section>

      <form onSubmit={joinRoom} className="card mx-auto mt-10 flex max-w-xl flex-col gap-3 sm:flex-row">
        <label className="flex-1">
          <span className="mb-2 block text-xs font-bold text-stone-500">6자리 방 코드</span>
          <input
            value={code}
            onChange={(event) => setCode(event.target.value.toUpperCase().slice(0, 6))}
            className="w-full rounded-2xl border border-black/10 bg-stone-50 px-4 py-3 font-mono text-lg font-bold uppercase tracking-[0.2em]"
            placeholder="X7K2P9"
            aria-label="방 코드"
            minLength={6}
            maxLength={6}
            required
          />
        </label>
        <button type="submit" className="primary-button self-end" disabled={loading || code.length !== 6}>
          {loading ? "확인 중…" : "방 참여하기"}
        </button>
      </form>

      {!room ? (
        <div className="mt-12 text-center text-sm text-stone-500">방 코드를 입력해 주세요.</div>
      ) : (
        <form onSubmit={submitForm} className="mt-8 space-y-6">
          <section className="card overflow-hidden">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <p className="eyebrow">Room {room.code}</p>
                <h2 className="mt-2 text-2xl font-semibold tracking-tight">{room.question}</h2>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => void copyCode()}
                  className="inline-flex items-center gap-2 rounded-2xl border border-black/10 bg-white px-4 py-3 text-sm font-semibold"
                  aria-label={`방 코드 ${room.code} 복사`}
                >
                  <span aria-hidden="true">{copied ? "✓" : "⧉"}</span>
                  <span aria-live="polite">{copied ? "복사됐어요" : `코드 ${room.code} 복사`}</span>
                </button>
                <div className="rounded-2xl bg-moss-50 px-4 py-3 text-sm font-semibold text-moss-700">
                  <span aria-hidden="true">◉</span> {room.submission_mode === "named" ? "실명 제출" : "익명 제출"}
                </div>
              </div>
            </div>
            {room.context && (
              <details className="mt-5 rounded-2xl border border-black/10 bg-stone-50 px-4 py-3" open={room.context.length <= 200}>
                <summary className="cursor-pointer text-sm font-bold text-stone-600">배경 맥락</summary>
                <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-stone-600">{room.context}</p>
              </details>
            )}
            <p className="mt-5 text-sm leading-6 text-stone-500">
              {room.submission_mode === "named"
                ? "입력한 이름은 제출 완료 여부에만 표시되고 Google 계정과 연결되지 않으며, 개인 점수와 의견은 공개하지 않습니다."
                : "이 제출에는 로그인·작성자 정보를 연결하지 않으며, 개인 답변 대신 팀 전체의 분석 결과만 공유됩니다."}
            </p>
          </section>

          {room.submission_mode === "named" && (
            <section className="card">
              <label className="block">
                <span className="mb-2 block text-sm font-bold text-stone-600">이름</span>
                <input value={participantName} onChange={(event) => setParticipantName(event.target.value)} maxLength={100} required className="w-full rounded-2xl border border-black/10 bg-stone-50 px-4 py-3" placeholder="홍길동" />
              </label>
            </section>
          )}

          <section className="card scroll-mt-24" ref={scoreSectionRef}>
            <div className="flex items-end justify-between gap-4">
              <div>
                <p className="eyebrow">Score each option</p>
                <h2 className="section-title">옵션을 기준별로 평가해 주세요.</h2>
              </div>
              <span
                className={`shrink-0 text-sm font-semibold ${
                  completedScores === totalScores ? "text-moss-600" : "text-stone-500"
                }`}
                aria-live="polite"
              >
                {completedScores}/{totalScores}
              </span>
            </div>
            <p className="mt-3 text-sm text-stone-500">모든 기준에서 1점은 부정적, 5점은 긍정적입니다.</p>
            {attempted && completedScores !== totalScores && (
              <p className="mt-3 rounded-xl bg-red-50 px-3 py-2 text-sm font-semibold text-red-700" role="alert">
                아직 평가하지 않은 항목이 {totalScores - completedScores}개 있어요. 붉게 표시된 항목을 채워 주세요.
              </p>
            )}

            <div className="mt-7 space-y-4">
              {room.options.map((option) => (
                <div key={option} className="rounded-2xl border border-black/5 bg-stone-50/70 p-4 sm:p-5">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <h3 className="font-semibold">{option}</h3>
                    <span className="text-xs text-stone-500">1 부정적 · 5 긍정적</span>
                  </div>
                  <div className="mt-4 space-y-4">
                    {room.criteria.map((criterion) => {
                      const missing = attempted && !scores[option]?.[criterion];
                      return (
                        <div
                          key={criterion}
                          className={`grid items-center gap-3 rounded-xl transition sm:grid-cols-[1fr_auto] ${
                            missing ? "-mx-2 bg-red-50 px-2 py-2 ring-1 ring-red-200" : ""
                          }`}
                        >
                          <span className={`text-sm ${missing ? "font-semibold text-red-700" : "text-stone-600"}`}>
                            {criterion}
                          </span>
                          <div className="grid grid-cols-5 gap-2">
                            {[1, 2, 3, 4, 5].map((score) => {
                              const selected = scores[option]?.[criterion] === score;
                              return (
                                <label key={score} className="cursor-pointer">
                                  <input
                                    type="radio"
                                    name={`score-${option}-${criterion}`}
                                    value={score}
                                    checked={selected}
                                    onChange={() =>
                                      setScores((current) => ({
                                        ...current,
                                        [option]: { ...current[option], [criterion]: score },
                                      }))
                                    }
                                    className="peer sr-only"
                                    aria-label={`${option} ${criterion} ${score}점`}
                                  />
                                  <span
                                    className={`flex h-10 w-10 items-center justify-center rounded-xl text-sm font-bold transition peer-focus-visible:ring-2 peer-focus-visible:ring-moss-500 peer-focus-visible:ring-offset-2 sm:h-11 sm:w-11 ${
                                      selected
                                        ? "bg-ink text-white shadow-sm"
                                        : "border border-black/10 bg-white text-stone-500 hover:border-moss-500"
                                    }`}
                                  >
                                    {score}
                                  </span>
                                </label>
                              );
                            })}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="card">
            <p className="eyebrow">What matters</p>
            <h2 className="section-title">기준의 중요도는 얼마인가요?</h2>
            <p className="mt-3 text-sm text-stone-500">한 기준을 바꾸면 나머지가 비례 조정되며, 합계는 항상 100%입니다.</p>
            <div className="mt-7 space-y-6">
              {room.criteria.map((criterion) => (
                <label key={criterion} className="block">
                  <span className="flex items-center justify-between text-sm font-semibold">
                    {criterion}
                    <output className="rounded-lg bg-moss-50 px-2.5 py-1 text-moss-700">{weights[criterion] ?? 0}%</output>
                  </span>
                  <input
                    type="range"
                    min="1"
                    max={100 - Math.max(0, room.criteria.length - 1)}
                    value={weights[criterion] ?? 1}
                    onChange={(event) =>
                      setWeights((current) =>
                        rebalancePercentages(current, room.criteria, criterion, Number(event.target.value)),
                      )
                    }
                    className="slider mt-3"
                    style={sliderFill(weights[criterion] ?? 1, 1, 100 - Math.max(0, room.criteria.length - 1))}
                  />
                </label>
              ))}
            </div>
            <p className="mt-5 text-right text-sm font-bold text-moss-700" aria-live="polite">
              합계 {Object.values(weights).reduce((sum, value) => sum + value, 0)}%
            </p>
          </section>

          <section className="card">
            <fieldset>
              <legend>
                <span className="eyebrow">Your first choice</span>
                <span className="section-title block">지금 하나를 고른다면?</span>
              </legend>
              <div className="mt-5 space-y-3">
                {room.options.map((option) => {
                  const selected = firstChoice === option;
                  return (
                    <label key={option} className="block cursor-pointer">
                      <input
                        type="radio"
                        name="first-choice"
                        value={option}
                        checked={selected}
                        onChange={() => setFirstChoice(option)}
                        className="peer sr-only"
                        required
                      />
                      <span
                        className={`flex items-center gap-3 rounded-2xl border px-4 py-3.5 transition peer-focus-visible:ring-2 peer-focus-visible:ring-moss-500 peer-focus-visible:ring-offset-2 ${
                          selected
                            ? "border-moss-500 bg-moss-50 shadow-sm"
                            : "border-black/10 bg-stone-50 hover:border-moss-500"
                        }`}
                      >
                        <span
                          aria-hidden="true"
                          className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 transition ${
                            selected ? "border-moss-600 bg-moss-600" : "border-stone-300 bg-white"
                          }`}
                        >
                          {selected && <span className="h-2 w-2 rounded-full bg-white" />}
                        </span>
                        <span className={`text-sm ${selected ? "font-semibold text-moss-700" : "text-stone-600"}`}>
                          {option}
                        </span>
                      </span>
                    </label>
                  );
                })}
              </div>
            </fieldset>
            <label className="mt-6 block">
              <span className="text-sm font-semibold">그렇게 생각한 이유 <span className="font-normal text-stone-500">(선택)</span></span>
              <textarea
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                rows={4}
                maxLength={1000}
                className="mt-2 w-full resize-y rounded-2xl border border-black/10 bg-stone-50 px-4 py-3 leading-6"
                placeholder="예: 새로운 접근은 매력적이지만, 구현 위험이 걱정돼요."
              />
              <span className="mt-1 block text-right text-xs text-stone-500">{reason.length}/1000</span>
            </label>
          </section>

          <div className="flex flex-col items-center pb-4 pt-2">
            <button type="submit" className="primary-button w-full max-w-sm" disabled={loading}>
              {loading ? "제출 중…" : "의견 제출하기"}
            </button>
            <p className="mt-3 text-center text-xs text-stone-500">
              {completedScores !== totalScores
                ? `평가하지 않은 항목이 ${totalScores - completedScores}개 남았어요.`
                : "제출 후에는 개인 답변이 아닌 팀 전체의 분석을 확인할 수 있어요."}
            </p>
          </div>
        </form>
      )}
    </div>
  );
}

export default SubmitPage;
