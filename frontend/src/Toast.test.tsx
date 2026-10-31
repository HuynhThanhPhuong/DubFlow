import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Toast } from "./ui";
import { vietnameseMessage } from "./messages";
afterEach(() => { cleanup(); vi.useRealTimers(); });
it("automatically closes a success notice even when its parent rerenders", () => {
  vi.useFakeTimers(); const close=vi.fn();
  const view=render(<Toast message="Đã gửi vào hàng đợi xử lý." kind="success" onClose={close}/>);
  act(() => vi.advanceTimersByTime(2500));
  view.rerender(<Toast message="Đã gửi vào hàng đợi xử lý." kind="success" onClose={() => close()}/>);
  act(() => vi.advanceTimersByTime(500));
  expect(screen.getByRole("status").className).toContain("toast-closing");
  expect(close).not.toHaveBeenCalled();
  act(() => vi.advanceTimersByTime(240));
  expect(close).toHaveBeenCalledOnce();
});
it("gives errors more reading time and translates the existing English gate", () => {
  vi.useFakeTimers(); const close=vi.fn();
  render(<Toast kind="error" message={vietnameseMessage("Review source transcript and enter Vietnamese text in cues; offline manual translation is the default")} onClose={close}/>);
  expect(screen.getByRole("alert").textContent).toContain("Chưa có đủ lời Việt");
  expect(screen.queryByText(/Tự đóng sau/)).toBeNull();
  act(() => vi.advanceTimersByTime(4000)); expect(close).not.toHaveBeenCalled();
  act(() => vi.advanceTimersByTime(1000)); expect(screen.getByRole("alert").className).toContain("toast-closing");
  act(() => vi.advanceTimersByTime(240)); expect(close).toHaveBeenCalledOnce();
});
