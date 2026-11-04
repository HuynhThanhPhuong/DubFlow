import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { SrtReviewDialog } from "./SrtReviewDialog";
import type { SrtPreview } from "./types";

afterEach(cleanup);
const preview: SrtPreview = {
  mode: "time",
  total: 3,
  matched: 1,
  problems: 3,
  cues: [
    { id: "a", number: 1, start: 1, end: 3, original: "你好" },
    { id: "b", number: 2, start: 6, end: 8, original: "再见" },
    { id: "c", number: 3, start: 9, end: 11, original: "谢谢" },
  ],
  empty_cues: [],
  rows: [
    { block: 0, number: 1, start: 1, end: 3, text: "Một", cue_id: "a", cue_number: 1, original: "你好", issues: [] },
    { block: 1, number: 2, start: 50, end: 51, text: "Lạc", cue_id: null, cue_number: null, original: "", issues: ["no_match"] },
    { block: 2, number: 3, start: 9, end: 11, text: "", cue_id: "c", cue_number: 3, original: "谢谢", issues: ["empty_block", "dup_time"] },
  ],
};

it("lists problems with reasons, lets the user fix text, re-target and delete, then applies", () => {
  const onApply = vi.fn();
  render(<SrtReviewDialog preview={preview} busy={false} onApply={onApply} onCancel={() => undefined} />);
  expect(screen.getByRole("status").textContent).toContain("Đã ghép 1/3 câu · 3 vấn đề");
  expect(screen.getByText("Không khớp câu nào")).toBeTruthy();
  expect(screen.getByText("Khối rỗng")).toBeTruthy();
  expect(screen.getByText("Trùng thời gian với khối khác")).toBeTruthy();
  expect(screen.queryByLabelText("Lời Việt khối 1")).toBeNull();
  fireEvent.change(screen.getByLabelText("Lời Việt khối 3"), { target: { value: "Ba" } });
  fireEvent.change(screen.getByLabelText("Ghép khối 2 với câu"), { target: { value: "b" } });
  fireEvent.click(screen.getByRole("button", { name: "Nhập" }));
  expect(onApply).toHaveBeenCalledWith({ assignments: { a: "Một", b: "Lạc", c: "Ba" }, translateIds: [] }, false);
});

it("deletes a block and sends the remaining empty cues to Gemini", () => {
  const onApply = vi.fn();
  render(<SrtReviewDialog preview={preview} busy={false} onApply={onApply} onCancel={() => undefined} />);
  fireEvent.click(screen.getAllByRole("button", { name: "Xoá khối" })[0]);
  expect(screen.getByText(/Câu chưa có bản dịch \(2\)/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Nhập và dịch phần còn trống bằng Gemini" }));
  expect(onApply).toHaveBeenCalledWith({ assignments: { a: "Một" }, translateIds: ["b", "c"] }, true);
});

it("Huỷ changes nothing", () => {
  const onApply = vi.fn();
  const onCancel = vi.fn();
  render(<SrtReviewDialog preview={preview} busy={false} onApply={onApply} onCancel={onCancel} />);
  fireEvent.click(screen.getByRole("button", { name: "Huỷ" }));
  expect(onCancel).toHaveBeenCalled();
  expect(onApply).not.toHaveBeenCalled();
});

it("a cue takes one block only: picking it for another block releases the first", () => {
  const onApply = vi.fn();
  render(<SrtReviewDialog preview={preview} busy={false} onApply={onApply} onCancel={() => undefined} />);
  fireEvent.change(screen.getByLabelText("Ghép khối 2 với câu"), { target: { value: "a" } });
  fireEvent.click(screen.getByRole("button", { name: "Nhập" }));
  expect(onApply).toHaveBeenCalledWith({ assignments: { a: "Lạc" }, translateIds: [] }, false);
});
