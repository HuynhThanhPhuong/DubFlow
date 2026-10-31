import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ReviewDialog } from "./ReviewDialog";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
it("requires an explanation for warnings and saves revision-bound approval", async () => {
  const state = {
    revision: 1,
    fingerprint: "a".repeat(64),
    characters: [],
    assignments: {},
    address_rules: [],
    scene_context: "",
    omissions: {},
    resolutions: {},
    source_cues: [],
  };
  const report = {
    fingerprint: state.fingerprint,
    technical_status: "passed",
    draft_allowed: true,
    final_allowed: false,
    coverage: { source: 1, covered: 1, omitted: 0, output: 1 },
    flags: [
      {
        id: "f1",
        code: "ASR_OCR_CONFLICT",
        severity: "review",
        cue_ids: ["a"],
        message: "ASR khác OCR",
        resolved: false,
      },
    ],
    source_evidence: [],
    limitations: [],
  };
  let saved: Record<string, unknown> | undefined;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "PUT") {
        saved = JSON.parse(String(init.body));
        return new Response(JSON.stringify(state));
      }
      return new Response(
        JSON.stringify(path.endsWith("/quality") ? report : state),
      );
    }),
  );
  render(
    <ReviewDialog jobId="j" cues={[]} onClose={() => {}} onSaved={() => {}} />,
  );
  await screen.findByText("ASR khác OCR");
  expect(
    (
      screen.getByRole("button", {
        name: "Chốt bản hoàn thiện",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  fireEvent.change(screen.getByLabelText("Lý do xử lý cảnh báo 1"), {
    target: { value: "Đã nghe và đối chiếu hình" },
  });
  fireEvent.change(screen.getByLabelText("Người duyệt"), {
    target: { value: "Tôi" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Chốt bản hoàn thiện" }));
  await waitFor(() => expect(saved?.approve_final).toBe(true));
  expect(saved?.fingerprint).toBe(state.fingerprint);
  expect(saved?.resolutions).toEqual({
    f1: { action: "accepted", reason: "Đã nghe và đối chiếu hình" },
  });
});
