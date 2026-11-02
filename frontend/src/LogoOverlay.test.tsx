import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { Player } from "./Player";
import { placeLogo } from "./LogoOverlay";
import { api } from "./api";
import { workspaceApi } from "./workspaceApi";
import type { Job, Logo, Overlay } from "./types";

vi.mock("./api", async (orig) => {
  const mod = await orig<typeof import("./api")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      regions: vi.fn(),
      saveRegions: vi.fn(),
      logos: vi.fn(),
      saveOverlays: vi.fn(),
      createTextLogo: vi.fn(),
    },
  };
});
vi.mock("./workspaceApi", () => ({
  workspaceApi: { settings: vi.fn(), updateSettings: vi.fn() },
}));

const logo: Logo = { id: "L1", kind: "image", name: "Kênh A", width: 400, height: 200, url: "/api/logos/L1/image" };
const overlay: Overlay = { id: "o1", logo_id: "L1", x: 100, y: 100, width: 300, height: 150, opacity: 1, start: 0, end: 10 };
// 1920x1080 video in a 960x540 frame: scale 0.5, no letterbox.
const job = (status = "ready", overlays: Overlay[] = []) =>
  ({ id: "j", status, source_url_path: "/api/jobs/j/source", duration: 10, width: 1920, height: 1080, overlays }) as unknown as Job;
const ui = (j: Job) => <Player job={j} cues={[]} onTime={vi.fn()} seek={{ time: 0, token: 0 }} />;
const last = () => {
  const calls = vi.mocked(api.saveOverlays).mock.calls;
  return calls[calls.length - 1][1][0];
};

// jsdom has no PointerEvent: provide one carrying clientX/clientY like browsers do.
class TestPointerEvent extends MouseEvent {
  pointerId: number;
  constructor(type: string, init: MouseEventInit & { pointerId?: number } = {}) {
    super(type, init);
    this.pointerId = init.pointerId ?? 1;
  }
}
(window as unknown as { PointerEvent: unknown }).PointerEvent = TestPointerEvent;

beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, get: () => 960 });
  Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, get: () => 540 });
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
const setup = (j = job("ready", [overlay])) => {
  vi.mocked(api.regions).mockResolvedValue([]);
  vi.mocked(api.logos).mockResolvedValue([logo]);
  vi.mocked(api.saveOverlays).mockImplementation(async (_id, rows) => rows);
  vi.mocked(workspaceApi.settings).mockResolvedValue({ default_overlay: null } as never);
  vi.mocked(workspaceApi.updateSettings).mockResolvedValue({} as never);
  return render(ui(j));
};
const box = () => screen.getByTestId("logo-box-o1");

describe("placeLogo", () => {
  it("puts the logo top-right with a 3% margin and 15% width in source pixels", () => {
    const o = placeLogo(logo, 1920, 1080, 12);
    expect(o).toMatchObject({ width: 288, height: 144, start: 0, end: 12, opacity: 1 });
    expect(o.x).toBeCloseTo(1920 - 57.6 - 288);
    expect(o.y).toBeCloseTo(57.6);
  });
  it("uses the source frame, not the display, for a vertical (letterboxed) video", () => {
    const o = placeLogo(logo, 1080, 1920, 5);
    expect(o.width).toBeCloseTo(162);
    expect(o.x + o.width).toBeCloseTo(1080 - 32.4);
  });
});

