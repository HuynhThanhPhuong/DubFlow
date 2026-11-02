import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { Player } from "./Player";
import { api } from "./api";
import type { Job, Region } from "./types";

vi.mock("./api", async (orig) => {
  const mod = await orig<typeof import("./api")>();
  return {
    ...mod,
    api: { ...mod.api, regions: vi.fn(), saveRegions: vi.fn(), detectLogos: vi.fn() },
  };
});

const region: Region = {
  id: "c1", x: 100, y: 100, width: 200, height: 100, start: 0, end: 10,
  kind: "static", text: "", translation: "", enabled: true,
  auto: true, confirmed: false, label: "Logo",
};
const job = (status: string) =>
  ({ id: "j", status, source_url_path: "/api/jobs/j/source", duration: 10, width: 1920, height: 1080 }) as unknown as Job;
const ui = (j: Job) => (
  <Player job={j} cues={[]} onTime={vi.fn()} seek={{ time: 0, token: 0 }} />
);

beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, get: () => 960 });
  Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, get: () => 540 });
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Player regions", () => {
  it("marks a time edit as confirmed", async () => {
    vi.mocked(api.regions).mockResolvedValue([region]);
    vi.mocked(api.saveRegions).mockResolvedValue([region]);
    render(ui(job("ready")));
    fireEvent.pointerDown(await screen.findByText("Gợi ý: Logo"));
    const to = screen.getByLabelText("Đến (s)");
    fireEvent.change(to, { target: { value: "5" } });
    fireEvent.blur(to);
    await waitFor(() => expect(api.saveRegions).toHaveBeenCalled());
    expect(vi.mocked(api.saveRegions).mock.calls[0][1][0]).toMatchObject({ end: 5, confirmed: true });
  });
  it("shows the suggestion prefix only until the box is confirmed", async () => {
    vi.mocked(api.regions).mockResolvedValue([{ ...region, auto: false, confirmed: true }]);
    render(ui(job("ready")));
    await screen.findByText("Logo");
    expect(screen.queryByText(/Gợi ý/)).toBeNull();
  });
  it("blocks editing while the job is busy", async () => {
    vi.mocked(api.regions).mockResolvedValue([region]);
    render(ui(job("running")));
    await screen.findByText("Gợi ý: Logo");
    expect(screen.getByText("Đang xử lý — chưa sửa vùng che được.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Vẽ vùng che" }) as HTMLButtonElement).disabled).toBe(true);
  });
  it("reverts to the server state when saving fails", async () => {
    vi.mocked(api.regions).mockResolvedValue([region]);
    vi.mocked(api.saveRegions).mockRejectedValue(new Error("lỗi lưu"));
    render(ui(job("ready")));
    await screen.findByText("Gợi ý: Logo");
    fireEvent.click(screen.getByRole("button", { name: /Bỏ vùng/ }));
    await screen.findByText("lỗi lưu");
    expect(screen.getByText("Gợi ý: Logo")).toBeTruthy();
  });
});
