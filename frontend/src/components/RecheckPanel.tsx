import { FormEvent, useEffect, useState } from "react";
import { api } from "../api";
import { allocatePercentages, rebalancePercentages } from "../calculations";
import type { AnalysisResponse, DecisionRecheck, Room, WeightFlipPoint } from "../types";

interface RecheckPanelProps {
  room: Room;
  analysis: AnalysisResponse;
  onDecisionRecorded: () => void;
}

function percent(value: number) {
  return `${Math.round(value * 100)}%`;
}

function sliderFill(value: number, max: number) {
  return { background: `linear-gradient(to right, #3b5e48 ${(value / max) * 100}%, #e7e5e4 ${(value / max) * 100}%)` };
}

function closestWeightFlip(analysis: AnalysisResponse): WeightFlipPoint | undefined {
  return analysis.flip_points
    .filter((item): item is WeightFlipPoint => item.type === "weight")
    .sort((left, right) => Math.abs((left.to - left.from)) - Math.abs((right.to - right.from)))[0];
}

function flipChange(item: WeightFlipPoint | undefined) {
  if (!item) return "가까운 뒤집힘 조건 없음";
  const change = Math.round((item.to - item.from) * 100);
  return `${item.criterion}: ${change >= 0 ? "+" : ""}${change}%p`;
}

