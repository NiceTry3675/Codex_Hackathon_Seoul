import { ChangeEvent, FormEvent, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { CONTEXT_MAX_LENGTH } from "../types";
import type { CreateRoomPayload, CriteriaSuggestResponse } from "../types";

interface CreateRoomPageProps {
  isAuthenticated: boolean;
  loading: boolean;
  onCreate: (payload: CreateRoomPayload) => Promise<void>;
}

const DEMO_QUESTION = "6시간 해커톤에서 어떤 아이디어를 만들까요?";
const DEMO_OPTIONS = "A. AI 보안 도구\nB. 팀 의사결정 도구\nC. 회의 요약 도구";
const DEMO_CRITERIA = "창의성\n구현 가능성\n발표 임팩트";
const CONTEXT_FILE_MAX_BYTES = 1_000_000;

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

const fieldClass = "w-full rounded-2xl border border-black/10 bg-stone-50 px-4 py-3 placeholder:text-stone-400";
const errorClass = "mt-2 block text-xs font-semibold text-red-700";

function CreateRoomPage({ isAuthenticated, loading, onCreate }: CreateRoomPageProps) {
  const [question, setQuestion] = useState(DEMO_QUESTION);
  const [context, setContext] = useState("");
  const [contextNotice, setContextNotice] = useState("");
  const [options, setOptions] = useState(DEMO_OPTIONS);
  const [criteria, setCriteria] = useState(DEMO_CRITERIA);
  const [expectedMembers, setExpectedMembers] = useState(4);
  const [submissionMode, setSubmissionMode] = useState<"anonymous" | "named">("anonymous");
  const [suggesting, setSuggesting] = useState(false);
  const [suggestions, setSuggestions] = useState<CriteriaSuggestResponse>();
  const [suggestError, setSuggestError] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!isAuthenticated) {
      setSubmissionMode("anonymous");
    }
  }, [isAuthenticated]);

  const criteriaList = lines(criteria);
  const optionError = labelError(lines(options), "선택지");
  const criteriaError = labelError(criteriaList, "평가 기준");
  const criteriaFull = criteriaList.length >= 10;

  const loadContextFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (file.size > CONTEXT_FILE_MAX_BYTES) {
      setContextNotice("1MB 이하의 텍스트 파일만 불러올 수 있어요.");
      return;
    }
    let text: string;
    try {
      text = (await file.text()).replace(/\r\n/g, "\n").trim();
    } catch {
      setContextNotice("파일을 읽지 못했어요. 다른 파일로 다시 시도해 주세요.");
      return;
    }
    const merged = context.trim() ? `${context.trimEnd()}\n\n${text}` : text;
    if (merged.length > CONTEXT_MAX_LENGTH) {
      setContext(merged.slice(0, CONTEXT_MAX_LENGTH));
      setContextNotice(`${file.name}을(를) 불러왔지만 ${CONTEXT_MAX_LENGTH.toLocaleString()}자 이후는 잘렸어요.`);
    } else {
      setContext(merged);
      setContextNotice(`${file.name}을(를) 불러왔어요.`);
    }
  };

  const requestSuggestions = async () => {
    setSuggesting(true);
    setSuggestError("");
    try {
      setSuggestions(
        await api.suggestCriteria({
          question: question.trim(),
          options: lines(options),
          existing_criteria: criteriaList,
          context: context.trim(),
        }),
      );
    } catch (cause) {
      setSuggestError(cause instanceof Error ? cause.message : "기준을 제안받지 못했습니다.");
    } finally {
      setSuggesting(false);
    }
  };

  const addCriterion = (name: string) => {
    if (criteriaList.includes(name) || criteriaFull) return;
    setCriteria((current) => (current.trim() ? `${current.trimEnd()}\n${name}` : name));
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (submissionMode === "named" && !isAuthenticated) return;
    if (optionError || criteriaError) return;
    void onCreate({
      question: question.trim(),
      options: lines(options),
      criteria: criteriaList,
      context: context.trim(),
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
            className={fieldClass}
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="예: 6시간 해커톤에서 어떤 아이디어를 만들까요?"
            required
            maxLength={500}
          />
        </label>

        <div>
          <div className="mb-2 flex flex-wrap items-end justify-between gap-2">
            <label htmlFor="room-context" className="block text-sm font-bold text-stone-600">
              배경 맥락 · 선택
            </label>
            <button
              type="button"
              className="secondary-button min-h-9 px-3 py-1.5 text-xs"
              onClick={() => fileInputRef.current?.click()}
            >
              파일 불러오기 (.md, .txt)
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".md,.txt,.markdown,text/markdown,text/plain"
              className="hidden"
              onChange={(event) => void loadContextFile(event)}
            />
          </div>
          <textarea
            id="room-context"
            className={`${fieldClass} min-h-24 resize-y leading-6`}
            value={context}
            onChange={(event) => {
              setContext(event.target.value);
              setContextNotice("");
            }}
            placeholder="한 줄이어도 좋고, 회의록을 통째로 붙여 넣어도 됩니다. AI 기준 추천과 이후 검토의 근거가 됩니다."
            maxLength={CONTEXT_MAX_LENGTH}
          />
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs">
            <span className={contextNotice.includes("못") || contextNotice.includes("잘렸") ? "font-semibold text-amber-700" : "text-stone-500"}>
              {contextNotice}
            </span>
            <span className="text-stone-400">
              {context.length.toLocaleString()} / {CONTEXT_MAX_LENGTH.toLocaleString()}
            </span>
          </div>
        </div>

        <div className="grid gap-5 sm:grid-cols-2">
          <label className="block">
            <span className="mb-2 block text-sm font-bold text-stone-600">선택지 · 한 줄에 하나</span>
            <textarea
              className={`${fieldClass} min-h-36`}
              value={options}
              onChange={(event) => setOptions(event.target.value)}
              placeholder={"예: A. AI 보안 도구\nB. 팀 의사결정 도구\nC. 회의 요약 도구"}
              required
            />
            {optionError && <span className={errorClass}>{optionError}</span>}
          </label>
          <label className="block">
            <span className="mb-2 block text-sm font-bold text-stone-600">평가 기준 · 한 줄에 하나</span>
            <textarea
              className={`${fieldClass} min-h-36`}
              value={criteria}
              onChange={(event) => setCriteria(event.target.value)}
              placeholder={"예: 창의성\n구현 가능성\n발표 임팩트"}
              required
            />
            {criteriaError && <span className={errorClass}>{criteriaError}</span>}
          </label>
        </div>

        <section className="rounded-2xl border border-dashed border-moss-500/40 bg-moss-50/60 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm font-bold text-stone-700">AI가 놓친 기준을 제안해요</p>
              <p className="mt-1 text-xs text-stone-500">질문·선택지·배경 맥락을 읽고 관점을 제안합니다. 고르는 건 팀의 몫이에요.</p>
            </div>
            <button
              type="button"
              className="secondary-button"
              onClick={() => void requestSuggestions()}
              disabled={suggesting || !question.trim()}
            >
              {suggesting ? "기준을 제안하는 중…" : suggestions ? "다시 추천 받기" : "AI 추천 받기"}
            </button>
          </div>

          {suggestError && <span className={errorClass}>{suggestError}</span>}

          {suggestions && !suggesting && (
            <div className="mt-4 space-y-2">
              {suggestions.source === "fallback" && (
                <span
                  className="inline-block rounded-full border border-black/10 bg-white px-3 py-1 text-xs font-semibold text-stone-500"
                  title="AI 응답을 받지 못해 범용 기준을 보여드립니다."
                >
                  기본 추천
                </span>
              )}
              {suggestions.criteria.length === 0 && (
                <p className="text-sm text-stone-500">추가로 제안할 기준이 없어요.</p>
              )}
              <ul className="space-y-2">
                {suggestions.criteria.map((item) => {
                  const added = criteriaList.includes(item.name);
                  return (
                    <li key={item.name} className="flex flex-wrap items-center gap-x-3 gap-y-1">
                      <button
                        type="button"
                        onClick={() => addCriterion(item.name)}
                        disabled={added || criteriaFull}
                        className={`rounded-full px-3 py-1.5 text-sm font-semibold transition ${
                          added
                            ? "bg-moss-100 text-moss-700"
                            : "border border-moss-600 bg-white text-moss-700 hover:bg-moss-600 hover:text-white disabled:opacity-40"
                        }`}
                      >
                        {added ? `✓ ${item.name}` : `+ ${item.name}`}
                      </button>
                      <span className="text-xs text-stone-500">{item.why}</span>
                    </li>
                  );
                })}
              </ul>
              {criteriaFull && <p className="text-xs text-stone-500">평가 기준은 최대 10개까지예요.</p>}
            </div>
          )}
        </section>

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
            criteriaList.length < 1 ||
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
