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
  await screen.findAllByRole("button", { name: "Vùng phân tích" });
  expect(screen.queryByRole("region", { name: "Chọn vùng phân tích" })).toBeNull();
  fireEvent.click(screen.getAllByRole("button", { name: "Vùng phân tích" })[0]);
  await screen.findByRole("region", { name: "Chọn vùng phân tích" });
  expect(screen.getByTestId("rp-subtitle-0")).toBeTruthy();
});

it("queue: lists awaiting_regions jobs with their status chip and an open button", async () => {
  location.hash = "#queue";
  const waiting = { ...base, id: "c", title: "Chờ vùng", filename: "c.mp4", status: "awaiting_regions", stage: "awaiting_regions" };
  stub([], [waiting]);
  render(<App />);
  await screen.findByText("Chờ vùng");
  expect(document.querySelector(".badge")?.textContent).toBe("Chờ chọn vùng sub");
  expect(screen.getByRole("button", { name: "Mở biên tập" })).toBeTruthy();
  expect(screen.queryByText("Không có tác vụ đang chờ hoặc cần xử lý.")).toBeNull();
});

const regions = { no_hard_subs: false, subtitle: [10, 900, 1800, 100], logos: [], screen_text: [] };
const reviewed = { ...base, id: "a", title: "Rà", filename: "a.mp4", status: "awaiting_review", stage: "awaiting_review", cue_count: 1, analysis_regions: regions };
const cueStub = (calls: string[], job: unknown, extra: (p: string, i: RequestInit) => Response | undefined = () => undefined) =>
  stub(calls, [job], (path, init) => {
    if (path === "/api/jobs/a/cues" && !init.method) return new Response(JSON.stringify([{ id: "c", start: 1, end: 2, speaker: "A", original: "你好", text: "Xin chào" }]), { status: 200 });
    return extra(path, init);
  });

it("editor: regions_stale shows a warning and allows opening the export report", async () => {
  location.hash = "#editor?job=a";
  cueStub([], { ...reviewed, regions_stale: true });
  render(<App />);
  await screen.findByLabelText("Lời Việt câu 1");
  expect(screen.getByText("Vùng phân tích đã đổi, hãy phân tích lại trước khi xuất.")).toBeTruthy();
  expect((screen.getByRole("button", { name: "Xuất video" }) as HTMLButtonElement).disabled).toBe(false);
});

it("editor: stopping shows Đang dừng… and disables cancel; queue chip too", async () => {
  location.hash = "#editor?job=a";
  cueStub([], { ...running, stopping: true });
  render(<App />);
  expect((await screen.findAllByText(/Đang dừng…/)).length).toBeGreaterThan(0);
  expect((screen.getByRole("button", { name: "Đang dừng…" }) as HTMLButtonElement).disabled).toBe(true);
  cleanup();
  location.hash = "#queue";
  stub([], [{ ...running, stopping: true }]);
  render(<App />);
  await screen.findByText("Đang chạy");
  expect(document.querySelector(".badge")?.textContent).toBe("Đang dừng…");
  expect((screen.getByRole("button", { name: "Đang dừng…" }) as HTMLButtonElement).disabled).toBe(true);
});

it("queue: deleting shows Đang xóa… and disables delete", async () => {
  location.hash = "#queue";
  stub([], [{ ...idle, deleting: true }]);
  render(<App />);
  await screen.findByText("Đã xong");
  expect(document.querySelector(".badge")?.textContent).toBe("Đang xóa…");
  expect((screen.getByRole("button", { name: /Xóa Đã xong/ }) as HTMLButtonElement).disabled).toBe(true);
});

it("queue: stop-all reports the count and unstoppable processes", async () => {
  location.hash = "#queue";
  stub([], [running], (path) =>
    path === "/api/tasks/stop-all"
      ? new Response(JSON.stringify({ cancelled: 3, queued: 1, running: 2, jobs: [], processes_killed: 1, processes_failed: 2 }), { status: 200 })
      : undefined);
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<App />);
  await screen.findByText("Đang chạy");
  fireEvent.click(screen.getByRole("button", { name: "Dừng tất cả" }));
  await screen.findByText("Đã dừng 3 tác vụ");
  await screen.findByText("Có 2 tiến trình chưa dừng được, hãy thử lại hoặc khởi động lại máy chủ.");
});

it("editor: picker Lưu & phân tích is blocked while Vietnamese edits are unsaved", async () => {
  location.hash = "#editor?job=a";
  const calls: string[] = [];
  cueStub(calls, reviewed);
  render(<App />);
  fireEvent.change(await screen.findByLabelText("Lời Việt câu 1"), { target: { value: "Bản nháp" } });
  fireEvent.click(screen.getAllByRole("button", { name: "Vùng phân tích" })[0]);
  fireEvent.click(await screen.findByRole("button", { name: "Lưu & phân tích" }));
  await screen.findByText("Hãy lưu hoặc bỏ thay đổi lời dịch trước khi phân tích lại.");
  expect(calls.some((c) => c.includes("analysis-regions") || c.endsWith("/analyze"))).toBe(false);
});

it("editor: leaving the region picker keeps the draft without saving while dirty", async () => {
  location.hash = "#editor?job=a";
  const calls: string[] = [];
  cueStub(calls, reviewed, (path) => (path === "/api/jobs/a/analysis-regions" ? new Response("{}", { status: 200 }) : undefined));
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
    left: 0, top: 0, width: 960, height: 600, right: 960, bottom: 600, x: 0, y: 0, toJSON: () => ({}),
  });
  render(<App />);
  fireEvent.change(await screen.findByLabelText("Lời Việt câu 1"), { target: { value: "Bản nháp" } });
  fireEvent.click(screen.getAllByRole("button", { name: "Vùng phân tích" })[0]);
  await screen.findByRole('button',{name:'Lưu & phân tích'});
  fireEvent.click(screen.getByRole('button',{name:'Biên tập video'}));
  expect(calls).not.toContain('PUT /api/jobs/a/analysis-regions');
  expect((screen.getByLabelText('Lời Việt câu 1') as HTMLTextAreaElement).value).toBe('Bản nháp');
});

it("editor: Player offers Vùng phân tích instead of Dò logo when regions exist", async () => {
  location.hash = "#editor?job=a";
  cueStub([], reviewed);
  render(<App />);
  await screen.findByLabelText("Lời Việt câu 1");
  expect(screen.queryByRole("button", { name: "Dò logo" })).toBeNull();
  expect(screen.getAllByRole("button", { name: "Vùng phân tích" }).length).toBe(2);
});
