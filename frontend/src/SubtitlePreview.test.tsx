import { render, screen, cleanup } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { SubtitlePreview, fitVideoRect } from "./SubtitlePreview";
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
