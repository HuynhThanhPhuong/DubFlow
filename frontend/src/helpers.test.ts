import { describe, it, expect } from "vitest";
import { editCue, playerSource, parseRoute, validateCues } from "./helpers";
import type { Cue, Job } from "./types";
const cues: Cue[] = [
  { id: "a", start: 1, end: 3, text: "Cũ", original: "原文", speaker: "A" },
  { id: "b", start: 4, end: 5, text: "Hai", original: "二", speaker: "B" },
];
describe("cue editing", () => {
  it("updates one cue immutably without losing source and timing", () => {
    const result = editCue(cues, "a", { text: "Mới" });
    expect(result[0]).toEqual({ ...cues[0], text: "Mới" });
    expect(cues[0].text).toBe("Cũ");
    expect(result[1]).toBe(cues[1]);
  });
  it("rejects inverted times but allows saving untranslated draft for regeneration", () => {
    expect(validateCues(editCue(cues, "a", { end: 0 }), 10)).toBeTruthy();
    expect(validateCues(editCue(cues, "a", { text: "" }), 10)).toBeNull();
    expect(validateCues(cues, 10)).toBeNull();
  });
});
describe("player source", () => {
  const job = {
    source_url_path: "/api/jobs/a/source",
    output_url: null,
  } as Job;
  it("never substitutes source for a missing result", () => {
    expect(playerSource(job, "output")).toBeUndefined();
    expect(playerSource(job, "source")).toBe(job.source_url_path);
  });
  it("selects actual output only", () =>
    expect(
      playerSource({ ...job, output_url: "/api/jobs/a/output" }, "output"),
    ).toBe("/api/jobs/a/output"));
});
it("round trips encoded job ids in hash routes", () =>
  expect(parseRoute("#editor?job=a%20b")).toEqual({
    page: "editor",
    jobId: "a b",
  }));
