import { useEffect, useMemo, useState } from "react";
import type { Agreement, AnalysisResponse, Room } from "../types";

interface ResultsPageProps {
  analysis: AnalysisResponse;
  room: Room;
}

const agreementStyle: Record<Agreement, string> = {
  HIGH: "bg-moss-100 text-moss-700",
  MID: "bg-amber-100 text-amber-800",
  LOW: "bg-red-100 text-red-700",
};

function percent(value: number) {
  return `${Math.round(value * 100)}%`;
}

function optionShortName(option: string) {
  return option.split(". ")[0] || option;
}

function useCountUp(target: number, duration = 900) {
  const [value, setValue] = useState(0);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setValue(target);
      return;
    }
    let frame = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setValue(target * eased);
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target, duration]);

  return value;
}

function StabilityDonut({ value }: { value: number }) {
  const animated = useCountUp(value);
  return (
    <div
      className="mx-auto mt-6 flex h-32 w-32 items-center justify-center rounded-full"
      style={{ background: `conic-gradient(#3b5e48 ${animated * 360}deg, #e7e5e4 0deg)` }}
    >
      <div className="flex h-24 w-24 items-center justify-center rounded-full bg-white text-3xl font-semibold tracking-tight">
        {percent(animated)}
      </div>
    </div>
  );
}

function sliderFill(value: number, min: number, max: number) {
  const ratio = ((value - min) / (max - min)) * 100;
  return { background: `linear-gradient(to right, #3b5e48 ${ratio}%, #e7e5e4 ${ratio}%)` };
}

