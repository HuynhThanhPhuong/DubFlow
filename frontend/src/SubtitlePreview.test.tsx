import { render, screen, cleanup } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { SubtitlePreview, fitVideoRect, fitLines, assignLanes } from "./SubtitlePreview";
afterEach(cleanup);
it("fits source coordinates inside letterboxed video without using black bars", () => {
  const box = fitVideoRect(1000, 400, 1920, 1080);
  expect(box.height).toBe(400);
  expect(box.width).toBeCloseTo(711.111, 2);
  expect(box.left).toBeCloseTo(144.444, 2);
  expect(box.top).toBe(0);
});
it("uses OCR time windows for masks/notes and handles overlapping translated dialogue", () => {
  const cues = [
    {
      id: "a",
      start: 1,
      end: 3,
      speaker: "m",
      original: "原文",
      text: "Câu nam",
    },
    {
      id: "b",
      start: 2,
      end: 4,
      speaker: "f",
      original: "原文",
      text: "Câu nữ",
    },
  ];
  const regions = [
    {
      id: "r",
      start: 1,
      end: 3,
      enabled: true,
      x: 100,
      y: 800,
      width: 300,
      height: 40,
      kind: "subtitle" as const,
      text: "原文",
      translation: "",
      preview_mask_url: "/api/jobs/test/text-mask/r?box=0",
    },
  ];
  const { container, rerender } = render(
    <SubtitlePreview
      cues={cues}
      now={2}
      regions={regions}
      width={1920}
      height={1080}
      rect={fitVideoRect(960, 540, 1920, 1080)}
      blurOriginal
    />,
  );
  expect(screen.getByText("Câu nam")).toBeTruthy();
  expect(screen.getByText("Câu nữ")).toBeTruthy();
  expect(container.querySelectorAll(".preview-source-mask")).toHaveLength(1);
  expect((container.querySelector(".preview-source-mask") as HTMLElement).style.maskImage).toContain('/text-mask/r');
  expect((container.querySelector(".preview-source-mask") as HTMLElement).style.maskMode).toBe('luminance');
  rerender(
    <SubtitlePreview
      cues={cues}
      now={3}
      regions={regions}
      width={1920}
      height={1080}
      rect={fitVideoRect(960, 540, 1920, 1080)}
      blurOriginal
    />,
  );
  expect(screen.queryByText("Câu nam")).toBeNull();
  expect(screen.getByText("Câu nữ")).toBeTruthy();
  expect(container.querySelectorAll(".preview-source-mask")).toHaveLength(0);
});
it("hides subtitle-kind masks but keeps other masks when playing the clean video", () => {
  const base = { start: 0, end: 5, enabled: true, x: 100, y: 800, width: 300, height: 40, text: "", translation: "" };
  const regions = [
    { ...base, id: "s", kind: "subtitle" as const },
    { ...base, id: "w", kind: "static" as const },
  ];
  const props = { cues: [], now: 1, regions, width: 1920, height: 1080, rect: fitVideoRect(960, 540, 1920, 1080), blurOriginal: true };
  const { container, rerender } = render(<SubtitlePreview {...props} />);
  expect(container.querySelectorAll(".preview-source-mask")).toHaveLength(2);
  rerender(<SubtitlePreview {...props} cleanVideo />);
  expect(container.querySelectorAll(".preview-source-mask")).toHaveLength(1);
});
it("uses the shared Roboto style scaled to the displayed height and the cue box centre", () => {
  const cues = [
    { id: "a", start: 0, end: 2, speaker: "m", original: "x", text: "Xin chào", box: [400, 900, 1000, 1000] },
    { id: "b", start: 0, end: 2, speaker: "m", original: "x", text: "Không có khung" },
  ];
  const style = { font: "Roboto", bold: true, size: 59, outline: 3, max_lines: 2, margin_v: 43 };
  const { container } = render(
    <SubtitlePreview
      cues={cues}
      now={1}
      regions={[]}
      width={1920}
      height={1080}
      rect={fitVideoRect(960, 540, 1920, 1080)}
      blurOriginal={false}
      subtitleStyle={style}
    />,
  );
  const [boxed, bottom] = Array.from(container.querySelectorAll<HTMLElement>(".vietnamese-preview"));
  expect(parseFloat(boxed.style.fontSize)).toBeCloseTo(29.5, 1);
  expect(boxed.style.getPropertyValue("-webkit-text-stroke-width") || (boxed.style as unknown as Record<string, string>).webkitTextStrokeWidth).toBeTruthy();
  expect(parseFloat(boxed.style.left)).toBeCloseTo((700 / 1920) * 100, 3);
  expect(parseFloat(boxed.style.top)).toBeCloseTo((950 / 1080) * 100, 3);
  expect(bottom.className).toContain("at-bottom");
  expect(parseFloat(bottom.style.left)).toBeCloseTo(50, 3);
});
it("fitLines mirrors the backend wrap and shrinks at most 15%", () => {
  expect(fitLines("Xin chào các bạn", 59, 1700).lines).toHaveLength(1);
  const long = Array(16).fill("abcdefg").join(" ");
  const fit = fitLines(long, 59, 1700, 2);
  expect(fit.lines.length).toBeLessThanOrEqual(2);
  expect(fit.size).toBeLessThan(59);
  expect(fit.size).toBeGreaterThanOrEqual(59 * 0.85);
  const sentence = "Hôm nay chúng ta sẽ cùng nhau tìm hiểu một câu chuyện rất dài và thú vị đó nhé các bạn";
  expect(fitLines(sentence, 59, 1900).lines).toHaveLength(2);
  expect(fitLines(sentence, 59, 1900).size).toBe(59);
  expect(fitLines(sentence, 86, 1060).size).toBeCloseTo(86 * 0.85, 5); // portrait overflow: shrunk, still > 2 lines
});
it("offsets overlapping cues by the same lane rule as the ASS export", () => {
  const box = [860, 990, 1060, 1010];
  const cues = [
    { id: "a", start: 0, end: 2, speaker: "m", original: "x", text: "Một", box },
    { id: "b", start: 1, end: 3, speaker: "m", original: "x", text: "Hai", box },
    { id: "c", start: 2.5, end: 4, speaker: "m", original: "x", text: "Ba", box },
  ];
  expect(assignLanes(cues)).toEqual([0, 1, 0]);
  const style = { font: "Roboto", bold: true, size: 59, outline: 3, max_lines: 2, margin_v: 43 };
  const { container } = render(
    <SubtitlePreview cues={cues} now={1.5} regions={[]} width={1920} height={1080} rect={fitVideoRect(960, 540, 1920, 1080)} blurOriginal={false} subtitleStyle={style} />,
  );
  const tops = Array.from(container.querySelectorAll<HTMLElement>(".vietnamese-preview")).map((e) => parseFloat(e.style.top));
  // fs = round(59 * 2701/2048) = 78 -> lane 1 is 3*78 px above
  expect(tops[0]).toBeCloseTo((1000 / 1080) * 100, 3);
  expect(tops[1]).toBeCloseTo(((1000 - 3 * 78) / 1080) * 100, 3);
});
