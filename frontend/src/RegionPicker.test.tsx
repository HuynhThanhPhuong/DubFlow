import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RegionPicker } from "./RegionPicker";
import type { Job } from "./types";

// jsdom has no PointerEvent: provide one carrying clientX/clientY like browsers do.
class TestPointerEvent extends MouseEvent {
  pointerId: number;
  constructor(type: string, init: MouseEventInit & { pointerId?: number } = {}) {
    super(type, init);
    this.pointerId = init.pointerId ?? 1;
  }
}
(window as unknown as { PointerEvent: unknown }).PointerEvent = TestPointerEvent;

const job = { id: "j1", duration: 60, width: 1920, height: 1080, status: "awaiting_regions" } as unknown as Job;

// Stage 960x600 for a 1920x1080 video -> letterbox: 960x540 at top 30, scale 0.5.
beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
    left: 0, top: 0, width: 960, height: 600, right: 960, bottom: 600, x: 0, y: 0, toJSON: () => ({}),
  });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const drag = (el: Element, from: [number, number], to: [number, number]) => {
  fireEvent.pointerDown(el, { clientX: from[0], clientY: from[1] });
  fireEvent.pointerMove(el, { clientX: to[0], clientY: to[1] });
  fireEvent.pointerUp(el, { clientX: to[0], clientY: to[1] });
};

describe("RegionPicker", () => {
  it("draws boxes in source pixels under letterboxing and saves them", () => {
    const onSave = vi.fn();
    render(<RegionPicker job={job} onSave={onSave} />);
    const stage = screen.getByTestId("rp-stage");
    expect(screen.getByAltText("Khung hình video").getAttribute("src")).toBe("/api/jobs/j1/frame?t=5");
    // subtitle strip: display (100,430)-(500,500) -> source (200,800)-(1000,940)
    drag(stage, [100, 430], [500, 500]);
    fireEvent.click(screen.getByRole("button", { name: "Logo" }));
    drag(stage, [10, 40], [60, 90]); // -> (20,20,100,100)
    fireEvent.click(screen.getByRole("button", { name: "Chữ trên màn hình" }));
    drag(stage, [200, 100], [300, 150]); // -> (400,140,200,100)
    fireEvent.click(screen.getByRole("button", { name: "Lưu vùng" }));
    expect(onSave).toHaveBeenCalledWith(
      { no_hard_subs: false, subtitle: [200, 800, 800, 140], logos: [[20, 20, 100, 100]], screen_text: [[400, 140, 200, 100]] },
      false,
    );
  });

  it("moves and resizes in source pixels, and deletes the selected box", () => {
    const onSave = vi.fn();
    render(<RegionPicker job={{ ...job, analysis_regions: { no_hard_subs: false, subtitle: [200, 800, 800, 140], logos: [], screen_text: [] } } as Job} onSave={onSave} />);
    const stage = screen.getByTestId("rp-stage");
    const box = screen.getByTestId("rp-subtitle-0");
    drag(box, [300, 460], [320, 440]); // move by (+40, -40) source px
    fireEvent.click(screen.getByRole("button", { name: "Lưu & phân tích" }));
    expect(onSave).toHaveBeenLastCalledWith(expect.objectContaining({ subtitle: [240, 760, 800, 140] }), true);
    // resize: drag the se corner by (+20,+10) display = (+40,+20) source
    fireEvent.click(screen.getByRole("button", { name: "Lưu vùng" }));
    fireEvent.pointerDown(screen.getByTestId("rp-handle-se"), { clientX: 520, clientY: 480 });
    fireEvent.pointerMove(stage, { clientX: 540, clientY: 490 });
    fireEvent.pointerUp(stage, { clientX: 540, clientY: 490 });
    fireEvent.click(screen.getByRole("button", { name: "Lưu vùng" }));
    expect(onSave).toHaveBeenLastCalledWith(expect.objectContaining({ subtitle: [240, 760, 800 + 40, 140 + 20] }), false);
    fireEvent.click(screen.getByRole("button", { name: "Xoá vùng đã chọn" }));
    expect(screen.queryByTestId("rp-subtitle-0")).toBeNull();
  });

  it("requires the subtitle strip unless the video has no hard subs", () => {
    const onSave = vi.fn();
    render(<RegionPicker job={job} onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "Lưu & phân tích" }));
    expect(screen.getByRole("alert").textContent).toContain("Hãy vẽ dải sub Trung");
    expect(onSave).not.toHaveBeenCalled();
    fireEvent.click(screen.getByLabelText("Video không có sub cứng"));
    fireEvent.click(screen.getByRole("button", { name: "Lưu & phân tích" }));
    expect(onSave).toHaveBeenCalledWith({ no_hard_subs: true, subtitle: null, logos: [], screen_text: [] }, true);
  });

  it("steps the frame by 5 seconds", () => {
    render(<RegionPicker job={job} onSave={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "+5 giây" }));
    expect(screen.getByAltText("Khung hình video").getAttribute("src")).toBe("/api/jobs/j1/frame?t=10");
    fireEvent.click(screen.getByRole("button", { name: "-5 giây" }));
    fireEvent.click(screen.getByRole("button", { name: "-5 giây" }));
    expect(screen.getByAltText("Khung hình video").getAttribute("src")).toBe("/api/jobs/j1/frame?t=0");
  });
});
