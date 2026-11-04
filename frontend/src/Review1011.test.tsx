import { cleanup, render } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { PipelineSteps } from "./PipelineSteps";
import { loadFont } from "./fonts";
import type { Job, SubtitleFont } from "./types";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("counts only spoken cues for the voice step (supplementary captions are text only)", () => {
  const job = { id: "j", title: "t", mode: "dub", status: "awaiting_review", stage: "awaiting_review", progress: 45,
    updated_at: "u", ready_count: 8, exported_paths: [], error: null } as unknown as Job;
  const { container, rerender } = render(<PipelineSteps job={job} cueCount={10} missing={0} />);
  expect(container.textContent).toContain("8/10 câu có giọng");
  rerender(<PipelineSteps job={job} cueCount={10} spokenCount={8} missing={0} />);
  expect(container.textContent).toContain("8/8 câu có giọng");
});

it("pins the browser baseline to libass winAscent/winDescent via FontFace descriptors", async () => {
  const seen: Record<string, unknown>[] = [];
  vi.stubGlobal(
    "FontFace",
    class {
      constructor(_f: string, _s: string, d: Record<string, unknown>) {
        seen.push(d);
      }
      load() {
        return Promise.resolve(this);
      }
    },
  );
  Object.defineProperty(document, "fonts", { value: { add: vi.fn() }, configurable: true });
  const font = { id: "pin-test", name: "P", file: "p.ttf", family: "P", group: "x", cell: 1.405,
    ascent: 1.1575, descent: 0.2475, url: "/api/fonts/p.ttf", advances: {} } as SubtitleFont;
  await loadFont(font);
  expect(seen[0]).toMatchObject({ weight: "700", ascentOverride: "115.75%", descentOverride: "24.75%", lineGapOverride: "0%" });
});
