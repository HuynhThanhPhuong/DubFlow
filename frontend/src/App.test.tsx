import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
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
  expect(screen.getByRole('group',{name:'Thao tác video'}).textContent).toBe('Vùng phân tíchPhân tích videoPhân tích lại lời gốcTuỳ chỉnhXuất videoXóa video');
  fireEvent.click(screen.getByRole('button',{name:'Dịch ▾'}));
  expect(screen.getByRole('link',{name:'Xuất SRT Trung + lệnh mẫu'}).getAttribute('href')).toBe('/api/jobs/job1/source-subtitles.srt');
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

function stubReset(calls: string[], cue: Record<string, unknown>, mode = "vietsub") {
  const current = { ...job, mode };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init: RequestInit) => {
      calls.push(`${init?.method || "GET"} ${path}`);
      let response: unknown;
      if (path === "/api/health") response = { status: "ok", queue_backend: "sqlite", capabilities: {}, warnings: [] };
      else if (path === "/api/settings") response = { output_dir: "D:/Exports", organize_by_collection: true };
      else if (path === "/api/collections" || path === "/api/voices") response = [];
      else if (path === "/api/jobs") response = [current];
      else if (path === "/api/jobs/job1" || path.startsWith("/api/jobs/job1/analyze")) response = current;
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
  render(<App />);
  await screen.findByLabelText("Lời Việt câu 1");
  fireEvent.click(screen.getByRole("button", { name: "Phân tích lại lời gốc" }));
  let dialog=await screen.findByRole('dialog');
  expect(within(dialog).getByText(/Bản dịch hiện tại sẽ được lưu vào Lịch sử/)).toBeTruthy();
  fireEvent.click(within(dialog).getByRole('button',{name:'Huỷ'}));
  expect(calls.some((c) => c.includes("analyze"))).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Phân tích lại lời gốc" }));
  dialog=await screen.findByRole('dialog');
  fireEvent.click(within(dialog).getByRole('button',{name:'Phân tích lại'}));
  await waitFor(() => expect(calls).toContain("POST /api/jobs/job1/analyze?reset_source=1"));
});
it("labels the source of a cue and hides persisted heard text in Vietsub", async () => {
  location.hash = "#editor?job=job1";
  stubReset([], { id: "1", start: 1, end: 2, speaker: "A", original: "你好", text: "Xin chào", source: "ocr", asr_text: "你们好", source_mismatch: true });
  render(<App />);
  await screen.findByLabelText("Lời Việt câu 1");
  expect(screen.getByText("Chữ trên hình")).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'Chọn và tua câu 1'}));
  expect(screen.queryByText('你们好')).toBeNull();
});
it.each(["dub", "tm"])("shows heard text on a source mismatch in %s", async (mode) => {
  location.hash = "#editor?job=job1";
  stubReset([], { id: "1", start: 1, end: 2, speaker: "A", original: "你好", text: "Xin chào", source: "ocr", asr_text: "你们好", source_mismatch: true }, mode);
  render(<App />);
  await screen.findByLabelText("Lời Việt câu 1");
  fireEvent.click(screen.getByRole("button", { name: "Chọn và tua câu 1" }));
  expect(screen.getByText("你们好").closest("p")?.textContent).toContain("Nghe được: 你们好");
});

it("clears the paused-updates banner once polling succeeds again", async () => {
  location.hash = "#queue";
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  let jobCalls = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => {
      let response: unknown = [];
      if (path === "/api/health") response = { status: "ok", queue_backend: "sqlite", capabilities: {}, warnings: [] };
      else if (path === "/api/settings") response = { output_dir: "D:/Exports", organize_by_collection: true };
      else if (path === "/api/jobs") {
        jobCalls++;
        if (jobCalls <= 5) throw new Error("server down");
        response = [job];
      }
      return new Response(JSON.stringify(response), { status: 200 });
    }),
  );
  try {
    render(<App />);
    const advance = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });
    for (let i = 0; i < 6; i++) await advance(3100);
    expect(screen.queryByText(/Đã tạm dừng cập nhật tự động/)).not.toBeNull();
    await advance(15500);
    expect(screen.queryByText(/Đã tạm dừng cập nhật tự động/)).toBeNull();
  } finally {
    vi.useRealTimers();
  }
});

it("deletes the open cue through the API after a confirm", async () => {
  location.hash = "#editor?job=job1";
  const calls: string[] = [];
  stubReset(calls, { id: "1", start: 1, end: 2, speaker: "A", original: "你好", text: "Xin chào", source: "ocr" });
  const base = globalThis.fetch as unknown as (p: string, i: RequestInit) => Promise<Response>;
  vi.stubGlobal("fetch", vi.fn(async (path: string, init: RequestInit) =>
    path === "/api/jobs/job1/cues/delete" ? (calls.push("POST delete"), new Response("[]", { status: 200 })) : base(path, init)));
  const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
  render(<App />);
  await screen.findByLabelText("Lời Việt câu 1");
  fireEvent.click(screen.getByRole("button", { name: "Chọn và tua câu 1" }));
  fireEvent.click(screen.getByRole("button", { name: "Xoá câu 1" }));
  expect(calls).not.toContain("POST delete");
  fireEvent.click(screen.getByRole("button", { name: "Xoá câu 1" }));
  await waitFor(() => expect(calls).toContain("POST delete"));
  confirm.mockRestore();
});

it("saves unsaved edits of other cues before deleting a saved cue and never drops them", async () => {
  location.hash = "#editor?job=job1";
  const calls: string[] = [];
  const first = { id: "1", start: 1, end: 2, speaker: "A", original: "你好", text: "Xin chào", source: "ocr" };
  const second = { id: "2", start: 3, end: 4, speaker: "A", original: "再见", text: "Tạm biệt", source: "ocr" };
  stubReset(calls, first);
  const base = globalThis.fetch as unknown as (p: string, i: RequestInit) => Promise<Response>;
  let saved: { id: string; text: string }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (path: string, init: RequestInit) => {
    if (path === "/api/jobs/job1/cues" && (init?.method || "GET") === "GET") return new Response(JSON.stringify([first, second]), { status: 200 });
    if (path === "/api/jobs/job1/cues" && init?.method === "PUT") {
      calls.push("PUT cues");
      saved = JSON.parse(String(init.body));
      return new Response(String(init.body), { status: 200 });
    }
    if (path === "/api/jobs/job1/cues/delete") {
      calls.push("POST delete");
      return new Response(JSON.stringify(saved.filter((c) => c.id !== "1")), { status: 200 });
    }
    return base(path, init);
  }));
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<App />);
  const second2 = await screen.findByLabelText("Lời Việt câu 2");
  fireEvent.change(second2, { target: { value: "Tạm biệt nhé" } });
  fireEvent.click(screen.getByRole("button", { name: "Chọn và tua câu 1" }));
  fireEvent.click(screen.getByRole("button", { name: "Xoá câu 1" }));
  await waitFor(() => expect(calls).toContain("POST delete"));
  expect(calls.indexOf("PUT cues")).toBeGreaterThanOrEqual(0);
  expect(calls.indexOf("PUT cues")).toBeLessThan(calls.indexOf("POST delete"));
  expect(saved.find((c) => c.id === "2")?.text).toBe("Tạm biệt nhé");
  await waitFor(() => expect((screen.getByLabelText("Lời Việt câu 1") as HTMLTextAreaElement).value).toBe("Tạm biệt nhé"));
  confirm.mockRestore();
});
