import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
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
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  location.hash = "";
});
it("edits Vietnamese and saves exact cue array to real API contract", async () => {
  location.hash = "#editor?job=job1";
  let saved: unknown;
  let cues = [
    {
      id: "1",
      start: 1,
      end: 2,
      speaker: "A",
      original: "你好",
      text: "Xin chào",
    },
  ];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init: RequestInit) => {
      let response: unknown;
      if (path === "/api/health")
        response = {
          status: "ok",
          queue_backend: "sqlite",
          capabilities: {},
          warnings: [],
        };
      else if (path === "/api/settings") response = {output_dir:"D:/Exports",organize_by_collection:true};
      else if (path === "/api/collections") response=[];
      else if (path === "/api/voices") response = [];
      else if (path === "/api/jobs") response = [job];
      else if (path === "/api/jobs/job1") response = job;
      else if (path === "/api/jobs/job1/cues") {
        if (init.method === "PUT") {
          saved = JSON.parse(String(init.body));
          cues = saved as typeof cues;
        }
        response = cues;
      } else throw Error(`Unexpected request ${path}`);
      return new Response(JSON.stringify(response), { status: 200 });
    }),
  );
  render(<App />);
  const input = await screen.findByLabelText("Lời Việt câu 1");
  expect(screen.queryByRole('button',{name:'Kiểm tra & duyệt'})).toBeNull();
  expect(screen.queryByRole('button',{name:'Thêm video'})).toBeNull();
  expect(screen.getByRole('group',{name:'Thao tác video'}).textContent).toBe('Tuỳ chỉnhPhân tích videoPhân tích lại lời gốcXuất video');
  expect(screen.getByRole('link',{name:'Xuất lời Trung'}).getAttribute('href')).toBe('/api/jobs/job1/source-subtitles.srt');
  fireEvent.change(input, { target: { value: "Chào bạn" } });
  expect(screen.getByText("Chưa lưu")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Lưu lời dịch" }));
  await waitFor(() =>
    expect(saved).toEqual([
      {
        id: "1",
        start: 1,
        end: 2,
        speaker: "A",
        original: "你好",
        text: "Chào bạn",
      },
    ]),
  );
  await screen.findByText("Đã lưu lời dịch.");
});

function stubReset(calls: string[], cue: Record<string, unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init: RequestInit) => {
      calls.push(`${init?.method || "GET"} ${path}`);
      let response: unknown;
      if (path === "/api/health") response = { status: "ok", queue_backend: "sqlite", capabilities: {}, warnings: [] };
      else if (path === "/api/settings") response = { output_dir: "D:/Exports", organize_by_collection: true };
      else if (path === "/api/collections" || path === "/api/voices") response = [];
      else if (path === "/api/jobs") response = [job];
      else if (path === "/api/jobs/job1" || path.startsWith("/api/jobs/job1/analyze")) response = job;
      else if (path === "/api/jobs/job1/cues") response = [cue];
      else throw Error(`Unexpected request ${path}`);
      return new Response(JSON.stringify(response), { status: 200 });
    }),
  );
}
it("asks before re-analysing the source text and does nothing on cancel", async () => {
  location.hash = "#editor?job=job1";
  const calls: string[] = [];
  stubReset(calls, { id: "1", start: 1, end: 2, speaker: "A", original: "你好", text: "Xin chào", source: "ocr" });
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<App />);
  await screen.findByLabelText("Lời Việt câu 1");
  fireEvent.click(screen.getByRole("button", { name: "Phân tích lại lời gốc" }));
  expect(confirm).toHaveBeenCalledWith("Lời gốc sẽ được dựng lại từ đầu. Bản dịch hiện tại được sao lưu nhưng sẽ không còn trong trình biên tập. Tiếp tục?");
  expect(calls.some((c) => c.includes("analyze"))).toBe(false);
  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", { name: "Phân tích lại lời gốc" }));
  await waitFor(() => expect(calls).toContain("POST /api/jobs/job1/analyze?reset_source=1"));
  confirm.mockRestore();
});
it("labels the source of a cue and shows the heard text on mismatch", async () => {
  location.hash = "#editor?job=job1";
  stubReset([], { id: "1", start: 1, end: 2, speaker: "A", original: "你好", text: "Xin chào", source: "ocr", asr_text: "你们好", source_mismatch: true });
  render(<App />);
  await screen.findByLabelText("Lời Việt câu 1");
  expect(screen.getByText("hình")).toBeTruthy();
  expect(screen.getByText(/Nghe được: 你们好/)).toBeTruthy();
});
