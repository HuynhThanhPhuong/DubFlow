import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { TranslatePanel } from "./TranslatePanel";
import { JobActivity } from "./JobActivity";
import type { Job } from "./types";

const base = {
  id: "j", title: "Phim", mode: "vietsub", voice_id: null, source_url: null,
  status: "awaiting_review", stage: "awaiting_review", progress: 45, error: null,
  duration: 10, width: 1920, height: 1080, filename: "phim.mp4",
  created_at: "2026-11-04", updated_at: "2026-11-04", source_url_path: "/api/jobs/j/source",
  warnings: [], cue_count: 1, ready_count: 0,
} as Job;
const props = {
  providerLabel: "Gemini", ready: false, disabled: false, canExport: true,
  onJob: vi.fn(), onCues: vi.fn(), onError: vi.fn(), onNotice: vi.fn(),
};
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.clearAllMocks(); });
function open() { fireEvent.click(screen.getByRole("button", { name: "Dịch ▾" })); }

it("persists a setting without an API key and reloads the saved setting per job", async () => {
  let saved = base;
  const calls: { path: string; init?: RequestInit }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (path: string, init?: RequestInit) => {
    calls.push({ path, init });
    saved = { ...base, ...JSON.parse(String(init?.body)) };
    return new Response(JSON.stringify(saved));
  }));
  const view = render(<TranslatePanel {...props} job={base} />);
  open();
  expect((screen.getByLabelText("Bối cảnh xưng hô") as HTMLSelectElement).value).toBe("auto");
  fireEvent.change(screen.getByLabelText("Bối cảnh xưng hô"), { target: { value: "ancient" } });
  await waitFor(() => expect(props.onJob).toHaveBeenCalledWith(expect.objectContaining({ setting: "ancient" })));
  expect(calls[0].path).toBe("/api/jobs/j");
  expect(calls[0].init?.method).toBe("PUT");
  expect(JSON.parse(String(calls[0].init?.body))).toEqual({ setting: "ancient" });
  view.rerender(<TranslatePanel {...props} job={saved} />);
  expect((screen.getByLabelText("Bối cảnh xưng hô") as HTMLSelectElement).value).toBe("ancient");
  view.unmount();
  const reload = render(<TranslatePanel {...props} job={saved} />);
  open();
  expect((screen.getByLabelText("Bối cảnh xưng hô") as HTMLSelectElement).value).toBe("ancient");
  expect(screen.queryByText(/^Bối cảnh:/)).toBeNull();
  reload.rerender(<TranslatePanel {...props} job={{ ...base, id: "other", setting: "modern" } as Job} />);
  expect((screen.getByLabelText("Bối cảnh xưng hô") as HTMLSelectElement).value).toBe("modern");
});

it("keeps the saved value on a rejected save and prevents actions while saving", async () => {
  let finish!: (response: Response) => void;
  const fetch = vi.fn(() => new Promise<Response>((resolve) => { finish = resolve; }));
  vi.stubGlobal("fetch", fetch);
  render(<TranslatePanel {...props} ready job={base} />);
  open();
  const select = screen.getByLabelText("Bối cảnh xưng hô") as HTMLSelectElement;
  fireEvent.change(select, { target: { value: "ancient" } });
  expect(select.disabled).toBe(true);
  expect((screen.getByRole("button", { name: "Dịch bằng Gemini" }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole("link", { name: "Xuất SRT Trung + lệnh mẫu" }));
  expect(fetch).toHaveBeenCalledTimes(1);
  await act(async () => finish(new Response(JSON.stringify({ detail: "Không lưu được bối cảnh." }), { status: 422 })));
  await waitFor(() => expect(select.disabled).toBe(false));
  expect(select.value).toBe("auto");
  expect(props.onJob).not.toHaveBeenCalled();
  expect(props.onError).toHaveBeenCalledWith(expect.objectContaining({ message: "Không lưu được bối cảnh." }));
});

it("passes the saved setting to estimate, translation and the manual prompt", async () => {
  const calls: { path: string; init?: RequestInit }[] = [];
  const job = { ...base, setting: "ancient" } as Job;
  vi.stubGlobal("fetch", vi.fn(async (path: string, init?: RequestInit) => {
    calls.push({ path, init });
    if (path.includes("translate-prompt")) return new Response("Lệnh cổ trang");
    if (path.includes("/estimate")) return new Response(JSON.stringify({ requests: 1, input_tokens: 10, output_tokens: 10, cost_usd: null, tier: "free", cap_usd: null, over_cap: false, cue_count: 1 }));
    return new Response(JSON.stringify(job));
  }));
  render(<TranslatePanel {...props} ready job={job} />);
  open();
  fireEvent.click(screen.getByRole("button", { name: "Dịch bằng Gemini" }));
  fireEvent.click(await screen.findByRole("button", { name: "Bắt đầu dịch" }));
  await waitFor(() => expect(props.onJob).toHaveBeenCalled());
  const estimate = calls.find(c => c.path.includes("/estimate"));
  expect(estimate?.path).toBe("/api/jobs/j/translate/estimate?scope=missing&setting=ancient");
  expect(JSON.parse(String(calls.find(c => c.path === "/api/jobs/j/translate")?.init?.body))).toEqual({ scope: "missing", allow_over_cap: false, setting: "ancient" });
  open();
  const download = screen.getByRole("link", { name: "Xuất SRT Trung + lệnh mẫu" });
  // jsdom cannot download a file; keep the real React handler, suppress navigation only.
  download.addEventListener("click", (event) => event.preventDefault());
  fireEvent.click(download);
  await screen.findByDisplayValue("Lệnh cổ trang");
  expect(calls.find(c => c.path.includes("translate-prompt"))?.path).toBe("/api/jobs/j/translate-prompt?setting=ancient");
});

it("refreshes both the selected setting and detected context from new job data", () => {
  const view = render(<TranslatePanel {...props} job={base} />);
  open();
  view.rerender(<TranslatePanel {...props} job={{ ...base, setting: "modern", translation_context: { setting: { era: "modern", note: "Bối cảnh công sở." } } }} />);
  expect((screen.getByLabelText("Bối cảnh xưng hô") as HTMLSelectElement).value).toBe("modern");
  expect(screen.getByText("Bối cảnh: Hiện đại")).toBeTruthy();
  expect(screen.getByText("Bối cảnh công sở.")).toBeTruthy();
  view.rerender(<TranslatePanel {...props} job={base} />);
  expect((screen.getByLabelText("Bối cảnh xưng hô") as HTMLSelectElement).value).toBe("auto");
  expect(screen.queryByText("Bối cảnh: Hiện đại")).toBeNull();
});

it("disables setting changes for busy jobs", () => {
  render(<TranslatePanel {...props} job={{ ...base, status: "processing" }} />);
  open();
  expect((screen.getByLabelText("Bối cảnh xưng hô") as HTMLSelectElement).disabled).toBe(true);
});

it("shows the model context in the popover and details even without activity", () => {
  const job = { ...base, translation_context: { setting: { era: "ancient", note: "Có sư tôn và tông môn." } } } as Job;
  render(<><TranslatePanel {...props} job={job} /><JobActivity job={job} /></>);
  open();
  expect(within(screen.getByRole("region", { name: "Công cụ dịch" })).getByText("Bối cảnh: Cổ trang")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /Xem chi tiết/ }));
  const dialog = screen.getByRole("dialog", { name: "Chi tiết" });
  expect(within(dialog).getByText("Bối cảnh: Cổ trang")).toBeTruthy();
  expect(within(dialog).getByText("Có sư tôn và tông môn.")).toBeTruthy();
});
