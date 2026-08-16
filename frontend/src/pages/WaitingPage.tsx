import { useEffect, useState } from "react";
import { api } from "../api";
import type { Room } from "../types";

interface WaitingPageProps {
  room: Room;
  loading: boolean;
  onRoomChange: (room: Room) => void;
  onAnalyze: () => Promise<void>;
}

function WaitingPage({ room, loading, onRoomChange, onAnalyze }: WaitingPageProps) {
  const [refreshing, setRefreshing] = useState(false);

  const refresh = async () => {
    setRefreshing(true);
    try {
      onRoomChange(await api.getRoom(room.code));
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => {
    if (room.is_complete) return;
    const timer = window.setInterval(() => {
      void api.getRoom(room.code).then(onRoomChange).catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [room.code, room.is_complete, onRoomChange]);

  const expectedMembers = Math.max(room.expected_members, 1);
  const progress = Math.min(100, (room.submission_count / expectedMembers) * 100);

  return (
    <div className="mx-auto flex min-h-[calc(100vh-150px)] max-w-3xl items-center px-4 py-12 sm:px-6">
      <section className="card w-full overflow-hidden text-center">
        <p className="eyebrow">Step 02 · Waiting room</p>
        <h1 className="mt-3 text-4xl font-semibold tracking-[-0.05em] sm:text-5xl">
          {room.is_complete ? "모두 준비됐어요." : "조금만 기다려 주세요."}
        </h1>
        <p className="mx-auto mt-4 max-w-lg leading-7 text-stone-600">
          개별 답변은 공개하지 않습니다. 모두의 입력이 완료되면, 팀의 분석 결과를 함께 확인할 수 있어요.
        </p>

        <div className="mx-auto mt-9 max-w-xl rounded-3xl bg-stone-50 p-6 sm:p-8">
          <div className="flex items-end justify-center gap-2">
            <strong className="text-6xl font-semibold tracking-[-0.06em] text-ink">{room.submission_count}</strong>
            <span className="pb-2 text-lg text-stone-400">/ {expectedMembers}명</span>
          </div>
          <div className="mt-6 h-2.5 overflow-hidden rounded-full bg-stone-200" aria-label={`제출 진행률 ${Math.round(progress)}%`}>
            <div className="h-full rounded-full bg-moss-600 transition-all duration-500" style={{ width: `${progress}%` }} />
          </div>
          <div className="mt-5 flex flex-wrap justify-center gap-3" aria-hidden="true">
            {Array.from({ length: expectedMembers }, (_, index) => (
              <span
                key={index}
                className={`flex h-11 w-11 items-center justify-center rounded-full text-sm font-bold transition ${
                  index < room.submission_count
                    ? "bg-moss-600 text-white"
                    : "border border-dashed border-stone-300 bg-white text-stone-300"
                }`}
              >
                {index < room.submission_count ? "✓" : index + 1}
              </span>
            ))}
          </div>
        </div>

        <div className="mt-6 flex items-center justify-center gap-2 text-sm text-stone-500">
          {!room.is_complete && <span className="h-2 w-2 animate-pulse rounded-full bg-amber-500" />}
          {room.is_complete ? "입력이 모두 완료되었습니다." : "3초마다 제출 인원을 확인하고 있어요."}
        </div>

        <div className="mt-8 flex flex-col justify-center gap-3 sm:flex-row">
          <button type="button" className="secondary-button" onClick={() => void refresh()} disabled={refreshing || loading}>
            {refreshing ? "새로고침 중…" : "지금 새로고침"}
          </button>
          <button type="button" className="primary-button" onClick={() => void onAnalyze()} disabled={!room.is_complete || loading}>
            {loading ? "분석 중…" : room.is_complete ? "결정 안정성 분석하기" : `${expectedMembers - room.submission_count}명 더 필요해요`}
          </button>
        </div>

        <div className="mt-9 border-t border-black/5 pt-6 text-sm text-stone-500">
          <span className="font-mono font-bold tracking-[0.18em] text-ink">{room.code}</span>
          <span className="mx-2 text-stone-300">·</span>
          이 코드를 팀원에게 공유하세요.
        </div>
      </section>
    </div>
  );
}

export default WaitingPage;
