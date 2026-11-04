import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { JobActivity, StatusPanel } from "./JobActivity";
import { PipelineSteps } from "./PipelineSteps";
import { agoText, formatClock, liveLine, retryWarning } from "./stepProgress";
import type { Job } from "./types";

const T0 = Date.parse("2026-11-02T17:33:44Z");
const base = {
  id: "j", title: "t", mode: "vietsub", status: "processing", stage: "translating", progress: 47,
  updated_at: "2026-11-02T17:34:20Z", ready_count: 0, exported_paths: [], error: null, warnings: [],
  stage_step: "translate", stage_started_at: "2026-11-02T17:33:44Z",
} as unknown as Job;

afterEach(() => { cleanup(); vi.useRealTimers(); });

describe("liveLine", () => {
  it("formats the clock", () => {
    expect(formatClock(42)).toBe("00:42");
    expect(formatClock(725)).toBe("12:05");
    expect(formatClock(3723)).toBe("1:02:03");
    expect(formatClock(-3)).toBe("00:00");
  });
  it("shows batch, size, Gemini note and elapsed time while translating", () => {
    const job = {
      ...base,
      stage_detail: { done: 80, total: 151, unit: "câu", batch: 3, batches: 8, batch_size: 40, note: "đang gửi tới Gemini, chờ trả lời…" },
    } as Job;
    expect(liveLine(job, T0 + 42_000)).toBe("Đang dịch lô 3/8 (40 câu) · đang gửi tới Gemini, chờ trả lời… · 00:42 đã chạy");
  });
  it("shows a 503 retry note", () => {
    const job = {
      ...base,
      stage_detail: { done: 0, total: 151, unit: "câu", batch: 1, batches: 1, batch_size: 151, note: "Gemini lỗi 503, thử lại lần 2/4 sau 5 giây…" },
    } as Job;
    expect(liveLine(job, T0 + 11_000)).toContain("Gemini lỗi 503, thử lại lần 2/4 sau 5 giây…");
  });
  it("falls back to the last worker message for other steps", () => {
    const job = { ...base, stage_step: "analyze", stage_detail: null, activity: [{ t: "x", msg: "Đang đọc chữ trên hình" }] } as Job;
    expect(liveLine(job, T0 + 5_000)).toBe("Đang đọc chữ trên hình · 00:05 đã chạy");
  });
  it("says where a queued job stands and warns when the worker is gone", () => {
    const queued = { ...base, status: "queued", stage_step: null, queue: { position: 1, running_ahead: false, worker_alive: true } } as Job;
    expect(liveLine(queued, T0)).toBe("Đang chờ máy xử lý (vị trí 1)");
    const behind = { ...queued, queue: { position: 2, running_ahead: true, worker_alive: true } } as Job;
    expect(liveLine(behind, T0)).toBe("Đang chờ máy xử lý (vị trí 2) · máy đang chạy tác vụ khác");
    const dead = { ...queued, queue: { position: 1, running_ahead: false, worker_alive: false } } as Job;
    expect(liveLine(dead, T0)).toContain("máy xử lý không phản hồi");
    expect(liveLine({ ...queued, queue: null } as Job, T0)).toBe("Đang chờ máy xử lý…");
  });
  it("is silent when nothing runs", () => {
    expect(liveLine({ ...base, status: "awaiting_review" } as Job, T0)).toBeNull();
  });
  it("says how long ago the last update was", () => {
    expect(agoText("2026-11-02T17:34:20Z", Date.parse("2026-11-02T17:34:20Z"))).toBe("vừa xong");
    expect(agoText("2026-11-02T17:34:20Z", Date.parse("2026-11-02T17:34:32Z"))).toBe("12 giây trước");
    expect(agoText("2026-11-02T17:34:20Z", Date.parse("2026-11-02T17:37:21Z"))).toBe("3 phút trước");
    expect(agoText(undefined, 0)).toBe("");
  });
});

