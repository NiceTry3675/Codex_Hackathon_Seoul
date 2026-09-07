import { ChangeEvent, FormEvent, useEffect, useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import { api } from "../api";
import { CONTEXT_MAX_LENGTH } from "../types";
import type {
  AssistantMessage,
  CreateRoomPayload,
  CriteriaSuggestResponse,
  OptionSuggestResponse,
} from "../types";

interface CreateRoomPageProps {
  isAuthenticated: boolean;
  loading: boolean;
  onCreate: (payload: CreateRoomPayload) => Promise<void>;
}

const INITIAL_OPTIONS = ["", ""];
const INITIAL_CRITERIA = [""];

const submissionModes = [
  {
    value: "anonymous",
    label: "익명 제출",
    description: "이름을 입력하지 않고 제출합니다.",
  },
  {
    value: "named",
    label: "실명 제출",
    description: "이름을 받고 대기 화면에 제출자를 표시합니다.",
  },
] as const;

const cleanItems = (values: string[]) => values.map((item) => item.trim()).filter(Boolean);

/** 백엔드 RoomCreate와 같은 규칙: 최대 10개, 200자 이내, 중복 금지. */
function labelError(items: string[], name: string): string | undefined {
  if (items.length > 10) return `${name}: 최대 10개까지 입력할 수 있어요.`;
  if (items.some((item) => item.length > 200)) return `${name}: 항목당 200자 이내로 입력해 주세요.`;
  if (new Set(items).size !== items.length) return `${name}에 같은 항목이 두 번 있어요.`;
  return undefined;
}

const fieldClass = "w-full rounded-2xl border border-black/10 bg-stone-50 px-4 py-3 placeholder:text-stone-400";
const errorClass = "mt-2 block text-xs font-semibold text-red-700";

function CreateRoomPage({ isAuthenticated, loading, onCreate }: CreateRoomPageProps) {
  const [question, setQuestion] = useState("");
  const [context, setContext] = useState("");
  const [contextNotice, setContextNotice] = useState("");
  const [options, setOptions] = useState<string[]>(INITIAL_OPTIONS);
  const [criteria, setCriteria] = useState<string[]>(INITIAL_CRITERIA);
  const [expectedMembers, setExpectedMembers] = useState(4);
  const [expiresInHours, setExpiresInHours] = useState(24);
  const [submissionMode, setSubmissionMode] = useState<"anonymous" | "named">("anonymous");
  const [optionSuggesting, setOptionSuggesting] = useState(false);
  const [optionSuggestions, setOptionSuggestions] = useState<OptionSuggestResponse>();
  const [optionSuggestError, setOptionSuggestError] = useState("");
  const [criteriaSuggesting, setCriteriaSuggesting] = useState(false);
  const [criteriaSuggestions, setCriteriaSuggestions] = useState<CriteriaSuggestResponse>();
  const [criteriaSuggestError, setCriteriaSuggestError] = useState("");
  const [chatMessages, setChatMessages] = useState<AssistantMessage[]>([
    {
      role: "assistant",
      content: "질문, 선택지, 판단 기준 중 다듬고 싶은 부분을 알려 주세요.",
    },
  ]);
  const [chatInput, setChatInput] = useState("");
  const [chatting, setChatting] = useState(false);
  const [chatError, setChatError] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!isAuthenticated) {
      setSubmissionMode("anonymous");
    }
  }, [isAuthenticated]);

  const criteriaList = cleanItems(criteria);
  const optionList = cleanItems(options);
  const optionError = labelError(optionList, "선택지");
  const criteriaError = labelError(criteriaList, "판단 기준");
  const criteriaFull = criteriaList.length >= 10;
  const optionsFull = optionList.length >= 10;

  const loadContextFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
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
      setContextNotice(`파일을 불러왔어요: ${file.name}. ${CONTEXT_MAX_LENGTH.toLocaleString()}자 이후는 잘렸어요.`);
    } else {
      setContext(merged);
      setContextNotice(`파일을 불러왔어요: ${file.name}`);
    }
  };

  const requestOptionSuggestions = async () => {
    if (!question.trim()) {
      setOptionSuggestError("먼저 위에 결정할 질문을 입력해 주세요.");
      return;
    }
    setOptionSuggesting(true);
    setOptionSuggestError("");
    try {
      setOptionSuggestions(
        await api.suggestOptions({
          question: question.trim(),
          existing_options: optionList,
          context: context.trim(),
        }),
      );
    } catch (cause) {
      setOptionSuggestError(cause instanceof Error ? cause.message : "선택지를 제안받지 못했습니다.");
    } finally {
      setOptionSuggesting(false);
    }
  };

  const requestCriteriaSuggestions = async () => {
    if (!question.trim()) {
      setCriteriaSuggestError("먼저 위에 결정할 질문을 입력해 주세요.");
      return;
    }
    setCriteriaSuggesting(true);
    setCriteriaSuggestError("");
    try {
      setCriteriaSuggestions(
        await api.suggestCriteria({
          question: question.trim(),
          options: optionList,
          existing_criteria: criteriaList,
          context: context.trim(),
        }),
      );
    } catch (cause) {
      setCriteriaSuggestError(cause instanceof Error ? cause.message : "기준을 제안받지 못했습니다.");
    } finally {
      setCriteriaSuggesting(false);
    }
  };

  const addOption = (name: string) => {
    if (optionList.includes(name) || optionsFull) return;
    setOptions((current) => {
      const firstEmpty = current.findIndex((item) => !item.trim());
      if (firstEmpty >= 0) {
        return current.map((item, index) => (index === firstEmpty ? name : item));
      }
      return [...current, name].slice(0, 10);
    });
  };

  const addCriterion = (name: string) => {
    if (criteriaList.includes(name) || criteriaFull) return;
    setCriteria((current) => {
      const next = current.length === 1 && !current[0].trim() ? [name] : [...current, name];
      return next.slice(0, 10);
    });
  };

  const sendChatMessage = async () => {
    const content = chatInput.trim();
    if (!content || chatting) return;
    const userMessage: AssistantMessage = { role: "user", content };
    const history = [...chatMessages, userMessage].slice(-8);
    setChatMessages((current) => [...current, userMessage]);
    setChatInput("");
    setChatting(true);
    setChatError("");
    try {
      const response = await api.messageAssistant({
        question: question.trim(),
        options: optionList,
        criteria: criteriaList,
        context: context.trim(),
        messages: history,
      });
      setChatMessages((current) => [
        ...current,
        { role: "assistant", content: response.source === "fallback" ? `기본 안내 · 실시간 AI 답변이 아닌 준비된 안내입니다.\n\n${response.message}` : response.message },
      ]);
    } catch (cause) {
      setChatError(cause instanceof Error ? cause.message : "도우미의 답변을 받지 못했습니다.");
    } finally {
      setChatting(false);
    }
  };

  const updateItem = (
    setter: Dispatch<SetStateAction<string[]>>,
    index: number,
    value: string,
  ) => setter((current) => current.map((item, itemIndex) => (itemIndex === index ? value : item)));

  const addItem = (setter: Dispatch<SetStateAction<string[]>>) =>
    setter((current) => (current.length < 10 ? [...current, ""] : current));

  const removeItem = (
    setter: Dispatch<SetStateAction<string[]>>,
    index: number,
    minimum: number,
  ) => setter((current) => (current.length > minimum ? current.filter((_, itemIndex) => itemIndex !== index) : current));

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (submissionMode === "named" && !isAuthenticated) return;
    if (optionError || criteriaError) return;
    void onCreate({
      question: question.trim(),
      options: optionList,
      criteria: criteriaList,
      context: context.trim(),
      expected_members: expectedMembers,
      submission_mode: submissionMode,
      expires_in_hours: expiresInHours,
    }).catch(() => undefined);
  };

  return (
    <div className="mx-auto max-w-4xl px-4 py-10 sm:px-6 sm:py-16">
      <section className="mx-auto max-w-2xl text-center">
        <p className="eyebrow">결정 만들기</p>
        <h1 className="mt-3 text-4xl font-semibold tracking-[-0.05em] sm:text-5xl">무엇을 결정하나요?</h1>
        <p className="mx-auto mt-4 max-w-xl leading-7 text-stone-600">질문, 선택지, 판단 기준을 정하면 팀에 공유할 6자리 코드가 생깁니다.</p>
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
              결정 배경 · 선택
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
            placeholder="결정에 필요한 배경, 예산, 기한 등을 적어 주세요. 불필요한 개인정보는 빼 주세요."
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

        <section className="rounded-3xl border border-black/10 bg-stone-50/70 p-5 sm:p-6">
          <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
            <div className="flex gap-3">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-moss-700 text-sm font-bold text-white">1</span>
              <div>
                <h2 className="font-bold text-stone-800">선택지</h2>
                <p className="mt-1 text-sm leading-6 text-stone-500">
                  생각해 둔 <strong className="text-stone-700">선택지</strong>를 적어 주세요. 필요하면 AI가 찾은 후보 중 골라 추가할 수 있어요.
                </p>
              </div>
            </div>
            <button
              type="button"
              className="secondary-button shrink-0"
              onClick={() => void requestOptionSuggestions()}
              disabled={optionSuggesting}
            >
              {optionSuggesting ? "찾는 중…" : optionSuggestions ? "다른 후보 보기" : "선택지 더 찾아보기"}
            </button>
          </div>

          <div className="space-y-2">
            {options.map((option, index) => (
              <div key={index} className="flex items-center gap-2">
                <input
                  className={fieldClass}
                  value={option}
                  onChange={(event) => updateItem(setOptions, index, event.target.value)}
                  placeholder={index === 0 ? "예: 직접 개발" : index === 1 ? "예: 외부 솔루션 도입" : "선택지를 입력하세요"}
                  aria-label={`선택지 ${index + 1}`}
                  maxLength={200}
                  required
                />
                <button
                  type="button"
                  className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-black/10 bg-white text-xl text-stone-500 hover:text-red-700 disabled:opacity-30"
                  onClick={() => removeItem(setOptions, index, 2)}
                  disabled={options.length <= 2}
                  aria-label={`선택지 ${index + 1} 삭제`}
                  title="선택지 삭제"
                >
                  −
                </button>
              </div>
            ))}
          </div>
          <button type="button" className="secondary-button mt-3 w-full" onClick={() => addItem(setOptions)} disabled={options.length >= 10}>
            <span aria-hidden="true">＋</span> 선택지 직접 추가
          </button>
          {optionError && <span className={errorClass}>{optionError}</span>}
          {optionSuggestError && <span className={errorClass}>{optionSuggestError}</span>}

          {optionSuggestions && !optionSuggesting && (
            <div className="mt-4 border-t border-black/5 pt-4">
              <div className="mb-3 flex items-center gap-2">
                <p className="text-xs font-bold text-moss-700">선택지 후보</p>
                {optionSuggestions.source === "fallback" && <span className="rounded-full bg-white px-2 py-1 text-[11px] text-stone-500">기본 예시</span>}
              </div>
              <ul className="grid gap-2 sm:grid-cols-2">
                {optionSuggestions.options.map((item) => {
                  const added = optionList.includes(item.name);
                  return (
                    <li key={item.name} className="rounded-2xl border border-black/5 bg-white p-3">
                      <button
                        type="button"
                        onClick={() => addOption(item.name)}
                        disabled={added || optionsFull}
                        className="font-bold text-moss-700 disabled:text-moss-500"
                      >
                        {added ? `✓ ${item.name}` : `＋ ${item.name}`}
                      </button>
                      <p className="mt-1 text-xs leading-5 text-stone-500">{item.why}</p>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </section>

        <section className="rounded-3xl border border-black/10 bg-stone-50/70 p-5 sm:p-6">
          <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
            <div className="flex gap-3">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-moss-700 text-sm font-bold text-white">2</span>
              <div>
                <h2 className="font-bold text-stone-800">판단 기준</h2>
                <p className="mt-1 text-sm leading-6 text-stone-500">
                  모든 선택지에 적용할 <strong className="text-stone-700">기준</strong>을 적어 주세요. 빠진 기준은 AI 제안을 보고 추가할 수 있어요.
                </p>
              </div>
            </div>
            <button
              type="button"
              className="secondary-button shrink-0"
              onClick={() => void requestCriteriaSuggestions()}
              disabled={criteriaSuggesting}
            >
              {criteriaSuggesting ? "찾는 중…" : criteriaSuggestions ? "다른 후보 보기" : "빠진 기준 찾아보기"}
            </button>
          </div>

          <div className="space-y-2">
            {criteria.map((criterion, index) => (
              <div key={index} className="flex items-center gap-2">
                <input
                  className={fieldClass}
                  value={criterion}
                  onChange={(event) => updateItem(setCriteria, index, event.target.value)}
                  placeholder={index === 0 ? "예: 실행 가능성" : "긍정적인 방향의 기준을 입력하세요"}
                  aria-label={`판단 기준 ${index + 1}`}
                  maxLength={200}
                  required
                />
                <button
                  type="button"
                  className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-black/10 bg-white text-xl text-stone-500 hover:text-red-700 disabled:opacity-30"
                  onClick={() => removeItem(setCriteria, index, 1)}
                  disabled={criteria.length <= 1}
                  aria-label={`판단 기준 ${index + 1} 삭제`}
                  title="판단 기준 삭제"
                >
                  −
                </button>
              </div>
            ))}
          </div>
          <button type="button" className="secondary-button mt-3 w-full" onClick={() => addItem(setCriteria)} disabled={criteria.length >= 10}>
            <span aria-hidden="true">＋</span> 판단 기준 직접 추가
          </button>
          <p className="mt-2 text-xs leading-5 text-stone-500">점수가 높을수록 좋은 상태가 되도록 적어 주세요. 예: ‘비용’보다 ‘비용 효율성’</p>
          {criteriaError && <span className={errorClass}>{criteriaError}</span>}
          {criteriaSuggestError && <span className={errorClass}>{criteriaSuggestError}</span>}

          {criteriaSuggestions && !criteriaSuggesting && (
            <div className="mt-4 border-t border-black/5 pt-4">
              <div className="mb-3 flex items-center gap-2">
                <p className="text-xs font-bold text-moss-700">판단 기준 후보</p>
                {criteriaSuggestions.source === "fallback" && <span className="rounded-full bg-white px-2 py-1 text-[11px] text-stone-500">기본 예시</span>}
              </div>
              <ul className="space-y-2">
                {criteriaSuggestions.criteria.map((item) => {
                  const added = criteriaList.includes(item.name);
                  return (
                    <li key={item.name} className="rounded-2xl border border-black/5 bg-white p-3">
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                        <button
                          type="button"
                          onClick={() => addCriterion(item.name)}
                          disabled={added || criteriaFull}
                          className="font-bold text-moss-700 disabled:text-moss-500"
                        >
                          {added ? `✓ ${item.name}` : `＋ ${item.name}`}
                        </button>
                        <span className="text-xs text-stone-500">{item.why}</span>
                      </div>
                      <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-stone-500">
                        <span className="rounded-full bg-red-50 px-2 py-1">낮음 · {item.one_point}</span>
                        <span className="rounded-full bg-moss-50 px-2 py-1">높음 · {item.five_point}</span>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </section>

        <section className="overflow-hidden rounded-3xl border border-moss-500/30 bg-moss-50/50">
          <div className="border-b border-moss-500/15 px-5 py-4">
            <p className="font-bold text-stone-800">설정 도움받기</p>
            <p className="mt-1 text-xs text-stone-500">AI와 대화하며 질문, 선택지, 판단 기준을 다듬을 수 있어요. AI는 최종 선택을 대신하지 않아요.</p>
          </div>
          <div className="max-h-72 space-y-3 overflow-y-auto px-5 py-4" aria-live="polite">
            {chatMessages.map((message, index) => (
              <div key={index} className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
                <p className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-6 ${message.role === "user" ? "bg-moss-700 text-white" : "border border-black/5 bg-white text-stone-700"}`}>
                  {message.content}
                </p>
              </div>
            ))}
            {chatting && <p className="text-xs font-semibold text-moss-700">답변을 작성하는 중…</p>}
          </div>
          <div className="flex gap-2 border-t border-moss-500/15 bg-white/60 p-3">
            <input
              className="min-w-0 flex-1 rounded-2xl border border-black/10 bg-white px-4 py-3 text-sm placeholder:text-stone-400"
              value={chatInput}
              onChange={(event) => setChatInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void sendChatMessage();
                }
              }}
              placeholder="예: 이 선택지들이 충분히 다른가요?"
              maxLength={2_000}
              aria-label="설정을 돕는 AI에게 보낼 메시지"
            />
            <button type="button" className="primary-button shrink-0" onClick={() => void sendChatMessage()} disabled={!chatInput.trim() || chatting}>
              보내기
            </button>
          </div>
          {chatError && <span className={`${errorClass} px-5 pb-4`}>{chatError}</span>}
        </section>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block">
            <span className="mb-2 block text-sm font-bold text-stone-600">참여 인원</span>
            <input type="number" min={1} max={100} className="w-full rounded-2xl border border-black/10 bg-stone-50 px-4 py-3" value={expectedMembers} onChange={(event) => setExpectedMembers(Number(event.target.value))} required />
          </label>
          <label className="block">
            <span className="mb-2 block text-sm font-bold text-stone-600">방 유효 시간</span>
            <select className="w-full rounded-2xl border border-black/10 bg-stone-50 px-4 py-3" value={expiresInHours} onChange={(event) => setExpiresInHours(Number(event.target.value))}>
              <option value={6}>6시간</option>
              <option value={24}>24시간</option>
              <option value={72}>3일</option>
              <option value={168}>7일</option>
            </select>
          </label>
        </div>

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
            optionList.length < 2 ||
            criteriaList.length < 1 ||
            Boolean(optionError || criteriaError) ||
            (submissionMode === "named" && !isAuthenticated)
          }
        >
          {loading ? "만드는 중…" : "결정 만들기"}
        </button>
      </form>
    </div>
  );
}

export default CreateRoomPage;
