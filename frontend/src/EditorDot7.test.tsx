import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";
import { packCapacity } from "./Pagination";

const job = {
  id: "dot7",
  title: "Video đợt 7",
  mode: "vietsub",
  status: "awaiting_review",
  stage: "awaiting_review",
  progress: 45,
  duration: 30,
  width: 1280,
  height: 720,
  filename: "test.mp4",
  created_at: "2026-11-03",
  updated_at: "1",
  source_url_path: "/api/jobs/dot7/source",
  output_url: null,
  poster_url: null,
  warnings: [],
  cue_count: 12,
  ready_count: 0,
  analysis_regions: {
    no_hard_subs: true,
    subtitle: null,
    logos: [],
    screen_text: [],
  },
};
const cues = Array.from({ length: 12 }, (_, i) => ({
  id: `c${i}`,
  start: i * 2,
  end: i * 2 + 2,
  original: `原文${i}`,
  text: i === 10 ? "" : "Lời Việt",
  speaker: "unconfirmed",
  ...(i === 0
    ? {
        box: [100, 600, 400, 650],
        band: [40, 580, 1240, 710],
        region: 0,
        kind: "dialogue" as const,
        orientation: "h" as const,
        reveal: [
          { t: 0, fraction: 0.2 },
          { t: 1, fraction: 1 },
        ],
      }
    : {}),
}));
const snapshot = {
  id: "s1",
  source: "gemini",
  status: "done",
  cue_count: 1,
  total_count: 1,
  created_at: "2026-11-03T01:00:00Z",
  cues: [{ start: 0, end: 2, original: "原文0", text: "Bản đã lưu" }],
};
function setup(saveGate?: Promise<void>, importGate?: Promise<void>) {
  location.hash = "#editor?job=dot7";
  const fetch = vi.fn(async (path: string, _init?: RequestInit) => {
    if (path === "/api/jobs/dot7/cues" && _init?.method === "PUT")
      await saveGate;
    if (path.endsWith("/translation-srt/preview")) await importGate;
    let value: unknown = [];
    if (path === "/api/health")
      value = { capabilities: { automatic_translation: true }, warnings: [] };
    else if (path === "/api/settings")
      value = { output_dir: "D:/Exports", translation_provider: "gemini" };
    else if (path === "/api/jobs") value = [job];
    else if (path === "/api/jobs/dot7") value = job;
    else if (path === "/api/jobs/dot7/cues") value = cues;
    else if (path === "/api/jobs/other")
      value = { ...job, id: "other", title: "Video khác" };
    else if (path === "/api/jobs/other/cues")
      value = [{ ...cues[0], id: "other-cue", text: "Lời của video khác" }];
    else if (path.endsWith("/translation-srt/preview"))
      value = { mode: "index", total: 1, matched: 1, problems: 0, empty_cues: [], cues: [],
        rows: [{ block: 0, number: 1, start: 0, end: 2, text: "Bản nhập cũ", cue_id: cues[0].id, cue_number: 1, original: "", issues: [] }] };
    else if (path.endsWith("/translation-srt/commit"))
      value = { cues: cues.map((c) => ({ ...c, text: "Bản nhập cũ" })), summary: { mode: "manual", total: 1, blocks: 1, matched: 1, empty: [], skipped: [], empty_blocks: 0 } };
    else if (path.endsWith("/quality"))
      value = {
        draft_allowed: false,
        reasons: [
          {
            code: "MISSING_TRANSLATION",
            message: "Câu chưa có lời Việt.",
            cue_count: 1,
            cue_ids: ["c10"],
          },
        ],
      };
    else if (path.endsWith("/translation-history")) value = [snapshot];
    else if (path.endsWith("/translation-history/s1")) value = snapshot;
    else if (path.endsWith("/restore"))
      value = { matched_count: 1, unmatched_count: 0 };
    else if (path.endsWith("/analyze?reset_source=1")) value = job;
    return new Response(JSON.stringify(value), { status: 200 });
  });
  vi.stubGlobal("fetch", fetch);
  render(<App />);
  return fetch;
}
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  location.hash = "";
});

