import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FontPopover } from "./FontPopover";
import { api } from "./api";
import { workspaceApi } from "./workspaceApi";
import type { Job, SubtitleFont } from "./types";

vi.mock("./api", () => ({ api: { fonts: vi.fn(), updateJob: vi.fn() } }));
vi.mock("./workspaceApi", () => ({
  workspaceApi: { updateSettings: vi.fn() },
}));
vi.mock("./fonts", () => ({
  loadFont: vi.fn(async (font: SubtitleFont) => font),
  fontFamily: (font: SubtitleFont) => font.family,
}));
const fonts = [
  {
    id: "public-sans",
    name: "Public Sans",
    family: "Public Sans",
    group: "Không chân",
  },
  { id: "lora", name: "Lora", family: "Lora", group: "Có chân" },
  {
    id: "dancing-script",
    name: "Dancing Script",
    family: "Dancing Script",
    group: "Viết tay",
  },
].map((f) => ({
  ...f,
  file: f.id + ".ttf",
  url: "/api/fonts/" + f.id + ".ttf",
  cell: 1.4,
  advances: {},
}));
const job = { id: "one", subtitle_font: "public-sans" } as Job;
beforeEach(() => {
  vi.mocked(api.fonts).mockResolvedValue({ default: "public-sans", fonts });
  vi.mocked(api.updateJob).mockResolvedValue({ ...job, subtitle_font: "lora" });
  vi.mocked(workspaceApi.updateSettings).mockResolvedValue({
    default_subtitle_font: "lora",
  } as never);
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
function setup() {
  const onPreview = vi.fn(),
    onJob = vi.fn(),
    onDefault = vi.fn();
  const view = render(
    <FontPopover
      job={job}
      defaultFont="public-sans"
      disabled={false}
      onPreview={onPreview}
      onJob={onJob}
      onDefault={onDefault}
      onError={vi.fn()}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Phông chữ ▾" }));
  return { ...view, onPreview, onJob, onDefault };
}
it("filters by group and search, shows selected and default font", async () => {
  setup();
  const selected = await screen.findByRole("button", { name: /Public Sans/ });
  expect(selected.getAttribute("aria-pressed")).toBe("true");
  expect(screen.getByText("Mặc định")).toBeTruthy();
  fireEvent.click(screen.getByRole("tab", { name: "Có chân" }));
  expect(screen.queryByRole("button", { name: /Public Sans/ })).toBeNull();
  expect(screen.getByRole("button", { name: "Lora" })).toBeTruthy();
  fireEvent.click(screen.getByRole("tab", { name: "Tất cả" }));
  fireEvent.change(screen.getByRole("searchbox"), {
    target: { value: "DANCING" },
  });
  expect(screen.getByRole("button", { name: "Dancing Script" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Lora" })).toBeNull();
});
it("auditions on hover and focus and clears on leave, Escape and unmount", async () => {
  const { onPreview, unmount } = setup();
  const lora = await screen.findByRole("button", { name: "Lora" });
  fireEvent.mouseEnter(lora);
  expect(onPreview).toHaveBeenLastCalledWith("lora");
  fireEvent.mouseLeave(screen.getByRole("region", { name: "Chọn phông chữ" }));
  expect(onPreview).toHaveBeenLastCalledWith(null);
  fireEvent.focus(lora);
  expect(onPreview).toHaveBeenLastCalledWith("lora");
  fireEvent.keyDown(lora, { key: "Escape" });
  expect(onPreview).toHaveBeenLastCalledWith(null);
  expect(screen.queryByRole("searchbox")).toBeNull();
  unmount();
  expect(onPreview).toHaveBeenLastCalledWith(null);
  expect(api.updateJob).not.toHaveBeenCalled();
});
it("saves selected font and sets default without requiring a job edit", async () => {
  const { onJob, onDefault } = setup();
  fireEvent.click(await screen.findByRole("button", { name: "Lora" }));
  await waitFor(() =>
    expect(onJob).toHaveBeenCalledWith(
      expect.objectContaining({ subtitle_font: "lora" }),
    ),
  );
  expect(api.updateJob).toHaveBeenCalledWith("one", { subtitle_font: "lora" });
  fireEvent.click(
    screen.getByRole("button", { name: "Đặt làm mặc định cho video mới" }),
  );
  await waitFor(() => expect(onDefault).toHaveBeenCalledWith("lora"));
  expect(workspaceApi.updateSettings).toHaveBeenCalledWith({
    default_subtitle_font: "lora",
  });
});
it("moves grid focus with arrows and supports Enter", async () => {
  setup();
  const first = await screen.findByRole("button", { name: /Public Sans/ });
  first.focus();
  fireEvent.keyDown(first, { key: "ArrowRight" });
  expect(document.activeElement).toBe(
    screen.getByRole("button", { name: "Lora" }),
  );
  fireEvent.keyDown(document.activeElement!, { key: "Enter" });
  await waitFor(() =>
    expect(api.updateJob).toHaveBeenCalledWith("one", {
      subtitle_font: "lora",
    }),
  );
});