describe("JobActivity", () => {
  beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(T0 + 30_000); });

  it("lists the worker messages (newest first) in the details popup", () => {
    const job = {
      ...base,
      activity: [
        { t: "2026-11-02T17:33:44Z", msg: "Máy xử lý đã nhận tác vụ." },
        { t: "2026-11-02T17:33:45Z", msg: "Lô 1/1 (40 câu): đang gửi tới Gemini, chờ trả lời…" },
      ],
    } as Job;
    render(<JobActivity job={job} />);
    expect(screen.queryByRole("status")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Xem chi tiết/ }));
    expect(screen.getByRole("tab", { name: "Hoạt động (2)" }).getAttribute("aria-selected")).toBe("true");
    const items = [...document.querySelectorAll(".job-activity-log li")].map((li) => li.textContent ?? "");
    expect(items.length).toBe(2);
    expect(items[0]).toContain("Lô 1/1");
    expect(items[1]).toContain("Máy xử lý đã nhận tác vụ.");
  });

  it("adds a third tab with the live error list, count on the button, actions and empty state", () => {
    const onRetry = vi.fn();
    const onJump = vi.fn();
    const item = { key: "tr:a", kind: "translate", step: "Dịch", time: "2026-11-02T17:33:44Z", cue_id: "a", cue_number: 3,
      message: "Gemini không trả bản dịch hợp lệ cho câu này.", actions: ["jump", "edit", "retry", "dismiss"] };
    const errors = { items: [item], count: 1, refresh: vi.fn(), onRetry, onJump, onEditCue: vi.fn() } as never;
    const job = { ...base, activity: [{ t: "2026-11-02T17:33:44Z", msg: "x" }] } as Job;
    const { rerender } = render(<JobActivity job={job} errors={errors} />);
    expect(screen.getByRole("button", { name: /Xem chi tiết · 1/ })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Xem chi tiết/ }));
    expect(screen.getByRole("tab", { name: "Lỗi (1)" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByText("Gemini không trả bản dịch hợp lệ cho câu này.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Câu 3" }));
    expect(onJump).toHaveBeenCalledWith("a");
    fireEvent.click(screen.getByRole("button", { name: "Dịch lại" }));
    expect(onRetry).toHaveBeenCalledWith(["a"]);
    expect(screen.getByRole("button", { name: "Bỏ qua" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Sửa lời Việt" })).toBeTruthy();
    rerender(<JobActivity job={job} errors={{ items: [], count: 0, refresh: vi.fn() } as never} />);
    fireEvent.click(screen.getByRole("tab", { name: "Lỗi (0)" }));
    expect(screen.getByText("Không có lỗi")).toBeTruthy();
  });

  it("keeps the details button after the job finished, and renders nothing when there is nothing to show", () => {
    const done = { ...base, status: "awaiting_review", stage_step: null, activity: [{ t: "2026-11-02T17:33:44Z", msg: "Xong." }] } as Job;
    const { container, rerender } = render(<JobActivity job={done} />);
    expect(screen.getByRole("button", { name: /Xem chi tiết/ })).toBeTruthy();
    rerender(<JobActivity job={{ ...done, activity: [] } as Job} />);
    expect(container.firstChild).toBeNull();
  });
});

describe("StatusPanel", () => {
  beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(T0 + 12_000); });
  const text = () => screen.getByRole("status").textContent ?? "";

  it("shows a queued job once, with queue chip and no repeated words", () => {
    const job = { ...base, status: "queued", stage: "queued", progress: 0, stage_step: null, queue: { position: 1, running_ahead: false, worker_alive: true }, updated_at: "2026-11-02T17:33:56Z" } as Job;
    render(<StatusPanel job={job} onCancel={() => undefined} />);
    expect(text()).toContain("Đang chờ máy xử lý");
    expect(text()).toContain("Hàng đợi: vị trí 1");
    expect(text()).not.toMatch(/Đang chờ · Đang chờ/);
    expect(document.querySelectorAll('[role="status"]').length).toBe(1);
  });

  it("shows batch title, percent, elapsed and updated chips while translating", () => {
    const job = { ...base, progress: 47, updated_at: "2026-11-02T17:33:49Z",
      stage_detail: { done: 0, total: 124, unit: "câu", batch: 1, batches: 1, batch_size: 124 } } as Job;
    render(<StatusPanel job={job} onCancel={() => undefined} />);
    expect(text()).toContain("Đang dịch lô 1/1 · 124 câu");
    expect(text()).toContain("47%");
    expect(text()).toContain("Đã chạy 00:12");
    expect(text()).toContain("Cập nhật 7 giây trước");
    expect(document.querySelector(".status-panel-warn")).toBeNull();
  });

  it("turns a 503 retry note into a soft warning inside the panel and cancels from it", () => {
    const onCancel = vi.fn();
    const job = { ...base, stage_detail: { done: 0, total: 124, unit: "câu", batch: 1, batches: 1, batch_size: 124, note: "Gemini lỗi 503, thử lại lần 2/4 sau 5 giây…" } } as Job;
    render(<StatusPanel job={job} onCancel={onCancel} />);
    expect(document.querySelector(".status-panel-warn")?.textContent).toBe("Gemini quá tải (503) · thử lại 2/4 sau 5 giây");
    expect(text()).not.toContain("thử lại lần");
    fireEvent.click(screen.getByRole("button", { name: "Huỷ" }));
    expect(onCancel).toHaveBeenCalled();
  });

  it("flags a dead worker and renders nothing for finished or failed jobs", () => {
    const dead = { ...base, status: "queued", stage_step: null, queue: { position: 1, running_ahead: false, worker_alive: false } } as Job;
    const { container, rerender } = render(<StatusPanel job={dead} onCancel={() => undefined} />);
    expect(container.querySelector(".status-panel.is-stuck")).not.toBeNull();
    expect(text()).toContain("Máy xử lý không phản hồi");
    rerender(<StatusPanel job={{ ...base, status: "error", error: "Lỗi" } as Job} onCancel={() => undefined} />);
    expect(container.firstChild).toBeNull();
  });

  it("parses retry notes", () => {
    expect(retryWarning("Gemini giới hạn tốc độ (429), thử lại lần 1/3 sau 10 giây…")).toBe("Gemini giới hạn tốc độ (429) · thử lại 1/3 sau 10 giây");
    expect(retryWarning("đang gửi tới Gemini, chờ trả lời…")).toBeNull();
  });
});

describe("PipelineSteps with batches", () => {
  it("includes the batch in the step card", () => {
    vi.useFakeTimers();
    const job = {
      ...base, eta_seconds: 70,
      stage_detail: { done: 40, total: 151, unit: "câu", batch: 2, batches: 4, batch_size: 40 },
    } as Job;
    const { container } = render(<PipelineSteps job={job} cueCount={151} missing={111} />);
    expect([...container.querySelectorAll(".step-meta")][1].textContent).toBe("Đang dịch lô 2/4 · 40/151 câu · còn ~1 phút");
  });
});
