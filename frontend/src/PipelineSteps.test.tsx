import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PipelineSteps } from "./PipelineSteps";
import { formatDuration, remainingSeconds } from "./stepProgress";
import type { Job } from "./types";

const base = {
  id: "j", title: "t", mode: "vietsub", status: "processing", stage: "translating", progress: 47,
  updated_at: "u1", ready_count: 0, exported_paths: [], error: null,
} as unknown as Job;
const estimates = {
  analyze: { seconds: 60, source: "history" },
  translate: { seconds: 125, source: "default" },
  render: { seconds: 3900, source: "history" },
} as const;

afterEach(() => { cleanup(); vi.useRealTimers(); });
const metas = (c: HTMLElement) => [...c.querySelectorAll(".step-meta")].map((e) => e.textContent);

describe("formatDuration", () => {
  it("formats Vietnamese durations", () => {
    expect(formatDuration(2)).toBe("<1 phút");
    expect(formatDuration(45)).toBe("~45 giây");
    expect(formatDuration(59)).toBe("~55 giây");
    expect(formatDuration(60)).toBe("~1 phút");
    expect(formatDuration(125)).toBe("~2 phút");
    expect(formatDuration(3900)).toBe("~1 giờ 5 phút");
    expect(formatDuration(7200)).toBe("~2 giờ");
  });
  it("counts the ETA down from the time it was received and never below 0", () => {
    const job = { ...base, eta_seconds: 10 } as Job;
    expect(remainingSeconds(job, 4000, 0)).toBe(6);
    expect(remainingSeconds(job, 60000, 0)).toBe(0);
  });
});

describe("PipelineSteps", () => {
  beforeEach(() => vi.useFakeTimers());
  it("shows live translate progress, ETA and a progress bar on the current step; estimates on pending steps", () => {
    const job = {
      ...base, stage_step: "translate", stage_detail: { done: 21, total: 40, unit: "câu" },
      eta_seconds: 70, stage_estimates: estimates,
    } as Job;
    const { container } = render(<PipelineSteps job={job} cueCount={40} missing={19} />);
    const m = metas(container);
    expect(m[1]).toBe("Đang dịch 21/40 câu · còn ~1 phút");
    const bar = container.querySelector("progress.step-progress") as HTMLProgressElement;
    expect(bar.max).toBe(40);
    expect(bar.value).toBe(21);
    expect(m[0]).toBe("40 câu lời gốc"); // done step keeps its status
    expect(m[3]).toBe("Ước tính ~1 giờ 5 phút"); // pending, learned from history
    expect(container.querySelector(".step-meta.is-guess")).toBeNull();
  });
  it("marks default-source estimates as a guess", () => {
    const job = { ...base, status: "awaiting_review", stage_step: null, stage_estimates: estimates } as Job;
    const { container } = render(<PipelineSteps job={job} cueCount={0} missing={0} />);
    const m = metas(container);
    expect(m[0]).toBe("Ước tính ~1 phút");
    expect(m[1]).toBe("Ước tính ~2 phút (ước lượng)");
    expect(container.querySelectorAll(".step-meta.is-guess").length).toBe(1);
    expect(container.querySelector("progress")).toBeNull();
  });
  it("ticks the ETA every second and says 'sắp xong' at 0", () => {
    const job = { ...base, stage_step: "render", eta_seconds: 3, stage_estimates: estimates } as Job;
    const { container } = render(<PipelineSteps job={job} cueCount={5} missing={0} />);
    expect(metas(container)[3]).toBe("Đang xử lý · còn <1 phút");
    act(() => { vi.advanceTimersByTime(4000); });
    expect(metas(container)[3]).toBe("Đang xử lý · sắp xong");
  });
  it("uses the synthesize estimate on the voice step for dub jobs", () => {
    const job = { ...base, mode: "dub", status: "awaiting_review", stage_estimates: { synthesize: { seconds: 300, source: "history" } } } as Job;
    const { container } = render(<PipelineSteps job={job} cueCount={10} missing={0} />);
    expect(metas(container)[2]).toBe("Ước tính ~5 phút");
  });
});
