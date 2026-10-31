import type { Cue, Job } from "./types";
import { mediaUrl } from "./api";
export type Page = "editor" | "projects" | "collections" | "voices" | "queue" | "settings";
export function parseRoute(hash: string): { page: Page; jobId: string | null } {
  const [page, query] = hash.replace(/^#/, "").split("?");
  return {
    page: ["editor", "projects", "collections", "voices", "queue", "settings"].includes(page)
      ? (page as Page)
      : "editor",
    jobId: new URLSearchParams(query).get("job"),
  };
}
export function navigate(page: Page, jobId?: string | null) {
  location.hash = page + (jobId ? `?job=${encodeURIComponent(jobId)}` : "");
}
export function editCue(cues: Cue[], id: string, patch: Partial<Cue>): Cue[] {
  return cues.map((cue) => (cue.id === id ? { ...cue, ...patch } : cue));
}
export function playerSource(job: Job, view: "source" | "output") {
  return mediaUrl(view === "source" ? job.source_url_path : job.output_url);
}
export function validateCues(
  cues: Cue[],
  duration: number | null,
): string | null {
  for (const cue of cues) {
    if (
      !Number.isFinite(cue.start) ||
      !Number.isFinite(cue.end) ||
      cue.start < 0 ||
      cue.end <= cue.start ||
      (duration && cue.end > duration)
    )
      return "Thời gian câu phải nằm trong video, kết thúc sau bắt đầu.";
  }
  return null;
}
export const time = (seconds: number | null | undefined) => {
  const value = Math.max(0, seconds || 0);
  return `${Math.floor(value / 60)
    .toString()
    .padStart(2, "0")}:${(value % 60).toFixed(2).padStart(5, "0")}`;
};
export const statusLabels: Record<string, string> = {
  created: "Đã tạo",
  processing: "Đang xử lý",
  uploaded: "Đã tải lên",
  new: "Mới tạo",
  queued: "Đang chờ",
  running: "Đang xử lý",
  analyzing: "Đang phân tích",
  rendering: "Đang xuất",
  synthesizing: "Đang sinh giọng",
  awaiting_review: "Sẵn sàng chỉnh sửa",
  ready: "Sẵn sàng",
  completed: "Hoàn tất",
  done: "Hoàn tất",
  error: "Có lỗi",
  failed: "Có lỗi",
  cancelled: "Đã huỷ",
  canceled: "Đã huỷ",
};
export const stageLabels: Record<string, string> = {
  ...statusLabels,
  separating: "Tách giọng và nhạc nền",
  separate: "Tách giọng và nhạc nền",
  transcribing: "Nhận dạng lời gốc",
  transcribe: "Nhận dạng lời gốc",
  ocr: "Tìm phụ đề và chữ trên hình",
  erase: "Xoá phụ đề gốc trên hình",
  translate: "Dịch lời Việt",
  translating: "Đang dịch tiếng Việt",
  refs: "Chuẩn bị mẫu giọng",
  gen: "Sinh giọng Việt",
  pick: "Kiểm tra lại từng câu",
  placing: "Căn thời gian giọng",
};
export const isBusy = (job: Job) =>
  [
    "queued",
    "running",
    "analyzing",
    "rendering",
    "synthesizing",
    "preparing",
    "processing",
  ].includes(job.status);
export const modeLabels = {
  dub: "Lồng tiếng",
  tm: "Thuyết minh",
  vietsub: "Vietsub",
};
