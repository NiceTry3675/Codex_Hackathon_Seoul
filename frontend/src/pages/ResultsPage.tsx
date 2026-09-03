import { useEffect, useMemo, useState } from "react";
import DebatePanel from "../components/DebatePanel";
import type { Agreement, AnalysisResponse, Room } from "../types";

interface ResultsPageProps {
  analysis: AnalysisResponse;
  room: Room;
  /** 공방 판정이 끝난 뒤 논의 안건을 갱신하기 위해 분석을 다시 받는다. */
  onRefreshAnalysis: () => Promise<void>;
}

const agreementStyle: Record<Agreement, string> = {
  HIGH: "bg-moss-100 text-moss-700",
  MID: "bg-amber-100 text-amber-800",
  LOW: "bg-red-100 text-red-700",
};

const agreementLabel: Record<Agreement, string> = {
  HIGH: "의견이 비슷해요",
  MID: "일부 차이가 있어요",
  LOW: "의견 차이가 커요",
};

const NEARBY_FLIP_THRESHOLD = 0.15;

function percent(value: number) {
  return `${Math.round(value * 100)}%`;
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

function ResultsPage({ analysis, room, onRefreshAnalysis }: ResultsPageProps) {
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
  const nearbyFlipPoints = analysis.flip_points.filter(
    (item) => item.type === "member" || Math.abs(item.to - item.from) <= NEARBY_FLIP_THRESHOLD,
  );
  const theoreticalFlipPoints = analysis.flip_points.filter(
    (item) => item.type === "weight" && Math.abs(item.to - item.from) > NEARBY_FLIP_THRESHOLD,
  );

  return (
    <div className="pb-10">
      <section className="border-b border-black/5 bg-sand">
        <div className="mx-auto max-w-5xl px-4 py-14 text-center sm:px-6 sm:py-20">
          <p className="eyebrow">Step 03 · Decision stress test</p>
          <h1 className="mt-3 text-4xl font-semibold tracking-[-0.055em] sm:text-6xl">현재 결과는 얼마나 견고할까요?</h1>
          <p className="mx-auto mt-5 max-w-2xl text-lg leading-8 text-stone-600">
            현재 1위는 <strong className="text-ink">{analysis.current_winner}</strong>입니다. 하지만 조건이 조금만 달라져도 같은 결과일까요?
          </p>
          <div className="mt-8 flex flex-wrap justify-center gap-2 text-xs font-semibold text-stone-500">
            <a href="#votes" className="rounded-full bg-white px-3 py-2 hover:text-ink">득표</a>
            <a href="#stability" className="rounded-full bg-white px-3 py-2 hover:text-ink">안정성</a>
            <a href="#conflict" className="rounded-full bg-white px-3 py-2 hover:text-ink">숨은 갈등</a>
            <a href="#flip" className="rounded-full bg-white px-3 py-2 hover:text-ink">뒤집힘 조건</a>
            <a href="#debate" className="rounded-full bg-white px-3 py-2 hover:text-ink">AI 공방</a>
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
          <p className="mt-6 text-sm text-stone-500">득표와 조건 변화에 대한 견고함은 서로 다를 수 있습니다.</p>
        </section>

        <section id="stability" className="card scroll-mt-28">
          <p className="eyebrow">02 · Decision stability</p>
          <h2 className="section-title">가중치가 흔들리면 결과도 흔들릴까요?</h2>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-stone-500">팀의 기준 비중을 조금씩 바꿨을 때 각 선택지가 1위를 유지한 비율입니다.</p>
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
          <details className="mt-6 rounded-2xl bg-stone-50 px-4 py-3 text-xs leading-5 text-stone-500">
            <summary className="cursor-pointer font-semibold">계산 방법 보기</summary>
            <p className="mt-2">팀 평균 주변의 여러 가중치 조합을 반복 계산한 설명용 지표이며, 통계적 유의성을 뜻하지 않습니다.</p>
          </details>
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
          <p className="mt-6 text-xs font-bold text-stone-500">{analysis.current_winner}에 대한 기준별 평가 합의도</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {room.criteria.map((criterion) => {
              const agreement = analysis.score_agreement[analysis.current_winner]?.[criterion] ?? "MID";
              return (
                <span key={criterion} className="rounded-full border border-black/5 bg-white px-3 py-2 text-xs font-semibold">
                  {criterion} <span className={`ml-1 rounded-full px-2 py-0.5 ${agreementStyle[agreement]}`}>{agreementLabel[agreement]}</span>
                </span>
              );
            })}
          </div>
          <p className="mt-3 text-xs text-stone-500">이 표시는 기준의 중요도가 아니라, 참여자들의 평가가 얼마나 비슷한지를 뜻합니다.</p>
        </section>

        <section id="flip" className="card scroll-mt-28">
          <p className="eyebrow">04 · Flip point</p>
          <h2 className="section-title">가까운 뒤집힘 조건을 확인하세요.</h2>
          {nearbyFlipPoints.length === 0 && (
            <p className="mt-5 rounded-2xl bg-moss-50 p-4 text-sm font-semibold text-moss-800">현재 결과는 가중치 변화에 비교적 견고합니다.</p>
          )}
          <div className="mt-7 grid gap-4 md:grid-cols-2">
            {nearbyFlipPoints.map((flipPoint, index) => (
              <div key={index} className="rounded-3xl bg-ink p-6 text-white">
                {flipPoint.type === "weight" ? (
                  <>
                    <span className="text-xs font-bold uppercase tracking-[0.18em] text-moss-100">Weight shift</span>
                    <div className="mt-5 flex items-baseline gap-3">
                      <strong className="text-4xl tracking-tight">{Math.round((flipPoint.to - flipPoint.from) * 100)}%p</strong>
                      <span className="text-sm text-white/60">{flipPoint.criterion}</span>
                    </div>
                    <p className="mt-4 text-sm leading-6 text-white/75">
                      {percent(flipPoint.from)}에서 {percent(flipPoint.to)}로 바뀌면 <strong className="text-white">{flipPoint.new_winner}</strong>가 1위가 됩니다.
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
          {theoreticalFlipPoints.length > 0 && (
            <details className="mt-5 rounded-2xl border border-black/10 bg-stone-50 p-4 text-sm text-stone-600">
              <summary className="cursor-pointer font-semibold">이론적 뒤집힘 포인트 {theoreticalFlipPoints.length}개 보기</summary>
              <ul className="mt-3 space-y-2">
                {theoreticalFlipPoints.map((item) => item.type === "weight" && (
                  <li key={`${item.criterion}-${item.to}`}>
                    {item.criterion}: {percent(item.from)} → {percent(item.to)}일 때 {item.new_winner} 1위
                  </li>
                ))}
              </ul>
            </details>
          )}
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
                      <span>{criterion} <span className={`ml-1 rounded-full px-2 py-1 text-[10px] ${agreementStyle[analysis.weight_agreement[criterion] ?? "MID"]}`}>{agreementLabel[analysis.weight_agreement[criterion] ?? "MID"]}</span></span>
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

        <section id="debate" className="card scroll-mt-28">
          <p className="eyebrow">06 · Devil's Advocate</p>
          <h2 className="section-title">AI가 결정을 공격합니다. 팀이 방어하세요.</h2>
          <DebatePanel roomCode={room.code} fallbackAdvocate={analysis.devils_advocate} onCompleted={onRefreshAnalysis} />
        </section>

        <section id="discussion" className="card scroll-mt-28">
          <p className="eyebrow">07 · Discussion agenda</p>
          <h2 className="section-title">이제, 이 쟁점만 이야기하세요.</h2>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-stone-500">통계가 찾은 뒤집힘 조건과 숨은 갈등, 그리고 공방에서 해소되지 않은 쟁점입니다.</p>
          <ol className="mt-6 space-y-3">
            {analysis.discussion_agenda.map((agenda, index) => (
              <li key={agenda} className="flex gap-3 rounded-2xl bg-moss-50 p-4 text-sm leading-6">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-moss-600 text-xs font-bold text-white">{index + 1}</span>
                <span>{agenda}</span>
              </li>
            ))}
          </ol>
        </section>

      </div>
    </div>
  );
}

export default ResultsPage;
