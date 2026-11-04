import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { SubtitlePreview, fitVideoRect, regionLayout } from "./SubtitlePreview";
import type { FontCatalog } from "./types";
import { api } from "./api";
vi.mock("./api", () => ({ api: { fonts: vi.fn() } }));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
it("waits for the selected FontFace, ignores stale loads, and uses its cell and metrics", async () => {
  const resolves: Record<string, () => void> = {};
  vi.stubGlobal(
    "FontFace",
    class {
      family: string;
      constructor(family: string) {
        this.family = family;
      }
      load() {
        return new Promise((resolve) => {
          resolves[this.family] = () => resolve(this);
        });
      }
    },
  );
  Object.defineProperty(document, "fonts", {
    value: { add: vi.fn() },
    configurable: true,
  });
  const fonts = ["slow", "new"].map((id) => ({
    id,
    name: id,
    family: id,
    file: id + ".ttf",
    url: "/api/fonts/" + id,
    group: "Có chân",
    cell: 1.5,
    advances: { A: 1, " ": 0.2 },
  }));
  vi.mocked(api.fonts).mockResolvedValue({
    default: "new",
    fonts,
  } as FontCatalog);
  const props = {
    cues: [
      { id: "a", start: 0, end: 3, speaker: "s", original: "", text: "A A A" },
    ],
    now: 1,
    width: 640,
    height: 360,
    rect: fitVideoRect(640, 360, 640, 360),
    regions: [],
    blurOriginal: false,
  };
  const style = {
    font: "slow",
    font_id: "slow",
    cell: 1.5,
    size: 20,
    bold: true,
    outline: 1,
    max_lines: 2,
    margin_v: 14,
  };
  const view = render(<SubtitlePreview {...props} subtitleStyle={style} />);
  await waitFor(() => expect(resolves["DubFlow slow"]).toBeTruthy());
  expect(screen.queryByLabelText("Phụ đề Việt xem trước")).toBeNull();
  view.rerender(
    <SubtitlePreview {...props} subtitleStyle={{ ...style, font_id: "new" }} />,
  );
  await waitFor(() => expect(resolves["DubFlow new"]).toBeTruthy());
  resolves["DubFlow slow"]();
  expect(screen.queryByLabelText("Phụ đề Việt xem trước")).toBeNull();
  resolves["DubFlow new"]();
  const node = await screen.findByLabelText("Phụ đề Việt xem trước");
  expect(node.style.fontFamily).toBe('"DubFlow new"');
  expect(node.style.lineHeight).toBe("1.5");
  expect(parseFloat(node.style.fontSize)).toBe(20);
  expect(
    regionLayout({ text: "A A A", box: [0, 0, 55, 80] }, 640, 360, {
      ...style,
      advances: fonts[0].advances,
    }).lines,
  ).toEqual(["A A", "A"]);
});
