import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { FontPopover } from "./FontPopover";
import { cueLayout, regionLayout } from "./SubtitlePreview";
import { api } from "./api";
import type { Cue, Job, SubtitleStyle } from "./types";

vi.mock("./api", () => ({ api: { fonts: vi.fn(), updateJob: vi.fn() } }));
vi.mock("./workspaceApi", () => ({
  workspaceApi: { updateSettings: vi.fn() },
}));
vi.mock("./fonts", () => ({
  loadFont: vi.fn(async (f) => f),
  fontFamily: (f: { family: string }) => f.family,
  useSubtitleFont: vi.fn(),
}));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const style = {
  font: "Public Sans",
  font_id: "public-sans",
  cell: 1.405,
  bold: true,
  size: 40,
  outline: 2.4,
  margin_v: 29,
  max_lines: 3,
  fixed_size: true,
  italic: true,
  advances: { A: 1, " ": 0.25 },
} as SubtitleStyle;

it("uses one fixed size across regions, flags long text and keeps three lines", () => {
  const cues = [12, 60].map((text_height, i) => ({
    id: String(i),
    start: i * 3,
    end: i * 3 + 2,
    original: "",
    speaker: "",
    text: Array(32).fill("A").join(" "),
    box: [100, 650, 400, 710],
    band: [80, 600, 420, 720],
    region: i,
    text_height,
  })) as Cue[];
  const first = cueLayout(cues, 0, 1280, 720, 1, style);
  const second = cueLayout(cues, 1, 1280, 720, 4, style);
  expect(first.size).toBe(40);
  expect(second.size).toBe(40);
  expect(first.lines).toHaveLength(3);
  expect(first.overflow).toBe(true);
  const fs = Math.round(first.size * style.cell!);
  expect(first.y + (fs * first.lines.length) / 2).toBeLessThanOrEqual(
    720 * 0.98,
  );
  expect(first.y - (fs * first.lines.length) / 2).toBeGreaterThanOrEqual(
    720 * 0.02,
  );
  const auxiliary = regionLayout(
    { ...cues[0], kind: "supplementary" },
    1280,
    720,
    style,
  );
  expect(auxiliary.size).toBe(34);
});

it("previews size immediately and saves size and italic per job", async () => {
  const job = {
    id: "one",
    subtitle_font: "public-sans",
    subtitle_size: 5.5,
    subtitle_italic: true,
  } as Job;
  vi.mocked(api.fonts).mockResolvedValue({ default: "public-sans", fonts: [] });
  vi.mocked(api.updateJob).mockImplementation(async (_id, values) => ({
    ...job,
    ...values,
  }));
  const onStylePreview = vi.fn();
  render(
    <FontPopover
      job={job}
      defaultFont="public-sans"
      disabled={false}
      onPreview={vi.fn()}
      onStylePreview={onStylePreview}
      onJob={vi.fn()}
      onDefault={vi.fn()}
      onError={vi.fn()}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Phông chữ ▾" }));
  const size = screen.getByRole("slider", { name: "Cỡ chữ" });
  expect((size as HTMLInputElement).value).toBe("5.5");
  fireEvent.change(size, { target: { value: "7" } });
  expect(onStylePreview).toHaveBeenLastCalledWith({
    subtitle_size: 7,
    subtitle_italic: true,
  });
  fireEvent.pointerUp(size);
  await waitFor(() =>
    expect(api.updateJob).toHaveBeenCalledWith("one", {
      subtitle_size: 7,
      subtitle_italic: true,
    }),
  );
  fireEvent.click(screen.getByRole("checkbox", { name: "Nghiêng" }));
  await waitFor(() =>
    expect(api.updateJob).toHaveBeenLastCalledWith("one", {
      subtitle_size: 7,
      subtitle_italic: false,
    }),
  );
  expect(screen.getByRole("button", { name: "Vừa" })).toBeTruthy();
});

it("preserves legacy size when toggling italic and applies a preset explicitly", async () => {
  const job = {
    id: "legacy",
    subtitle_font: "public-sans",
    subtitle_size: null,
    subtitle_italic: false,
  } as Job;
  vi.mocked(api.fonts).mockResolvedValue({ default: "public-sans", fonts: [] });
  vi.mocked(api.updateJob).mockImplementation(async (_id, values) => ({
    ...job,
    ...values,
  }));
  const onStylePreview = vi.fn();
  render(
    <FontPopover
      job={job}
      defaultFont="public-sans"
      disabled={false}
      onPreview={vi.fn()}
      onStylePreview={onStylePreview}
      onJob={vi.fn()}
      onDefault={vi.fn()}
      onError={vi.fn()}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Phông chữ ▾" }));
  expect(api.updateJob).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("checkbox", { name: "Nghiêng" }));
  await waitFor(() =>
    expect(api.updateJob).toHaveBeenLastCalledWith("legacy", {
      subtitle_italic: true,
    }),
  );
  expect(onStylePreview).toHaveBeenCalledWith({ subtitle_italic: true });
  fireEvent.click(screen.getByRole("button", { name: "Vừa" }));
  await waitFor(() =>
    expect(api.updateJob).toHaveBeenLastCalledWith("legacy", {
      subtitle_size: 5.5,
      subtitle_italic: true,
    }),
  );
});

it("keeps rounded ASS positions inside both video safe edges", () => {
  for (const box of [
    [100, -10, 800, 20],
    [100, 700, 800, 735],
  ]) {
    const cue = {
      id: "safe",
      start: 0,
      end: 2,
      text: "A A",
      original: "",
      speaker: "",
      box,
    } as Cue;
    const fit = cueLayout([cue], 0, 1280, 720, 1, style);
    const half = (Math.round(fit.size * style.cell!) * fit.lines.length) / 2;
    expect(Math.round(fit.y) - half).toBeGreaterThanOrEqual(720 * 0.02);
    expect(Math.round(fit.y) + half).toBeLessThanOrEqual(720 * 0.98);
  }
});

it("restores legacy size after a rejected size change", async () => {
  const job = {
    id: "legacy-failure",
    subtitle_font: "public-sans",
    subtitle_size: null,
    subtitle_italic: false,
  } as Job;
  vi.mocked(api.fonts).mockResolvedValue({ default: "public-sans", fonts: [] });
  vi.mocked(api.updateJob)
    .mockRejectedValueOnce(new Error("Failed"))
    .mockImplementation(async (_id, values) => ({ ...job, ...values }));
  const onError = vi.fn();
  render(
    <FontPopover
      job={job}
      defaultFont="public-sans"
      disabled={false}
      onPreview={vi.fn()}
      onStylePreview={vi.fn()}
      onJob={vi.fn()}
      onDefault={vi.fn()}
      onError={onError}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Phông chữ ▾" }));
  fireEvent.click(screen.getByRole("button", { name: "Lớn" }));
  await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole("checkbox", { name: "Nghiêng" }));
  await waitFor(() =>
    expect(api.updateJob).toHaveBeenLastCalledWith("legacy-failure", {
      subtitle_italic: true,
    }),
  );
});