it("saves edited translated text through the real editor without dropping OCR band or reveal data", async () => {
  const fetch = setup();
  fireEvent.change(await screen.findByLabelText("Lời Việt câu 1"), {
    target: { value: "Bản sửa vẫn hiện dần" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Lưu lời dịch" }));
  await screen.findByText("Đã lưu lời dịch.");
  const saved = fetch.mock.calls.find(
    ([path, init]) => path === "/api/jobs/dot7/cues" && init?.method === "PUT",
  );
  expect(JSON.parse(saved![1]!.body as string)[0]).toEqual({
    ...cues[0],
    text: "Bản sửa vẫn hiện dần",
  });
});

it("disables adding cues while saving the editor", async () => {
  let release = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  setup(gate);
  fireEvent.change(await screen.findByLabelText("Lời Việt câu 1"), {
    target: { value: "Đã sửa" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Lưu lời dịch" }));
  expect(
    (
      screen.getByRole("button", {
        name: "Thêm câu phụ đề tại vị trí đang phát",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  release();
  await screen.findByText("Đã lưu lời dịch.");
});

it("ignores a late AI chat import after switching to another job", async () => {
  let release = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  setup(undefined, gate);
  fireEvent.click(await screen.findByRole("button", { name: "Dịch ▾" }));
  fireEvent.change(screen.getByLabelText("Chọn file SRT Việt"), {
    target: { files: [new File(["x"], "vi.srt")] },
  });
  location.hash = "#editor?job=other";
  await screen.findByText("Video khác");
  await screen.findByDisplayValue("Lời của video khác");
  release();
  await waitFor(() =>
    expect(screen.queryByDisplayValue("Bản nhập cũ")).toBeNull(),
  );
  expect(screen.getByDisplayValue("Lời của video khác")).toBeTruthy();
});

it("packs real row heights including an expanded cue and always keeps a long row accessible", () => {
  expect(packCapacity([60, 60, 160, 60, 60, 60], 300)).toEqual([
    { start: 0, end: 3 },
    { start: 3, end: 6 },
  ]);
  expect(packCapacity([700, 60], 300)).toEqual([
    { start: 0, end: 1 },
    { start: 1, end: 2 },
  ]);
});
it("shows read-only mode badges and a translation popover at the top of the script", async () => {
  setup();
  await screen.findByText("Video đợt 7");
  for (const name of ["Lồng tiếng", "Thuyết minh", "Vietsub"])
    expect(
      (screen.getByRole("button", { name }) as HTMLButtonElement).disabled,
    ).toBe(true);
  expect(screen.queryByText("Chỉ đọc")).toBeNull();
  expect(screen.queryByText("Giữ âm thanh gốc")).toBeNull();
  expect(screen.queryByText("Nhập SRT có sẵn")).toBeNull();
  expect(screen.queryByRole("button", { name: "Dịch bằng Gemini" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Dịch ▾" }));
  expect(screen.getByRole("button", { name: "Dịch bằng Gemini" })).toBeTruthy();
  expect(screen.getByLabelText("Dịch lại tất cả")).toBeTruthy();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("button", { name: "Dịch bằng Gemini" })).toBeNull();
});
it("requires explicit source reset confirmation before dispatch", async () => {
  const fetch = setup();
  fireEvent.click(
    await screen.findByRole("button", { name: "Phân tích lại lời gốc" }),
  );
  const dialog = await screen.findByRole("dialog");
  expect(
    within(dialog).getByText(/Bản dịch hiện tại sẽ được lưu vào Lịch sử/),
  ).toBeTruthy();
  expect(fetch.mock.calls.some(([p]) => p.includes("reset_source"))).toBe(
    false,
  );
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Phân tích lại" }),
  );
  await waitFor(() =>
    expect(fetch.mock.calls.some(([p]) => p.includes("reset_source"))).toBe(
      true,
    ),
  );
});
it("shows export reasons and jumps to a cue on another page", async () => {
  setup();
  fireEvent.click(await screen.findByRole("button", { name: "Xuất video" }));
  const dialog = await screen.findByRole("dialog");
  await within(dialog).findByText("Câu chưa có lời Việt.");
  expect(
    (
      within(dialog).getByRole("button", {
        name: "Xuất video",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  fireEvent.click(within(dialog).getByRole("button", { name: "Câu 11" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(await screen.findByLabelText("Lời Việt câu 11")).toBeTruthy();
});
it("compares history, confirms restore and reloads cues", async () => {
  const fetch = setup();
  fireEvent.click(
    await screen.findByRole("button", { name: "Lịch sử bản dịch" }),
  );
  let dialog = await screen.findByRole("dialog");
  fireEvent.click(await within(dialog).findByRole("button", { name: "Xem" }));
  await within(dialog).findByText("Bản đã lưu");
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Khôi phục bản này" }),
  );
  dialog = await screen.findByRole("dialog");
  expect(
    within(dialog).getByText(/Bản dịch hiện tại sẽ được lưu/),
  ).toBeTruthy();
  fireEvent.click(within(dialog).getByRole("button", { name: "Khôi phục" }));
  await waitFor(() =>
    expect(
      fetch.mock.calls.some(
        ([p, init]) => p.endsWith("/restore") && init?.method === "POST",
      ),
    ).toBe(true),
  );
  expect(await screen.findByText(/Đã khôi phục 1 câu/)).toBeTruthy();
});
