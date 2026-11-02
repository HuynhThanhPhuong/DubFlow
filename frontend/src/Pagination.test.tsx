import { cleanup, fireEvent, render, screen, act } from "@testing-library/react";
import { useRef } from "react";
import { describe, expect, it, vi, afterEach } from "vitest";
import { Pagination, useCapacity } from "./Pagination";

function setup(page = 1) {
  const onChange = vi.fn();
  render(<Pagination total={50} size={10} page={page} onChange={onChange} />);
  return { onChange, input: screen.getByLabelText("Trang") as HTMLInputElement };
}

afterEach(cleanup);

describe("Pagination", () => {
  it("shows layout and commits on Enter", () => {
    const { onChange, input } = setup();
    expect(input.value).toBe("2");
    fireEvent.change(input, { target: { value: "4" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith(3);
  });
  it("commits on blur and clamps to 1..N", () => {
    const { onChange, input } = setup();
    fireEvent.change(input, { target: { value: "99" } });
    fireEvent.blur(input);
    expect(onChange).toHaveBeenLastCalledWith(4);
    fireEvent.change(input, { target: { value: "0" } });
    fireEvent.blur(input);
    expect(onChange).toHaveBeenLastCalledWith(0);
  });
  it("reverts invalid input to the current page", () => {
    const { onChange, input } = setup();
    fireEvent.change(input, { target: { value: "abc" } });
    fireEvent.blur(input);
    expect(onChange).not.toHaveBeenCalled();
    expect(input.value).toBe("2");
  });
  it("prev and next buttons work", () => {
    const { onChange } = setup();
    fireEvent.click(screen.getByText(/Trước/));
    fireEvent.click(screen.getByText(/Sau/));
    expect(onChange.mock.calls).toEqual([[0], [2]]);
  });
});

describe("useCapacity fullscreenchange", () => {
  const OrigRO = globalThis.ResizeObserver;
  afterEach(() => { globalThis.ResizeObserver = OrigRO; });
  it("recomputes capacity after fullscreen exit", () => {
    globalThis.ResizeObserver = class { observe() {} disconnect() {} unobserve() {} } as never;
    let height = 1000;
    function Probe() {
      const ref = useRef<HTMLDivElement>(null);
      const size = useCapacity(ref, 100, 3);
      return <div ref={ref} data-testid="box">{size}</div>;
    }
    render(<Probe />);
    const box = screen.getByTestId("box");
    Object.defineProperty(box, "clientHeight", { get: () => height, configurable: true });
    act(() => { document.dispatchEvent(new Event("fullscreenchange")); });
    expect(box.textContent).toBe("10");
    height = 400; // layout restored after exiting fullscreen, no ResizeObserver callback fired
    act(() => { document.dispatchEvent(new Event("fullscreenchange")); });
    expect(box.textContent).toBe("4");
  });
});