function ResultsPage({ analysis, room }: ResultsPageProps) {
  const initialWeights = useMemo(
    () => Object.fromEntries(room.criteria.map((criterion) => [criterion, Math.round((analysis.team_weights[criterion] ?? 0) * 100)])),
    [analysis.team_weights, room.criteria],
  );
  const [liveWeights, setLiveWeights] = useState<Record<string, number>>(initialWeights);

  const normalizedWeights = useMemo(() => {
    const total = Object.values(liveWeights).reduce((sum, value) => sum + value, 0) || 1;
    return Object.fromEntries(room.criteria.map((criterion) => [criterion, (liveWeights[criterion] ?? 0) / total]));
  }, [liveWeights, room.criteria]);

  const liveRanking = useMemo(() => {
    if (!analysis.mean_scores) return [];
    return room.options
      .map((option) => ({
        option,
        score: room.criteria.reduce(
          (sum, criterion) =>
            sum + (analysis.mean_scores?.[option]?.[criterion] ?? 0) * (normalizedWeights[criterion] ?? 0),
          0,
        ),
      }))
      .sort((left, right) => right.score - left.score);
  }, [analysis.mean_scores, normalizedWeights, room.criteria, room.options]);

  const liveWinner = liveRanking[0]?.option;
  const winnerChanged = Boolean(liveWinner && liveWinner !== analysis.current_winner);
  const voteEntries = Object.entries(analysis.vote_share).sort(([, left], [, right]) => right - left);
  const stabilityEntries = Object.entries(analysis.stability).sort(([, left], [, right]) => right - left);

  return (
    <div className="pb-10">
      <section className="border-b border-black/5 bg-sand">
        <div className="mx-auto max-w-5xl px-4 py-14 text-center sm:px-6 sm:py-20">
          <p className="eyebrow">Step 03 · Decision stress test</p>
          <h1 className="mt-3 text-4xl font-semibold tracking-[-0.055em] sm:text-6xl">합의보다, 더 나은 선택.</h1>
          <p className="mx-auto mt-5 max-w-2xl text-lg leading-8 text-stone-600">
            현재 1위는 <strong className="text-ink">{analysis.current_winner}</strong>입니다. 하지만 조건이 조금만 달라져도 같은 결과일까요?
          </p>
          <div className="mt-8 flex flex-wrap justify-center gap-2 text-xs font-semibold text-stone-500">
            <a href="#votes" className="rounded-full bg-white px-3 py-2 hover:text-ink">득표</a>
            <a href="#stability" className="rounded-full bg-white px-3 py-2 hover:text-ink">안정성</a>
            <a href="#conflict" className="rounded-full bg-white px-3 py-2 hover:text-ink">숨은 갈등</a>
            <a href="#flip" className="rounded-full bg-white px-3 py-2 hover:text-ink">뒤집힘 조건</a>
            <a href="#discussion" className="rounded-full bg-white px-3 py-2 hover:text-ink">논의 안건</a>
          </div>
        </div>
      </section>

      <div className="mx-auto max-w-5xl space-y-7 px-4 py-10 sm:px-6 sm:py-14">
        <section id="votes" className="card scroll-mt-28">
          <p className="eyebrow">01 · First choices</p>
          <h2 className="section-title">표는 이렇게 갈렸습니다.</h2>
          <div className="mt-7 space-y-5">
            {voteEntries.map(([option, share], index) => (
              <div key={option}>
                <div className="mb-2 flex items-center justify-between gap-4 text-sm">
                  <span className="font-semibold"><span className="mr-2 text-stone-500">{index + 1}</span>{option}</span>
                  <strong>{percent(share)}</strong>
                </div>
                <div className="h-3 overflow-hidden rounded-full bg-stone-100">
                  <div className={`h-full rounded-full ${index === 0 ? "bg-ink" : "bg-stone-300"}`} style={{ width: percent(share) }} />
                </div>
              </div>
            ))}
          </div>
          <p className="mt-6 text-sm leading-6 text-stone-500">득표는 선호를 보여주지만, 그 결정이 조건 변화에도 유지되는지는 알려주지 않습니다.</p>
        </section>

        <section id="stability" className="card scroll-mt-28">
          <p className="eyebrow">02 · Decision stability</p>
          <h2 className="section-title">가중치가 흔들리면 결과도 흔들릴까요?</h2>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-stone-500">팀 가중치 주변을 반복해서 변화시켜, 각 옵션이 1위를 유지한 비율입니다.</p>
          <div className="mt-8 grid gap-4 md:grid-cols-3">
            {stabilityEntries.map(([option, value]) => {
              const robust = option === analysis.robust_choice;
              return (
                <div key={option} className={`rounded-3xl border p-5 ${robust ? "border-moss-500 bg-moss-50" : "border-black/5 bg-stone-50"}`}>
                  <div className="flex items-start justify-between gap-3">
                    <span className="text-sm font-semibold leading-5">{option}</span>
                    {robust && <span className="shrink-0 rounded-full bg-moss-600 px-2 py-1 text-[10px] font-bold text-white">MOST ROBUST</span>}
                  </div>
                  <StabilityDonut value={value} />
                  <p className="mt-4 text-center text-xs text-stone-500">1위 유지 확률</p>
                </div>
              );
            })}
          </div>
          <div className="mt-6 rounded-2xl bg-stone-50 px-4 py-3 text-xs leading-5 text-stone-500">이 수치는 4~6명 규모의 서술적 민감도 분석이며 통계적 유의성을 뜻하지 않습니다.</div>
        </section>

        <section id="conflict" className="card scroll-mt-28 border-l-4 border-l-coral">
          <p className="eyebrow text-coral">03 · Hidden conflict</p>
          <h2 className="section-title">같은 선택 아래, 다른 생각이 숨어 있습니다.</h2>
          <div className="mt-7 space-y-3">
            {analysis.hidden_conflicts.length > 0 ? analysis.hidden_conflicts.map((conflict) => (
              <div key={conflict} className="flex gap-3 rounded-2xl bg-red-50/70 p-4 text-sm leading-6 text-red-950">
                <span className="mt-0.5 text-coral" aria-hidden="true">◆</span>
                <p>{conflict}</p>
              </div>
            )) : <p className="text-sm text-stone-500">뚜렷한 숨은 갈등이 감지되지 않았습니다.</p>}
          </div>
          <div className="mt-6 flex flex-wrap gap-2">
            {room.criteria.map((criterion) => {
              const agreement = analysis.weight_agreement[criterion] ?? "MID";
              return (
                <span key={criterion} className="rounded-full border border-black/5 bg-white px-3 py-2 text-xs font-semibold">
                  {criterion} <span className={`ml-1 rounded-full px-2 py-0.5 ${agreementStyle[agreement]}`}>{agreement}</span>
                </span>
              );
            })}
          </div>
        </section>

        <section id="flip" className="card scroll-mt-28">
          <p className="eyebrow">04 · Flip point</p>
          <h2 className="section-title">결과는 이만큼만 변해도 뒤집힙니다.</h2>
          <div className="mt-7 grid gap-4 md:grid-cols-2">
            {analysis.flip_points.map((flipPoint, index) => (
              <div key={index} className="rounded-3xl bg-ink p-6 text-white">
                {flipPoint.type === "weight" ? (
                  <>
                    <span className="text-xs font-bold uppercase tracking-[0.18em] text-moss-100">Weight shift</span>
                    <div className="mt-5 flex items-baseline gap-3">
                      <strong className="text-4xl tracking-tight">+{Math.round((flipPoint.to - flipPoint.from) * 100)}%p</strong>
                      <span className="text-sm text-white/60">{flipPoint.criterion}</span>
                    </div>
                    <p className="mt-4 text-sm leading-6 text-white/75">
                      {percent(flipPoint.from)}에서 {percent(flipPoint.to)}로 오르면 <strong className="text-white">{flipPoint.new_winner}</strong>가 1위가 됩니다.
                    </p>
                  </>
                ) : (
                  <>
                    <span className="text-xs font-bold uppercase tracking-[0.18em] text-moss-100">Member shift</span>
                    <strong className="mt-5 block text-4xl tracking-tight">1명</strong>
                    <p className="mt-4 text-sm leading-6 text-white/75">{flipPoint.description}</p>
                  </>
                )}
              </div>
            ))}
          </div>
        </section>

        <section className="overflow-hidden rounded-3xl bg-moss-700 p-6 text-white shadow-card sm:p-9">
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-moss-100">05 · Most robust choice</p>
          <div className="mt-4 grid items-end gap-7 md:grid-cols-[1fr_auto]">
            <div>
              <h2 className="text-3xl font-semibold tracking-[-0.04em] sm:text-4xl">조건 변화에 가장 견고한 선택</h2>
              <p className="mt-4 max-w-2xl leading-7 text-white/75">가중치가 달라지는 여러 상황에서 가장 자주 1위를 차지한 옵션입니다. 정답이 아니라, 팀이 검토할 중요한 신호입니다.</p>
            </div>
            <div className="rounded-2xl bg-white px-5 py-4 text-right text-moss-700">
              <span className="block text-xs font-bold uppercase tracking-widest">Robust choice</span>
              <strong className="mt-1 block text-2xl">{analysis.robust_choice}</strong>
            </div>
          </div>
        </section>

        <section className="card">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="eyebrow">Live simulator</p>
              <h2 className="section-title">가중치를 움직여 직접 확인해 보세요.</h2>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-stone-500">서버 요청 없이 현재 브라우저에서 점수와 순위를 즉시 다시 계산합니다. 합계는 자동 정규화됩니다.</p>
            </div>
            <button type="button" className="secondary-button" onClick={() => setLiveWeights(initialWeights)}>팀 평균으로 초기화</button>
          </div>

          {!analysis.mean_scores ? (
            <div className="mt-7 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-900">
              실 API 응답에 <code className="rounded bg-white px-1.5 py-0.5">mean_scores</code>가 없어 시뮬레이터를 표시할 수 없습니다. mock 응답 구조를 참고해 옵션×기준 평균 점수를 추가해 주세요.
            </div>
          ) : (
            <div className="mt-8 grid gap-8 lg:grid-cols-[1fr_1fr]">
              <div className="space-y-6">
                {room.criteria.map((criterion) => (
                  <label key={criterion} className="block">
                    <span className="flex items-center justify-between text-sm font-semibold">
                      <span>{criterion} <span className={`ml-1 rounded-full px-2 py-1 text-[10px] ${agreementStyle[analysis.weight_agreement[criterion] ?? "MID"]}`}>{analysis.weight_agreement[criterion] ?? "MID"}</span></span>
                      <output>{Math.round((normalizedWeights[criterion] ?? 0) * 100)}%</output>
                    </span>
                    <input
                      type="range"
                      min="1"
                      max="100"
                      value={liveWeights[criterion] ?? 1}
                      onChange={(event) => setLiveWeights((current) => ({ ...current, [criterion]: Number(event.target.value) }))}
                      className="slider mt-3"
                      style={sliderFill(liveWeights[criterion] ?? 1, 1, 100)}
                    />
                  </label>
                ))}
                <p className="rounded-xl bg-stone-50 px-3 py-2 text-xs text-stone-500">Tip: ‘구현 가능성’을 올리면 순위가 바뀌는 지점을 볼 수 있어요.</p>
              </div>

              <div className="rounded-3xl bg-stone-50 p-5">
                <div className="flex items-center justify-between gap-3">
                  <h3 className="font-semibold">실시간 순위</h3>
                  {winnerChanged && <span className="animate-pulse rounded-full bg-coral px-3 py-1 text-[11px] font-bold text-white">순위가 뒤집혔어요</span>}
                </div>
                <ol className="mt-4 space-y-3">
                  {liveRanking.map((item, index) => (
                    <li key={item.option} className={`flex items-center gap-3 rounded-2xl border p-4 transition ${index === 0 ? "border-moss-500 bg-white shadow-sm" : "border-transparent bg-white/60"}`}>
                      <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-sm font-bold ${index === 0 ? "bg-moss-600 text-white" : "bg-stone-200 text-stone-500"}`}>{index + 1}</span>
                      <div className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-semibold">{item.option}</span>
                        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-stone-100">
                          <div className="h-full rounded-full bg-moss-500 transition-all" style={{ width: `${Math.max(0, Math.min(100, (item.score / 5) * 100))}%` }} />
                        </div>
                      </div>
                      <strong className="text-lg tabular-nums">{item.score.toFixed(2)}</strong>
                    </li>
                  ))}
                </ol>
                <p className="mt-4 text-right text-xs text-stone-500">5점 만점 가중 평균</p>
              </div>
            </div>
          )}
        </section>

        <section id="discussion" className="card scroll-mt-28">
          <p className="eyebrow">06 · Discussion agenda</p>
          <h2 className="section-title">이제, 이 쟁점만 이야기하세요.</h2>
          <div className="mt-7 grid gap-6 lg:grid-cols-2">
            <div>
              <h3 className="text-sm font-bold text-stone-500">팀 논의 안건</h3>
              <ol className="mt-3 space-y-3">
                {analysis.discussion_agenda.map((agenda, index) => (
                  <li key={agenda} className="flex gap-3 rounded-2xl bg-moss-50 p-4 text-sm leading-6">
                    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-moss-600 text-xs font-bold text-white">{index + 1}</span>
                    <span>{agenda}</span>
                  </li>
                ))}
              </ol>
            </div>
            <div>
              <h3 className="text-sm font-bold text-stone-500">Devil’s Advocate · {analysis.devils_advocate?.target ?? optionShortName(analysis.current_winner)} 반론</h3>
              {analysis.devils_advocate?.challenges?.length ? (
                <ul className="mt-3 space-y-3">
                  {analysis.devils_advocate.challenges.map((challenge) => (
                    <li key={challenge} className="rounded-2xl bg-ink p-4 text-sm leading-6 text-white/85">
                      <span className="mr-2 text-coral">Q.</span>{challenge}
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="mt-3 rounded-2xl bg-stone-50 p-4 text-sm leading-6 text-stone-500">AI 반론을 불러오지 못했습니다. 통계 분석 결과에는 영향이 없습니다.</div>
              )}
            </div>
          </div>
        </section>

        <div className="py-5 text-center">
          <p className="text-2xl font-semibold tracking-[-0.04em]">싱큐 · 합의보다, 더 나은 선택.</p>
          <p className="mt-2 text-sm text-stone-500">싱큐는 결정을 추천하지 않습니다. 결정의 견고성을 보여줄 뿐입니다.</p>
        </div>
      </div>
    </div>
  );
}

export default ResultsPage;
