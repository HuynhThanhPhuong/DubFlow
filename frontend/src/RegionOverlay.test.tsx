import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RegionOverlay } from "./RegionOverlay";
import { SettingsDialog } from "./Dialogs";
import { normalizeBox, toDisplay, toSource } from "./regionGeometry";
import type { Job, Region } from "./types";

vi.mock("./api", async (orig) => {
  const mod = await orig<typeof import("./api")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      regions: vi.fn().mockResolvedValue([
        {
          id: "r1", x: 1, y: 2, width: 30, height: 40, start: 0, end: 5,
          kind: "static", text: "", translation: "", enabled: true,
        },
      ]),
    },
  };
});

afterEach(cleanup);

// jsdom has no PointerEvent: provide one carrying clientX/clientY like browsers do.
class TestPointerEvent extends MouseEvent {
  pointerId: number;
  constructor(type: string, init: MouseEventInit & { pointerId?: number } = {}) {
    super(type, init);
    this.pointerId = init.pointerId ?? 1;
  }
}
(window as unknown as { PointerEvent: unknown }).PointerEvent = TestPointerEvent;

describe("regionGeometry", () => {
  const letter = { left: 0, top: 60, width: 960, height: 540 };
  it("maps letterboxed display points to source pixels", () => {
    expect(toSource({ x: 100, y: 160 }, { left: 0, top: 60, width: 960, height: 540 }, 1920, 1080)).toEqual({ x: 200, y: 200 });
    // scale 0.5 case from the brief
    expect(toSource({ x: 100, y: 160 }, { left: 0, top: 60, width: 960, height: 540 }, 1920, 1080)).toEqual({ x: 200, y: 200 });
    expect(toSource({ x: 50, y: 100 }, letter, 1920, 1080)).toEqual({ x: 100, y: 80 });
  });
  it("maps pillarboxed display points", () => {
    const pillar = { left: 100, top: 0, width: 270, height: 480 };
    expect(toSource({ x: 235, y: 240 }, pillar, 540, 960)).toEqual({ x: 270, y: 480 });
  });
  it("clamps to the frame", () => {
    expect(toSource({ x: -50, y: 10 }, letter, 1920, 1080)).toEqual({ x: 0, y: 0 });
    expect(toSource({ x: 5000, y: 5000 }, letter, 1920, 1080)).toEqual({ x: 1920, y: 1080 });
  });
  it("round trips and enforces a minimum box", () => {
    const d = toDisplay({ x: 200, y: 200, width: 100, height: 50 }, letter, 1920, 1080);
    expect(d).toEqual({ left: 100, top: 160, width: 50, height: 25 });
    const b = normalizeBox({ x: 10, y: 10 }, { x: 12, y: 5 });
    expect(b).toEqual({ x: 10, y: 5, width: 8, height: 8 });
  });
});

const rect = { left: 0, top: 60, width: 960, height: 540 };
const auto: Region = {
  id: "a1", x: 100, y: 100, width: 200, height: 100, start: 1, end: 4,
  kind: "static", text: "", translation: "", enabled: true,
  auto: true, confirmed: false, label: "Logo",
};
const props = { rect, videoWidth: 1920, videoHeight: 1080, duration: 10, drawing: false, onDrawEnd: vi.fn() };

describe("RegionOverlay", () => {
  it("rejects an auto candidate with the cross button", () => {
    const onChange = vi.fn();
    render(<RegionOverlay {...props} regions={[auto]} onChange={onChange} />);
    expect(screen.getByText("Logo")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Bỏ vùng/ }));
    expect(onChange).toHaveBeenCalledWith([{ ...auto, enabled: false, confirmed: true }]);
  });
  it("confirms an auto candidate with the tick button", () => {
    const onChange = vi.fn();
    render(<RegionOverlay {...props} regions={[auto]} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: /Giữ vùng/ }));
    expect(onChange).toHaveBeenCalledWith([{ ...auto, enabled: true, confirmed: true }]);
  });
  it("hides rejected regions", () => {
    render(<RegionOverlay {...props} regions={[{ ...auto, enabled: false, confirmed: true }]} onChange={vi.fn()} />);
    expect(screen.queryByText("Logo")).toBeNull();
  });
  it("draws a new region in source pixels covering the whole video time", () => {
    const onChange = vi.fn();
    const onDrawEnd = vi.fn();
    render(<RegionOverlay {...props} drawing regions={[]} onChange={onChange} onDrawEnd={onDrawEnd} />);
    const layer = screen.getByTestId("region-draw-layer");
    fireEvent.pointerDown(layer, { clientX: 100, clientY: 160, pointerId: 1 });
    fireEvent.pointerMove(layer, { clientX: 200, clientY: 260, pointerId: 1 });
    fireEvent.pointerUp(layer, { clientX: 200, clientY: 260, pointerId: 1 });
    expect(onChange).toHaveBeenCalledTimes(1);
    const [rows] = onChange.mock.calls[0];
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      x: 200, y: 200, width: 200, height: 200,
      start: 0, end: 10, kind: "static", auto: false, confirmed: true, enabled: true, label: "Vùng vẽ tay",
    });
    expect(onDrawEnd).toHaveBeenCalled();
  });
});

describe("regions dialog", () => {
  it("no longer renders pixel inputs", async () => {
    render(
      <SettingsDialog
        job={{ id: "j", width: 1920, height: 1080, duration: 10 } as Job}
        kind="regions"
        onClose={vi.fn()}
        onError={vi.fn()}
        onSaved={vi.fn()}
      />,
    );
    await waitFor(() => expect(screen.getByText(/Vùng 1/)).toBeTruthy());
    expect(screen.queryByText(/X \(px\)/)).toBeNull();
    expect(screen.queryByText(/Rộng \(px\)/)).toBeNull();
    expect(screen.getByText(/Bắt đầu \(s\)/)).toBeTruthy();
  });
});
