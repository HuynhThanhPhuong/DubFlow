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
    const batch = detail.batch && detail.batches ? `lô ${detail.batch}/${detail.batches} · ` : "";
    return {
      text: `Đang dịch ${batch}${detail.done}/${detail.total} ${detail.unit || "câu"}${eta}`,
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

/** "00:42", "12:05", "1:02:03" */
export function formatClock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const pad = (n: number) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s % 60)}` : `${pad(m)}:${pad(s % 60)}`;
}

/** One line telling the user what the worker is doing right now; null when nothing is running. */
export function liveLine(job: Job, nowMs: number): string | null {
  if (job.deleting) return "Đang xóa…";
  if (job.stopping) return "Đang dừng…";
  if (job.status === "queued") {
    const q = job.queue;
    if (!q) return "Đang chờ máy xử lý…";
    const parts = [`Đang chờ máy xử lý (vị trí ${q.position})`];
    if (q.running_ahead) parts.push("máy đang chạy tác vụ khác");
    if (!q.worker_alive) parts.push("máy xử lý không phản hồi, hãy khởi động lại DubFlow");
    return parts.join(" · ");
  }
  if (job.status !== "processing") return null;
  const started = job.stage_started_at ? Date.parse(job.stage_started_at) : NaN;
  const elapsed = Number.isFinite(started) ? ` · ${formatClock((nowMs - started) / 1000)} đã chạy` : "";
  const detail = job.stage_detail;
  if (job.stage_step === "translate" && detail) {
    const head =
      detail.batch && detail.batches
        ? `Đang dịch lô ${detail.batch}/${detail.batches}${detail.batch_size ? ` (${detail.batch_size} câu)` : ""}`
        : `Đang dịch ${detail.done}/${detail.total} ${detail.unit || "câu"}`;
    return `${head}${detail.note ? ` · ${detail.note}` : ""}${elapsed}`;
  }
  const last = job.activity?.length ? job.activity[job.activity.length - 1].msg : "";
  return `${last || "Đang xử lý"}${elapsed}`;
}

/** "vừa xong", "12 giây trước", "3 phút trước" */
export function agoText(iso: string | undefined, nowMs: number): string {
  const t = iso ? Date.parse(iso) : NaN;
  if (!Number.isFinite(t)) return "";
  const s = Math.max(0, Math.round((nowMs - t) / 1000));
  if (s < 3) return "vừa xong";
  if (s < 60) return `${s} giây trước`;
  return `${Math.floor(s / 60)} phút trước`;
}
