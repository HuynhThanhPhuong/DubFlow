import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";

const job = {
  id: "job1",
  title: "Video thật",
  mode: "vietsub",
  voice_id: null,
  source_url: null,
  status: "awaiting_review",
  stage: "awaiting_review",
  progress: 45,
  error: null,
  duration: 10,
  width: 1920,
  height: 1080,
  filename: "real.mp4",
  created_at: "2026-10-29",
  updated_at: "2026-10-29",
  source_url_path: "/api/jobs/job1/source",
  output_url: null,
  poster_url: null,
  warnings: [],
  cue_count: 1,
  ready_count: 0,
};
type Call = { path: string; init?: RequestInit };
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  location.hash = "";
});
function stub(over: Record<string, unknown>, calls: Call[], extra?: (path: string) => Response | undefined) {
  const current = { ...job, ...over };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      calls.push({ path, init });
      const special = extra?.(path);
      if (special) return special;
      let response: unknown;
      if (path === "/api/health")
        response = { status: "ok", queue_backend: "sqlite", capabilities: { automatic_translation: true }, warnings: [] };
      else if (path === "/api/settings") response = { output_dir: "D:/Exports", translation_provider: "gemini" };
      else if (path === "/api/collections" || path === "/api/voices") response = [];
      else if (path === "/api/jobs") response = [current];
      else if (path === "/api/jobs/job1") response = current;
      else if (path === "/api/jobs/job1/cues")
        response = [{ id: "1", start: 1, end: 2, speaker: "A", original: "你好", text: "" }];
      else if (path.startsWith("/api/jobs/job1/translate/estimate"))
        response = { requests: 3, input_tokens: 1000, output_tokens: 500, cost_usd: 0.12, tier: "paid", cap_usd: 0.05, spent_usd: 0.04, over_cap: true, cue_count: 40 };
      else if (path === "/api/jobs/job1/translate") response = current;
      else throw Error(`Unexpected request ${path}`);
      return new Response(JSON.stringify(response), { status: 200 });
    }),
  );
}
it("shows the estimate, posts nothing on cancel, posts with over-cap consent", async () => {
  location.hash = "#editor?job=job1";
  const calls: Call[] = [];
  stub({}, calls);
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "Dịch bằng Gemini" }));
  await screen.findByText(/Dự kiến: 3 request, khoảng 1\.500 token, khoảng 0\.12 USD/);
  expect(screen.getByRole("alert").textContent).toContain("vượt mức trần");
  expect(screen.getByText(/Đã tiêu cho video này: 0\.04 USD/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Hủy" }));
  expect(calls.some((c) => c.path === "/api/jobs/job1/translate")).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Dịch bằng Gemini" }));
  fireEvent.click(await screen.findByRole("button", { name: "Vẫn dịch, cho phép vượt trần" }));
  await waitFor(() => expect(calls.some((c) => c.path === "/api/jobs/job1/translate")).toBe(true));
  const post = calls.find((c) => c.path === "/api/jobs/job1/translate");
  expect(JSON.parse(String(post?.init?.body))).toEqual({ scope: "missing", allow_over_cap: true });
});
it("shows usage, the stale-mode note and a resume button for a cost-cap pause", async () => {
  location.hash = "#editor?job=job1";
  stub(
    {
      warnings: ['Tạm dừng – sắp vượt mức trần chi phí 0.5 USD cho video này. Bấm "Dịch tiếp, cho phép vượt trần" nếu muốn chạy tiếp.'],
      translation_usage: { requests: 4, input_tokens: 2000, output_tokens: 1000, cost_usd: 0.25, provider: "gemini", model: "m", mode: "dub" },
    },
    [],
  );
  render(<App />);
  await screen.findByRole("button", { name: "Dịch tiếp, cho phép vượt trần" });
  expect(screen.getByText(/Đã dùng: 4 request · 3\.000 token · 0\.25 USD/)).toBeTruthy();
  expect(screen.getByText(/Bản dịch hiện tại theo chế độ lồng tiếng/)).toBeTruthy();
});
it("prefers the structured pause flag over the warning text", async () => {
  location.hash = "#editor?job=job1";
  stub(
    {
      warnings: ["Tạm dừng – nội dung cảnh báo đã đổi"],
      translation_usage: { requests: 1, input_tokens: 1, output_tokens: 1, cost_usd: 0.1, provider: "gemini", model: "m", mode: "dub", paused: "cost_cap" },
    },
    [],
  );
  render(<App />);
  await screen.findByRole("button", { name: "Dịch tiếp, cho phép vượt trần" });
});
it("uses Dịch tiếp for a quota pause", async () => {
  location.hash = "#editor?job=job1";
  stub({ warnings: ['Tạm dừng – hết hạn mức ngày của Gemini. Đã dịch 3/9 câu; bấm "Dịch tiếp" khi hạn mức được làm mới.'] }, []);
  render(<App />);
  expect((await screen.findByRole("button", { name: "Dịch tiếp" })).textContent).toBe("Dịch tiếp");
});
it("shows the 422 message verbatim when importing a Vietnamese SRT fails", async () => {
  location.hash = "#editor?job=job1";
  stub({}, [], (path) =>
    path === "/api/jobs/job1/translation-srt"
      ? new Response(JSON.stringify({ detail: "Thiếu số 2, 3 trong file SRT." }), { status: 422 })
      : undefined,
  );
  render(<App />);
  await screen.findByRole("button", { name: "Nhập SRT Việt" });
  const file = new File(["x"], "vi.srt", { type: "text/plain" });
  fireEvent.change(screen.getByLabelText("Chọn file SRT Việt"), { target: { files: [file] } });
  await screen.findByText("Thiếu số 2, 3 trong file SRT.");
});
