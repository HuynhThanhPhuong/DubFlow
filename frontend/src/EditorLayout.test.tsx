import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";

const job = {
  id: "job1", title: "Video thật", mode: "vietsub", voice_id: null, source_url: null,
  status: "awaiting_review", stage: "awaiting_review", progress: 45, error: null,
  duration: 10, width: 1920, height: 1080, filename: "real.mp4",
  created_at: "2026-10-29", updated_at: "2026-10-29", source_url_path: "/api/jobs/job1/source",
  output_url: null, poster_url: null, warnings: ["Cảnh báo thử một"], cue_count: 1, ready_count: 0,
};
const cues = [{ id: "1", start: 1, end: 2, speaker: "A", original: "你好", text: "Xin chào" }];

function stubFetch() {
  vi.stubGlobal("fetch", vi.fn(async (path: string) => {
    let response: unknown;
    if (path === "/api/health") response = { status: "ok", queue_backend: "sqlite", capabilities: {}, warnings: [] };
    else if (path === "/api/settings") response = { output_dir: "D:/Exports", organize_by_collection: true };
    else if (path === "/api/collections") response = [];
    else if (path === "/api/voices") response = [];
    else if (path === "/api/jobs") response = [job];
    else if (path === "/api/jobs/job1") response = job;
    else if (path === "/api/jobs/job1/cues") response = cues;
    else throw Error(`Unexpected request ${path}`);
    return new Response(JSON.stringify(response), { status: 200 });
  }));
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); location.hash = ""; });

it("opens project notes in a modal dialog instead of expanding inline, and Escape closes it", async () => {
  location.hash = "#editor?job=job1";
  stubFetch();
  render(<App />);
  const toggle = await screen.findByRole("button", { name: /Lưu ý của dự án/ });
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.click(toggle);
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByText("Cảnh báo thử một")).toBeTruthy();
  expect(document.querySelector(".project-notes-content")).toBeNull();
  fireEvent.click(within(dialog).getByRole("button", { name: "Đóng" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  fireEvent.click(toggle);
  const again = await screen.findByRole("dialog");
  fireEvent.keyDown(again, { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});

it("renders pipeline steps with a .step-meta status element", async () => {
  location.hash = "#editor?job=job1";
  stubFetch();
  render(<App />);
  await screen.findByRole("button", { name: /Lưu ý của dự án/ });
  const steps = document.querySelectorAll(".studio-workflow > div");
  expect(steps.length).toBe(4);
  steps.forEach((step) => expect(step.querySelector(".step-meta")).not.toBeNull());
});
