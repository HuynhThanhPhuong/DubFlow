import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import {
  SubtitlePreview,
  assignLanes,
  fitVideoRect,
  regionLayout,
} from "./SubtitlePreview";
import type { Cue } from "./types";
afterEach(cleanup);
const a: Cue = {
  id: "a",
  start: 1,
  end: 5,
  speaker: "s",
  original: "你好",
  text: "Bình an nhé",
  region: 0,
  orientation: "v",
  box: [1100, 100, 1190, 400],
};
it("fits two horizontal lines in height and accounts for ASS font quantization", () => {
  const horizontal = regionLayout(
    {
      text: "Chúng ta cùng nhau trở về nhà",
      box: [100, 500, 400, 570],
      text_height: 40,
    },
    1280,
    720,
  );
  expect(horizontal.overflow).toBe(false);
  expect(
    Math.round(horizontal.size * (2701 / 2048)) * horizontal.lines.length,
  ).toBeLessThanOrEqual(70);
  const vertical = regionLayout({ ...a, box: [0, 0, 58, 500] }, 1280, 720);
  expect(vertical.overflow).toBe(false);
  expect(Math.round(vertical.size * (2701 / 2048))).toBe(47);
});
it("treats old vertical cues as horizontal bracketed auxiliary captions without overflow", () => {
  const fit = regionLayout(a, 1280, 720);
  expect(fit.lines).toEqual(["[Bình an nhé]"]);
  expect([fit.x, fit.y]).toEqual([640, 691]);
  expect(fit.overflow).toBe(false);
  expect(
    regionLayout({ ...a, box: [1100, 100, 1120, 140] }, 1280, 720).overflow,
  ).toBe(false);
  expect(
    regionLayout(
      { ...a, orientation: "h", text: "wwwwww", box: [100, 500, 200, 600] },
      1280,
      720,
    ).overflow,
  ).toBe(true);
});
it("gives dialogue its source position and puts auxiliary text above it", () => {
  const b = {
    ...a,
    id: "b",
    region: 1,
    box: [100, 500, 500, 570],
    orientation: "h" as const,
    text: "Chúng ta cùng nhau trở về nhà",
    text_height: 28,
  };
  expect(assignLanes([a, b])).toEqual([0, 0]);
  render(
    <SubtitlePreview
      cues={[a, b]}
      now={2}
      regions={[]}
      width={1280}
      height={720}
      rect={fitVideoRect(1280, 720, 1280, 720)}
      blurOriginal={false}
    />,
  );
  const nodes = screen.getAllByLabelText("Phụ đề Việt xem trước");
  expect(nodes[0].textContent).toBe("[Bình an nhé]");
  expect(parseFloat(nodes[0].style.top)).toBeCloseTo((513 / 720) * 100);
  expect(nodes[1].style.left).toBe(`${(300 / 1280) * 100}%`);
  expect(regionLayout(b, 1280, 720).size).toBeLessThanOrEqual(28);
});