describe("Player logo overlay", () => {
  it("picks a logo from the library and saves it in source pixels", async () => {
    setup(job("ready"));
    fireEvent.click(screen.getByText("Chèn logo"));
    fireEvent.click(await screen.findByLabelText("Chèn logo Kênh A"));
    await waitFor(() => expect(api.saveOverlays).toHaveBeenCalled());
    expect(last()).toMatchObject({ logo_id: "L1", width: 288, height: 144, start: 0, end: 10 });
  });

  it("drags and resizes with the aspect locked, saving source pixels", async () => {
    setup();
    fireEvent.pointerDown(box(), { clientX: 200, clientY: 100, pointerId: 1 });
    fireEvent.pointerMove(box(), { clientX: 250, clientY: 130, pointerId: 1 });
    fireEvent.pointerUp(box(), { clientX: 250, clientY: 130, pointerId: 1 });
    await waitFor(() => expect(api.saveOverlays).toHaveBeenCalledTimes(1));
    // +50/+30 display px at scale 0.5 = +100/+60 source px
    expect(last()).toMatchObject({ x: 200, y: 160, width: 300, height: 150 });
    const handle = screen.getByTestId("logo-handle-se");
    fireEvent.pointerDown(handle, { pointerId: 2 });
    fireEvent.pointerMove(handle, { clientX: 200, clientY: 400, pointerId: 2 });
    fireEvent.pointerUp(handle, { pointerId: 2 });
    await waitFor(() => expect(api.saveOverlays).toHaveBeenCalledTimes(2));
    // anchor (200,160); pointer source (400,800): w=200, h locked to w/2 = 100
    expect(last().width).toBeCloseTo(200);
    expect(last().height).toBeCloseTo(100);
  });

  it("frees the aspect with Shift", async () => {
    setup();
    fireEvent.pointerDown(box(), { clientX: 0, clientY: 0, pointerId: 1 });
    fireEvent.pointerUp(box(), { pointerId: 1 });
    const handle = screen.getByTestId("logo-handle-se");
    fireEvent.pointerDown(handle, { pointerId: 2 });
    fireEvent.pointerMove(handle, { clientX: 300, clientY: 300, pointerId: 2, shiftKey: true });
    fireEvent.pointerUp(handle, { pointerId: 2 });
    await waitFor(() => expect(api.saveOverlays).toHaveBeenCalled());
    expect(last()).toMatchObject({ width: 500, height: 500 });
  });

  it("updates the preview opacity and saves it", async () => {
    setup();
    fireEvent.pointerDown(box(), { clientX: 0, clientY: 0, pointerId: 1 });
    fireEvent.pointerUp(box(), { pointerId: 1 });
    fireEvent.change(screen.getByLabelText("Độ mờ logo"), { target: { value: "0.5" } });
    expect(screen.getByTestId("logo-img-o1")).toHaveProperty("style.opacity","0.5");
    await waitFor(() => expect(api.saveOverlays).toHaveBeenCalled());
    expect(last().opacity).toBe(0.5);
  });

  it("reverts to the server state when saving fails", async () => {
    setup();
    vi.mocked(api.saveOverlays).mockRejectedValue(new Error("Lỗi lưu"));
    fireEvent.pointerDown(box(), { clientX: 0, clientY: 0, pointerId: 1 });
    fireEvent.pointerUp(box(), { pointerId: 1 });
    fireEvent.change(screen.getByLabelText("Độ mờ logo"), { target: { value: "0.5" } });
    expect(await screen.findByText("Lỗi lưu")).toBeTruthy();
    expect(screen.getByTestId("logo-img-o1")).toHaveProperty("style.opacity","1");
  });

  it("saves the default overlay as fractions from the checkbox", async () => {
    setup();
    fireEvent.pointerDown(box(), { clientX: 0, clientY: 0, pointerId: 1 });
    fireEvent.pointerUp(box(), { pointerId: 1 });
    fireEvent.click(screen.getByLabelText("Tự chèn cho video mới"));
    await waitFor(() => expect(workspaceApi.updateSettings).toHaveBeenCalled());
    expect(workspaceApi.updateSettings).toHaveBeenCalledWith({
      default_overlay: { logo_id: "L1", fx: 100 / 1920, fy: 100 / 1080, fw: 300 / 1920, opacity: 1 },
    });
    fireEvent.click(screen.getByLabelText("Tự chèn cho video mới"));
    await waitFor(() => expect(workspaceApi.updateSettings).toHaveBeenLastCalledWith({ default_overlay: null }));
  });

  it("is read-only while the job is busy", async () => {
    setup(job("rendering", [overlay]));
    expect((await screen.findByText("Chèn logo")).closest("button")?.disabled).toBe(true);
    fireEvent.pointerDown(box(), { clientX: 0, clientY: 0, pointerId: 1 });
    expect(screen.queryByTestId("logo-handle-se")).toBeNull();
    expect((screen.getByLabelText("Độ mờ logo") as HTMLInputElement).disabled).toBe(true);
  });

  it("creates a text logo and shows the server image", async () => {
    setup(job("ready"));
    vi.mocked(api.createTextLogo).mockResolvedValue({
      id: "T1", kind: "text", name: "TikTok @abc", width: 300, height: 90, url: "/api/logos/T1/image", text: "@abc",
    });
    fireEvent.click(screen.getByText("Chèn logo"));
    fireEvent.click(await screen.findByText("Tạo logo chữ"));
    fireEvent.change(screen.getByPlaceholderText("@abc"), { target: { value: "@abc" } });
    fireEvent.change(screen.getByPlaceholderText("TikTok @abc"), { target: { value: "TikTok @abc" } });
    expect(screen.getByTestId("text-preview").textContent).toBe("@abc");
    fireEvent.click(screen.getByText("Lưu mẫu"));
    expect((await screen.findByTestId("saved-preview")).getAttribute("src")).toBe("/api/logos/T1/image");
    expect(api.createTextLogo).toHaveBeenCalledWith({
      name: "TikTok @abc",
      text: "@abc",
      style: { font: "Roboto", color: "#ffffff", stroke_color: "#000000", stroke_width: 4, size: 96 },
    });
  });

  it("shows the server message when text logo creation fails", async () => {
    setup(job("ready"));
    vi.mocked(api.createTextLogo).mockRejectedValue(new Error("Chữ quá dài."));
    fireEvent.click(screen.getByText("Chèn logo"));
    fireEvent.click(await screen.findByText("Tạo logo chữ"));
    fireEvent.change(screen.getByPlaceholderText("@abc"), { target: { value: "x" } });
    fireEvent.click(screen.getByText("Lưu mẫu"));
    expect(await screen.findByText("Chữ quá dài.")).toBeTruthy();
  });
});