function RecheckPanel({ room, analysis, onDecisionRecorded }: RecheckPanelProps) {
  const initialWeights = allocatePercentages(
    Object.fromEntries(room.criteria.map((criterion) => [criterion, (analysis.team_weights[criterion] ?? 0) * 100])),
    room.criteria,
    100,
    1,
  );
  const [weights, setWeights] = useState(initialWeights);
  const [finalChoice, setFinalChoice] = useState(analysis.current_winner ?? room.options[0]);
  const [consensusNote, setConsensusNote] = useState("");
  const [recheck, setRecheck] = useState<DecisionRecheck>();
  const [decisionRecordExists, setDecisionRecordExists] = useState(false);
  const [loading, setLoading] = useState(false);
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState("");
  const [recordError, setRecordError] = useState("");

  useEffect(() => {
    let active = true;
    void api.getDecisionRecord(room.code)
      .then(() => active && setDecisionRecordExists(true))
      .catch(() => active && setDecisionRecordExists(false));
    void api.getDecisionRecheck(room.code).then(setRecheck).catch(() => undefined);
    return () => { active = false; };
  }, [room.code]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      setRecheck(await api.createDecisionRecheck(room.code, {
        weights,
        final_choice: finalChoice,
        consensus_note: consensusNote.trim(),
      }));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Re-check 결과를 저장하지 못했습니다.");
    } finally {
      setLoading(false);
    }
  };

  const saveDecisionRecord = async () => {
    if (!recheck) return;
    setRecording(true);
    setRecordError("");
    try {
      await api.createDecisionRecord(room.code, {
        final_choice: recheck.final_choice,
        final_reason: recheck.consensus_note,
      });
      setDecisionRecordExists(true);
      onDecisionRecorded();
    } catch (cause) {
      setRecordError(cause instanceof Error ? cause.message : "최종 결정을 기록하지 못했습니다.");
    } finally {
      setRecording(false);
    }
  };

  if (recheck) {
    const winnerChanged = recheck.before.current_winner !== recheck.after.current_winner;
    const robustChanged = recheck.before.robust_choice !== recheck.after.robust_choice;
    return (
      <div className="mt-6 space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-2xl bg-stone-50 p-4"><span className="text-xs text-stone-500">논의 전</span><strong className="mt-1 block">{recheck.before.current_winner}</strong><span className="text-xs text-stone-500">견고한 선택 · {recheck.before.robust_choice}</span></div>
          <div className="rounded-2xl bg-moss-50 p-4"><span className="text-xs text-moss-700">논의 후</span><strong className="mt-1 block text-moss-800">{recheck.after.current_winner}</strong><span className="text-xs text-stone-500">견고한 선택 · {recheck.after.robust_choice}</span></div>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          {Object.entries(recheck.after.stability).map(([option, value]) => {
            const before = recheck.before.stability[option] ?? 0;
            return <div key={option} className="rounded-2xl border border-black/5 bg-white p-4 text-sm"><div className="flex justify-between gap-3"><strong>{option}</strong><span>{percent(value)} <span className="text-stone-400">({value - before >= 0 ? "+" : ""}{Math.round((value - before) * 100)}%p)</span></span></div></div>;
          })}
        </div>
        <div className="rounded-2xl bg-ink p-4 text-sm leading-6 text-white/80">
          <p>Flip Point {recheck.before.flip_points.length}개 → {recheck.after.flip_points.length}개 · {winnerChanged || robustChanged ? "선택 결과가 달라졌습니다." : "선택 결과는 유지되었습니다."}</p>
          <p className="mt-2">가장 가까운 weight Flip Point · 논의 전 {flipChange(closestWeightFlip(recheck.before))} → 논의 후 {flipChange(closestWeightFlip(recheck.after))}</p>
        </div>
        <div className="rounded-2xl bg-stone-50 p-4 text-sm leading-6"><strong>최종 선택 · {recheck.final_choice}</strong><p className="mt-2 whitespace-pre-wrap text-stone-600">{recheck.consensus_note}</p></div>
        {decisionRecordExists ? (
          <p className="rounded-2xl bg-moss-50 p-4 text-sm font-semibold text-moss-800">최종 결정이 기록되었습니다.</p>
        ) : (
          <div className="space-y-2">
            <button type="button" className="primary-button" disabled={recording} onClick={() => void saveDecisionRecord()}>{recording ? "기록 중…" : "이 결정 확정하고 기록하기"}</button>
            {recordError && <p className="text-sm font-semibold text-red-700" role="alert">{recordError}</p>}
            <p className="text-xs text-stone-500">재검증에 입력한 최종 선택과 합의 메모가 그대로 기록됩니다.</p>
          </div>
        )}
      </div>
    );
  }

  const maximum = 100 - Math.max(0, room.criteria.length - 1);
  return (
    <form onSubmit={submit} className="mt-6 space-y-5">
      <div className="space-y-5">
        {room.criteria.map((criterion) => (
          <label key={criterion} className="block">
            <span className="flex items-center justify-between text-sm font-semibold"><span>{criterion}</span><output>{weights[criterion] ?? 1}%</output></span>
            <input type="range" min="1" max={maximum} value={weights[criterion] ?? 1} onChange={(event) => setWeights((current) => rebalancePercentages(current, room.criteria, criterion, Number(event.target.value)))} className="slider mt-3" style={sliderFill(weights[criterion] ?? 1, maximum)} />
          </label>
        ))}
      </div>
      <p className="rounded-xl bg-stone-50 px-3 py-2 text-xs text-stone-500">수정 가중치 합계 {Object.values(weights).reduce((sum, value) => sum + value, 0)}%</p>
      <fieldset><legend className="text-sm font-bold text-stone-600">논의 후 최종 선택</legend><div className="mt-3 grid gap-2 sm:grid-cols-2">{room.options.map((option) => <label key={option} className={`cursor-pointer rounded-2xl border p-3 text-sm ${finalChoice === option ? "border-moss-500 bg-moss-50 font-semibold" : "border-black/10 bg-stone-50"}`}><input className="mr-2" type="radio" name="recheck-choice" checked={finalChoice === option} onChange={() => setFinalChoice(option)} />{option}</label>)}</div></fieldset>
      <label className="block text-sm font-bold text-stone-600">합의 메모<textarea className="mt-2 min-h-28 w-full rounded-2xl border border-black/10 bg-stone-50 px-4 py-3 font-normal leading-6" value={consensusNote} onChange={(event) => setConsensusNote(event.target.value)} maxLength={2000} required placeholder="논의에서 수정한 기준과 감수하기로 한 위험을 남겨 주세요." /></label>
      {error && <p className="text-sm font-semibold text-red-700" role="alert">{error}</p>}
      <button type="submit" className="primary-button" disabled={loading || !consensusNote.trim()}>{loading ? "재계산 중…" : "논의 결과 다시 확인하기"}</button>
    </form>
  );
}

export default RecheckPanel;
