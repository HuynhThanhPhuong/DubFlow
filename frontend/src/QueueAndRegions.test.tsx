import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";

const base = {
  mode: "vietsub", voice_id: null, source_url: null, error: null, duration: 10, width: 1920, height: 1080,
  created_at: "2026-10-29", updated_at: "2026-10-29", poster_url: null, output_url: null, warnings: [],
  cue_count: 0, ready_count: 0, progress: 10, source_url_path: "/api/jobs/a/source",
};
const running = { ...base, id: "a", title: "Đang chạy", filename: "a.mp4", status: "processing", stage: "ocr" };
const idle = { ...base, id: "b", title: "Đã xong", filename: "b.mp4", status: "error", stage: "error" };

function stub(calls: string[], jobs: unknown[], extra: (path: string, init: RequestInit) => Response | undefined = () => undefined) {
  vi.stubGlobal("fetch", vi.fn(async (path: string, init: RequestInit = {}) => {
    calls.push(`${init.method || "GET"} ${path}`);
    const custom = extra(path, init);
    if (custom) return custom;
    let response: unknown = [];
    if (path === "/api/health") response = { status: "ok", queue_backend: "sqlite", capabilities: {}, warnings: [] };
    else if (path === "/api/settings") response = { output_dir: "D:/Exports", organize_by_collection: true };
    else if (path === "/api/jobs") response = jobs;
    else if (path.startsWith("/api/jobs/") && !path.includes("/", 10)) response = (jobs as { id: string }[]).find((j) => path.endsWith(j.id));
    return new Response(JSON.stringify(response ?? {}), { status: 200 });
  }));
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); location.hash = ""; });

it("queue: per-row Dừng only for busy jobs, calls cancel and refreshes", async () => {
  location.hash = "#queue";
  const calls: string[] = [];
  stub(calls, [running, idle]);
  render(<App />);
  await screen.findByText("Đang chạy");
  expect(screen.getAllByRole("button", { name: "Dừng" }).length).toBe(1);
  fireEvent.click(screen.getByRole("button", { name: "Dừng" }));
  await waitFor(() => expect(calls).toContain("POST /api/jobs/a/cancel"));
  await waitFor(() => expect(calls.filter((c) => c === "GET /api/jobs").length).toBeGreaterThan(1));
});

it("queue: Dừng tất cả asks first, then posts stop-all", async () => {
  location.hash = "#queue";
  const calls: string[] = [];
  stub(calls, [running, idle]);
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<App />);
  await screen.findByText("Đang chạy");
  fireEvent.click(screen.getByRole("button", { name: "Dừng tất cả" }));
  expect(confirm).toHaveBeenCalledWith("Dừng mọi tác vụ đang chạy và đang chờ?");
  expect(calls).not.toContain("POST /api/tasks/stop-all");
  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", { name: "Dừng tất cả" }));
  await waitFor(() => expect(calls).toContain("POST /api/tasks/stop-all"));
});

it("editor: awaiting_regions shows the picker, Lưu & phân tích saves then analyzes", async () => {
  location.hash = "#editor?job=a";
  const calls: string[] = [];
  const job = { ...base, id: "a", title: "Mới", filename: "a.mp4", status: "awaiting_regions", stage: "awaiting_regions", analysis_regions: null };
  let body: unknown;
  stub(calls, [job], (path, init) => {
    if (path === "/api/jobs/a/analysis-regions") { body = JSON.parse(String(init.body)); return new Response("{}", { status: 200 }); }
    if (path === "/api/jobs/a/analyze") return new Response(JSON.stringify({ ...job, status: "queued" }), { status: 200 });
    return undefined;
  });
  render(<App />);
  await screen.findByRole("region", { name: "Chọn vùng phân tích" });
  fireEvent.click(screen.getByLabelText("Video không có sub cứng"));
  fireEvent.click(screen.getByRole("button", { name: "Lưu & phân tích" }));
  await waitFor(() => expect(calls).toContain("POST /api/jobs/a/analyze"));
  expect(body).toEqual({ no_hard_subs: true, subtitle: null, logos: [], screen_text: [] });
  expect(calls.indexOf("PUT /api/jobs/a/analysis-regions")).toBeLessThan(calls.indexOf("POST /api/jobs/a/analyze"));
});

it("editor: a 409 from analyze opens the picker with the server message", async () => {
  location.hash = "#editor?job=a";
  const calls: string[] = [];
  const job = { ...base, id: "a", title: "Cũ", filename: "a.mp4", status: "awaiting_review", stage: "awaiting_review" };
  stub(calls, [job], (path) =>
    path === "/api/jobs/a/analyze"
      ? new Response(JSON.stringify({ detail: "Hãy chọn vùng sub trước khi phân tích." }), { status: 409 })
      : undefined);
  render(<App />);
  await screen.findByRole("button", { name: "Phân tích video" });
  fireEvent.click(screen.getByRole("button", { name: "Phân tích video" }));
  await screen.findByRole("region", { name: "Chọn vùng phân tích" });
  expect(screen.getAllByText("Hãy chọn vùng sub trước khi phân tích.").length).toBeGreaterThan(0);
});

it("editor: Vùng phân tích reopens the picker prefilled when regions exist", async () => {
  location.hash = "#editor?job=a";
  const job = {
    ...base, id: "a", title: "Có vùng", filename: "a.mp4", status: "awaiting_review", stage: "awaiting_review",
    analysis_regions: { no_hard_subs: false, subtitle: [10, 900, 1800, 100], logos: [], screen_text: [] },
  };
  stub([], [job]);
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
    left: 0, top: 0, width: 960, height: 600, right: 960, bottom: 600, x: 0, y: 0, toJSON: () => ({}),
  });
  render(<App />);
  await screen.findByRole("button", { name: "Vùng phân tích" });
  expect(screen.queryByRole("region", { name: "Chọn vùng phân tích" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Vùng phân tích" }));
  await screen.findByRole("region", { name: "Chọn vùng phân tích" });
  expect(screen.getByTestId("rp-subtitle-0")).toBeTruthy();
});
