import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "./api";
import { NamesDialog } from "./NamesDialog";
import { TranslatePanel } from "./TranslatePanel";
import { JobDetailsDialog } from "./JobActivity";
import { CueList } from "./CueList";
import { SrtReviewDialog } from "./SrtReviewDialog";
import type { Cue, Job, JobNames, JobErrorItem, SrtPreview } from "./types";

const job = { id: "j", mode: "vietsub", status: "awaiting_review", warnings: [], collection_id: "c" } as unknown as Job;
const names: JobNames = {
  fingerprint: "source-1",
  groups: [{ from_vi: "A Tấn", forms_zh: ["阿晋"], confusable: true,
    occurrences: [
      { cue_id: "a", number: 31, start: 65.1, end: 66.7, original: "叫你阿晋如何", translated: "Gọi ngươi là A Tấn thì sao?" },
      { cue_id: "real", number: 47, start: 94.9, end: 98.5, original: "我希望阿晋永远", translated: "Ta mong A Tấn mãi mãi" },
    ] }, { from_vi: "A Âm", forms_zh: ["阿音"], confusable: true, occurrences: [] }],
};
const cues: Cue[] = [{ id: "a", start: 65.1, end: 66.7, speaker: "", original: "叫你阿音如何", text: "Gọi ngươi là A Âm thì sao?" }];
beforeEach(() => {
  vi.spyOn(api, "names").mockResolvedValue(names);
  vi.spyOn(api, "applyName").mockResolvedValue({ ...names, count: 1, cues });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it("opens name editing from translation tools, closes the popover and lists confusable groups", async () => {
  render(<TranslatePanel job={job} providerLabel="Gemini" ready={false} disabled={false} canExport onJob={vi.fn()} onCues={vi.fn()} onError={vi.fn()} onNotice={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Dịch ▾" }));
  fireEvent.click(screen.getByRole("button", { name: "Sửa tên nhân vật" }));
  expect(screen.queryByRole("region", { name: "Công cụ dịch" })).toBeNull();
  const dialog = await screen.findByRole("dialog", { name: "Sửa tên nhân vật" });
  expect(await within(dialog).findByRole("button", { name: /A Tấn.*阿晋.*2 lần xuất hiện.*dễ nhầm/ })).toBeTruthy();
  expect(within(dialog).getByRole("button", { name: /A Âm.*阿音/ })).toBeTruthy();
  expect((screen.getByRole("checkbox", { name: "Đổi tên câu 31" }) as HTMLInputElement).checked).toBe(true);
  expect((screen.getByRole("checkbox", { name: "Đổi tên câu 47" }) as HTMLInputElement).checked).toBe(true);
});

it("applies only selected cues with source repair, collection scope and the preview fingerprint", async () => {
  const onCues = vi.fn(), onNotice = vi.fn();
  render(<NamesDialog job={job} onClose={vi.fn()} onCues={onCues} onNotice={onNotice} />);
  fireEvent.change(await screen.findByLabelText("Tên Việt mới"), { target: { value: "A Âm" } });
  fireEvent.click(screen.getByRole("checkbox", { name: "Đổi tên câu 47" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Sửa luôn chữ Hán" }));
  fireEvent.change(screen.getByLabelText("Chữ Hán mới"), { target: { value: "阿音" } });
  fireEvent.click(screen.getByRole("button", { name: "Lưu cho cả bộ sưu tập" }));
  await waitFor(() => expect(api.applyName).toHaveBeenCalledWith("j", {
    from_vi: "A Tấn", to_vi: "A Âm", cue_ids: ["a"], fix_source: { from_zh: "阿晋", to_zh: "阿音" }, scope: "collection", fingerprint: "source-1",
  }));
  expect(onCues).toHaveBeenCalledWith(cues);
  expect(await screen.findByRole("status")).toHaveProperty("textContent", "Đã đổi 1 câu");
  expect(onNotice).toHaveBeenCalledWith("Đã đổi 1 câu");
});

it("searches a manually entered Han name and closes before jumping to a cue", async () => {
  const events: string[] = [];
  render(<NamesDialog job={job} onClose={() => events.push("close")} onCues={vi.fn()} onNotice={vi.fn()} onJump={(id) => events.push(id)} />);
  await screen.findByLabelText("Tên Việt mới");
  fireEvent.change(screen.getByLabelText("Tìm hoặc thêm tên"), { target: { value: "古晋" } });
  fireEvent.click(screen.getByRole("button", { name: "Tìm / thêm" }));
  await waitFor(() => expect(api.names).toHaveBeenCalledWith("j", "古晋"));
  fireEvent.click(await screen.findByRole("button", { name: "Câu 47" }));
  expect(events).toEqual(["close", "real"]);
});

it("selects an added Han group even when existing groups precede it and saves its mapping", async () => {
  vi.mocked(api.names).mockResolvedValueOnce(names).mockResolvedValueOnce({ ...names, groups: [...names.groups, { from_vi: "", forms_zh: ["古晋"], confusable: false, occurrences: [names.groups[0].occurrences[0]] }] });
  render(<NamesDialog job={job} onClose={vi.fn()} onCues={vi.fn()} onNotice={vi.fn()} />);
  await screen.findByLabelText("Tên Việt mới");
  fireEvent.change(screen.getByLabelText("Tìm hoặc thêm tên"), { target: { value: "古晋" } });
  fireEvent.click(screen.getByRole("button", { name: "Tìm / thêm" }));
  await waitFor(() => expect(screen.getByRole("button", { name: /古晋.*1 lần xuất hiện/ }).getAttribute("aria-pressed")).toBe("true"));
  fireEvent.change(screen.getByLabelText("Tên Việt mới"), { target: { value: "Cổ Tấn" } });
  fireEvent.click(screen.getByRole("button", { name: "Áp dụng" }));
  await waitFor(() => expect(api.applyName).toHaveBeenCalledWith("j", expect.objectContaining({ from_vi: "古晋", to_vi: "Cổ Tấn", cue_ids: ["a"] })));
});

it("keeps selected edits visible when a stale fingerprint is rejected", async () => {
  vi.mocked(api.applyName).mockRejectedValue(new Error("Nội dung đã đổi. Hãy tải lại danh sách tên."));
  const onCues = vi.fn();
  render(<NamesDialog job={job} onClose={vi.fn()} onCues={onCues} onNotice={vi.fn()} />);
  fireEvent.change(await screen.findByLabelText("Tên Việt mới"), { target: { value: "A Âm" } });
  fireEvent.click(screen.getByRole("button", { name: "Áp dụng" }));
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Nội dung đã đổi. Hãy tải lại danh sách tên.");
  expect(onCues).not.toHaveBeenCalled();
  expect(screen.getByLabelText("Tên Việt mới")).toHaveProperty("value", "A Âm");
});

it("shows an ambiguity crop and resolves only the selected name position with a fingerprint", async () => {
  const resolve = vi.spyOn(api, "resolveName").mockResolvedValue({ ...names, count: 1, cues });
  const onSourceChanged = vi.fn(), refresh = vi.fn();
  const item: JobErrorItem = { key: "name:a", kind: "audit", severity: "error", code: "NAME_OCR_AMBIGUOUS", cue_id: "a", cue_number: 31, step: "Phân tích", time: "2026-11-05", message: "Tên có thể đọc sai: 阿晋/阿音", actions: ["jump", "dismiss"], fingerprint: "source-1", name_review: [{ from_zh: "阿晋", variants: ["阿晋", "阿音"], position: 2 }] };
  render(<JobDetailsDialog job={job} notes={[]} onClose={vi.fn()} errors={{ count: 1, items: [item], onSourceChanged, refresh }} />);
  expect(screen.getByRole("img", { name: "Chữ Trung trên hình câu 31" }).getAttribute("src")).toBe("/api/jobs/j/name-crop/a");
  fireEvent.click(screen.getByRole("button", { name: "Chọn 阿音 ở vị trí 3" }));
  await waitFor(() => expect(resolve).toHaveBeenCalledWith("j", { cue_id: "a", from_zh: "阿晋", to_zh: "阿音", position: 2, fingerprint: "source-1" }));
  expect(onSourceChanged).toHaveBeenCalledWith(cues);
  expect(refresh).toHaveBeenCalled();
  expect(screen.getByText("Tên có thể đọc sai: 阿晋/阿音").closest("li")?.classList.contains("error")).toBe(true);
});

it("explains glossary name mismatches in import review and keeps the Vietnamese text editable", () => {
  const preview: SrtPreview = { mode: "index", total: 1, matched: 1, problems: 1, empty_cues: [], fingerprint: "source-1", cues: [{ id: "a", number: 1, start: 1, end: 2, original: "阿音" }],
    rows: [{ block: 0, number: 1, start: 1, end: 2, text: "A Phổ", cue_id: "a", cue_number: 1, original: "阿音", issues: ["name_mismatch"], name_issues: ["Tên 阿音 cần dùng A Âm"] }] };
  const onApply = vi.fn();
  render(<SrtReviewDialog preview={preview} busy={false} onApply={onApply} onCancel={vi.fn()} />);
  expect(screen.getByText("Tên chưa khớp danh sách đã lưu")).toBeTruthy();
  expect(screen.getByText("Tên 阿音 cần dùng A Âm")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Lời Việt khối 1"), { target: { value: "A Âm" } });
  fireEvent.click(screen.getByRole("button", { name: "Nhập" }));
  expect(onApply).toHaveBeenCalledWith({ assignments: { a: "A Âm" }, translateIds: [] }, false);
});

it.each(["dub", "tm", "vietsub"])("uses red speech mismatch for %s only when the mode uses speech", (mode) => {
  const cue: Cue = { ...cues[0], source: "ocr+asr", asr_text: "叫你阿晋如何", auto_flags: ["Chữ trên hình và lời nghe được khác nhau."] };
  render(<CueList cues={[cue]} active="a" disabled={false} loading={false} error="" onSelect={vi.fn()} onEdit={vi.fn()} mode={mode}
    audit={{ a: [{ code: "OCR_ASR_MISMATCH", severity: "warn", message: "Giọng và chữ khác tên." }] }} />);
  if (mode === "vietsub") {
    expect(screen.queryByText("Giọng và chữ khác tên.")).toBeNull();
    expect(document.querySelector(".cue-flag-badge")).toBeNull();
    expect(screen.getByText("Chữ trên hình")).toBeTruthy();
    expect(screen.queryByText("Nghe được:")).toBeNull();
  } else {
    expect(document.querySelector(".cue-flag-badge")?.classList.contains("error")).toBe(true);
    expect(screen.getByText("Hình + giọng")).toBeTruthy();
  }
});
