import type { Job, StageStep } from "./types";

/** Vietnamese duration: "<1 phút", "~45 giây", "~3 phút", "~1 giờ 5 phút". */
export function formatDuration(seconds: number): string {
  const s = Math.max(0, seconds);
  if (s < 5) return "<1 phút";
  if (s < 60) return `~${Math.min(55, Math.round(s / 5) * 5)} giây`;
  const minutes = Math.round(s / 60);
  if (minutes < 60) return `~${minutes} phút`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m ? `~${h} giờ ${m} phút` : `~${h} giờ`;
}

/** Remaining seconds for the running step, ticking down client-side. */
export function remainingSeconds(job: Job, nowMs: number, receivedAtMs: number): number | null {
  if (typeof job.eta_seconds === "number") {
    return Math.max(0, job.eta_seconds - Math.max(0, (nowMs - receivedAtMs) / 1000));
  }
  const step = job.stage_step;
  const estimate = step ? job.stage_estimates?.[step]?.seconds : undefined;
  const started = job.stage_started_at ? Date.parse(job.stage_started_at) : NaN;
  if (typeof estimate === "number" && Number.isFinite(started)) {
    return Math.max(0, estimate - (nowMs - started) / 1000);
  }
  return null;
}

export interface StepMeta {
  text: string;
  state: "running" | "pending" | "done";
  /** estimate is a built-in default guess, not learned from history */
  guess?: boolean;
  progress?: { done: number; total: number };
}

export function runningMeta(job: Job, remaining: number | null): StepMeta {
  const detail = job.stage_detail;
  const eta = remaining === null ? "" : remaining < 1 ? " · sắp xong" : ` · còn ${formatDuration(remaining)}`;
  if (job.stage_step === "translate" && detail && detail.total > 0) {
    return {
      text: `Đang dịch ${detail.done}/${detail.total} ${detail.unit || "câu"}${eta}`,
      state: "running",
      progress: { done: detail.done, total: detail.total },
    };
  }
  return { text: `Đang xử lý${eta}`, state: "running" };
}

export function pendingMeta(job: Job, step: StageStep): { text: string; guess: boolean } | null {
  const estimate = job.stage_estimates?.[step];
  if (!estimate || !(estimate.seconds >= 0)) return null;
  const guess = estimate.source === "default";
  return { text: `Ước tính ${formatDuration(estimate.seconds)}${guess ? " (ước lượng)" : ""}`, guess };
}
