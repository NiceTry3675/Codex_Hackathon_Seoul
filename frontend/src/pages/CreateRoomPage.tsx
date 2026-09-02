import { FormEvent, useEffect, useState } from "react";
import type { CreateRoomPayload } from "../types";

interface CreateRoomPageProps {
  isAuthenticated: boolean;
  loading: boolean;
  onCreate: (payload: CreateRoomPayload) => Promise<void>;
}

const DEMO_QUESTION = "6시간 해커톤에서 어떤 아이디어를 만들까요?";
const DEMO_OPTIONS = "A. AI 보안 도구\nB. 팀 의사결정 도구\nC. 회의 요약 도구";
const DEMO_CRITERIA = "창의성\n구현 가능성\n발표 임팩트";

const submissionModes = [
  {
    value: "anonymous",
    label: "익명 제출",
    description: "이름 없이 판단 내용만 수집합니다.",
  },
  {
    value: "named",
    label: "실명 제출",
    description: "이름을 받고 대기 화면에 제출자를 표시합니다.",
  },
] as const;

const lines = (value: string) =>
  value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);

/** 백엔드 RoomCreate와 같은 규칙: 최대 10개, 200자 이내, 중복 금지. */
function labelError(items: string[], name: string): string | undefined {
  if (items.length > 10) return `${name}은(는) 최대 10개까지 입력할 수 있어요.`;
  if (items.some((item) => item.length > 200)) return `${name}은(는) 항목당 200자 이내로 입력해 주세요.`;
  if (new Set(items).size !== items.length) return `${name}에 같은 항목이 두 번 있어요.`;
  return undefined;
}

function CreateRoomPage({ isAuthenticated, loading, onCreate }: CreateRoomPageProps) {
  const [question, setQuestion] = useState(DEMO_QUESTION);
  const [options, setOptions] = useState(DEMO_OPTIONS);
  const [criteria, setCriteria] = useState(DEMO_CRITERIA);
  const [expectedMembers, setExpectedMembers] = useState(4);
  const [submissionMode, setSubmissionMode] = useState<"anonymous" | "named">("anonymous");

  useEffect(() => {
    if (!isAuthenticated) {
      setSubmissionMode("anonymous");
    }
  }, [isAuthenticated]);

  const optionError = labelError(lines(options), "선택지");
  const criteriaError = labelError(lines(criteria), "평가 기준");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (submissionMode === "named" && !isAuthenticated) return;
    if (optionError || criteriaError) return;
    void onCreate({
      question: question.trim(),
      options: lines(options),
      criteria: lines(criteria),
      expected_members: expectedMembers,
      submission_mode: submissionMode,
    }).catch(() => undefined);
  };

  return (
    <div className="mx-auto max-w-4xl px-4 py-10 sm:px-6 sm:py-16">
      <section className="mx-auto max-w-2xl text-center">
        <p className="eyebrow">Create a room</p>
        <h1 className="mt-3 text-4xl font-semibold tracking-[-0.05em] sm:text-5xl">우리 팀의 결정을 시작해요.</h1>
        <p className="mx-auto mt-4 max-w-xl leading-7 text-stone-600">질문과 평가 기준을 정하면 공유 가능한 6자리 코드가 생성됩니다.</p>
      </section>

      <form onSubmit={submit} className="card mx-auto mt-10 max-w-2xl space-y-6">
        <label className="block">
          <span className="mb-2 block text-sm font-bold text-stone-600">결정할 질문</span>
          <input
            className="w-full rounded-2xl border border-black/10 bg-stone-50 px-4 py-3 placeholder:text-stone-400"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="예: 6시간 해커톤에서 어떤 아이디어를 만들까요?"
            required
            maxLength={500}
          />
        </label>

        <div className="grid gap-5 sm:grid-cols-2">
          <label className="block">
            <span className="mb-2 block text-sm font-bold text-stone-600">선택지 · 한 줄에 하나</span>
            <textarea
              className="min-h-36 w-full rounded-2xl border border-black/10 bg-stone-50 px-4 py-3 placeholder:text-stone-400"
              value={options}
              onChange={(event) => setOptions(event.target.value)}
              placeholder={"예: A. AI 보안 도구\nB. 팀 의사결정 도구\nC. 회의 요약 도구"}
              required
            />
            {optionError && <span className="mt-2 block text-xs font-semibold text-red-700">{optionError}</span>}
          </label>
          <label className="block">
            <span className="mb-2 block text-sm font-bold text-stone-600">평가 기준 · 한 줄에 하나</span>
            <textarea
              className="min-h-36 w-full rounded-2xl border border-black/10 bg-stone-50 px-4 py-3 placeholder:text-stone-400"
              value={criteria}
              onChange={(event) => setCriteria(event.target.value)}
              placeholder={"예: 창의성\n구현 가능성\n발표 임팩트"}
              required
            />
            {criteriaError && <span className="mt-2 block text-xs font-semibold text-red-700">{criteriaError}</span>}
          </label>
        </div>

        <label className="block">
          <span className="mb-2 block text-sm font-bold text-stone-600">참여 인원</span>
          <input type="number" min={1} max={100} className="w-full rounded-2xl border border-black/10 bg-stone-50 px-4 py-3" value={expectedMembers} onChange={(event) => setExpectedMembers(Number(event.target.value))} required />
        </label>

        <fieldset>
          <legend className="mb-3 text-sm font-bold text-stone-600">제출 방식</legend>
          <div className="grid gap-3 sm:grid-cols-2">
            {submissionModes.map(({ value, label, description }) => {
              const disabled = value === "named" && !isAuthenticated;
              return (
                <label
                  key={value}
                  className={`rounded-2xl border p-4 transition ${
                    disabled
                      ? "cursor-not-allowed border-black/5 bg-stone-100 opacity-65"
                      : submissionMode === value
                        ? "cursor-pointer border-moss-600 bg-moss-50"
                        : "cursor-pointer border-black/10 bg-stone-50"
                  }`}
                >
                  <input
                    className="sr-only"
                    type="radio"
                    name="submission-mode"
                    value={value}
                    checked={submissionMode === value}
                    disabled={disabled}
                    onChange={() => setSubmissionMode(value)}
                  />
                  <span className="block font-bold">{label}</span>
                  <span className="mt-1 block text-sm text-stone-500">{description}</span>
                  {disabled && (
                    <span className="mt-2 block text-xs font-semibold text-amber-700">
                      Google 로그인 후 만들 수 있습니다.
                    </span>
                  )}
                </label>
              );
            })}
          </div>
        </fieldset>

        <button
          type="submit"
          className="primary-button w-full"
          disabled={
            loading ||
            lines(options).length < 2 ||
            lines(criteria).length < 1 ||
            Boolean(optionError || criteriaError) ||
            (submissionMode === "named" && !isAuthenticated)
          }
        >
          {loading ? "방 만드는 중…" : "방 만들기"}
        </button>
      </form>
    </div>
  );
}

export default CreateRoomPage;
