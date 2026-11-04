import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { SubtitlePreview, fitVideoRect } from "./SubtitlePreview";

afterEach(cleanup);
const left = {
  id: "left",
  start: 0,
  end: 6,
  speaker: "s",
  original: "原文",
  text: "Chúng ta cùng nhau trở về nhà an toàn nhé",
  box: [340, 620, 560, 660],
  band: [40, 590, 1240, 710],
  region: 0,
  text_height: 40,
};
const right = {
  ...left,
  id: "right",
  start: 2,
  end: 4,
  text: "Bình an nhé",
  box: [700, 630, 940, 670],
};
const props = {
  now: 1,
  regions: [],
  width: 1280,
  height: 720,
  rect: fitVideoRect(1280, 720, 1280, 720),
  blurOriginal: false,
};
const nodes = () => screen.getAllByLabelText("Phụ đề Việt xem trước");

it("keeps legacy lanes for concurrent cues occupying the same region box", () => {
  const a = { ...left, text: "Xin chào", band: undefined };
  const b = { ...a, id: "same-box" };
  render(<SubtitlePreview {...props} cues={[a, b]} />);
  expect(parseFloat(nodes()[0].style.top)).toBeCloseTo((640 / 720) * 100);
  expect(parseFloat(nodes()[1].style.top)).toBeCloseTo((520 / 720) * 100);
});

// Literal positions, wrapping and quantized sizes checked against make_ass / cue_layout.
it("keeps full ASS wrapping and invisible word tails through absolute reveal boundaries", () => {
  const cue = {
    ...left,
    reveal: [
      { t: 1, fraction: 0.11 },
      { t: 1.5, fraction: 0.4 },
      { t: 3, fraction: 1 },
    ],
  };
  const { rerender } = render(
    <SubtitlePreview {...props} cues={[cue, right]} now={0.999} />,
  );
  const full = nodes()[0].textContent;
  expect(nodes()[0].querySelector('[aria-hidden="true"]')?.textContent).toBe(
    left.text,
  );
  rerender(<SubtitlePreview {...props} cues={[cue, right]} now={1} />);
  expect(nodes()[0].textContent).toBe(full);
  expect(nodes()[0].querySelector('[aria-hidden="true"]')?.textContent).toBe(
    " cùng nhau trở về nhà an toàn nhé",
  );
  expect(
    (nodes()[0].querySelector('[aria-hidden="true"]') as HTMLElement).style
      .visibility,
  ).toBe("hidden");
  expect(parseFloat(nodes()[0].style.fontSize)).toBeCloseTo(53 / (2701 / 2048));
  rerender(<SubtitlePreview {...props} cues={[cue, right]} now={2} />);
  expect(nodes()[0].textContent).toBe(
    "Chúng ta cùng nhau\ntrở về nhà an toàn nhé",
  );
  expect(nodes()[0].querySelector('[aria-hidden="true"]')?.textContent).toBe(
    "trở về nhà an toàn nhé",
  );
  expect(parseFloat(nodes()[0].style.fontSize)).toBeCloseTo(47 / (2701 / 2048));
  rerender(<SubtitlePreview {...props} cues={[cue, right]} now={3} />);
  expect(nodes()[0].querySelector('[aria-hidden="true"]')).toBeNull();
  expect(nodes()[0].textContent).toBe(
    "Chúng ta cùng nhau\ntrở về nhà an toàn nhé",
  );
});

it("recomputes shared-band left/right space on inclusive starts and exclusive ends", () => {
  const { rerender } = render(
    <SubtitlePreview {...props} cues={[left, right]} now={1.999} />,
  );
  expect(nodes()).toHaveLength(1);
  expect(nodes()[0].textContent).toBe(left.text);
  expect(parseFloat(nodes()[0].style.maxWidth)).toBeCloseTo((820 / 1280) * 100);
  rerender(<SubtitlePreview {...props} cues={[left, right]} now={2} />);
  expect(nodes()).toHaveLength(2);
  expect(nodes()[0].textContent).toBe(
    "Chúng ta cùng nhau\ntrở về nhà an toàn nhé",
  );
  expect(parseFloat(nodes()[0].style.maxWidth)).toBeCloseTo((360 / 1280) * 100);
  expect(parseFloat(nodes()[1].style.maxWidth)).toBeCloseTo((380 / 1280) * 100);
  expect(parseFloat(nodes()[0].style.left)).toBeCloseTo((450 / 1280) * 100);
  expect(parseFloat(nodes()[1].style.left)).toBeCloseTo((820 / 1280) * 100);
  expect(parseFloat(nodes()[1].style.top)).toBeCloseTo((650 / 720) * 100);
  rerender(<SubtitlePreview {...props} cues={[left, right]} now={4} />);
  expect(nodes()).toHaveLength(1);
  expect(nodes()[0].textContent).toBe(left.text);
  expect(parseFloat(nodes()[0].style.maxWidth)).toBeCloseTo((820 / 1280) * 100);
});

it.each([{ orientation: "v" as const }, { kind: "supplementary" as const }])(
  "places auxiliary brackets above the highest active dialogue using ASS rounding: %j",
  (kind) => {
    const aux = {
      ...left,
      ...kind,
      id: "aux",
      text: "Gió cuốn bay",
      box: [1100, 100, 1190, 400],
      reveal: [{ t: 5, fraction: 0.1 }],
    };
    const { rerender } = render(
      <SubtitlePreview {...props} cues={[left, right, aux]} now={1} />,
    );
    expect(nodes()[1].textContent).toBe("[Gió cuốn bay]");
    expect(nodes()[1].className).toContain("at-bottom");
    expect(parseFloat(nodes()[1].style.top)).toBeCloseTo((610 / 720) * 100);
    expect(parseFloat(nodes()[1].style.fontSize)).toBeCloseTo(
      47 / (2701 / 2048),
    );
    rerender(<SubtitlePreview {...props} cues={[left, right, aux]} now={2} />);
    // dot13: the dialogue block is bottom-anchored inside the safe area, so the brackets above it moved up 3 px
    expect(parseFloat(nodes()[2].style.top)).toBeCloseTo((586 / 720) * 100);
    rerender(<SubtitlePreview {...props} cues={[left, right, aux]} now={4} />);
    expect(parseFloat(nodes()[1].style.top)).toBeCloseTo((610 / 720) * 100);
    rerender(
      <SubtitlePreview {...props} cues={[{ ...aux, end: 8 }, left]} now={6} />,
    );
    expect(nodes()[0].textContent).toBe("[Gió cuốn bay]");
    expect(parseFloat(nodes()[0].style.top)).toBeCloseTo((691 / 720) * 100);
  },
);

it("preserves the vertical source with no preview erasure mask, including timed boxes", () => {
  const base = {
    id: "v",
    start: 0,
    end: 6,
    enabled: true,
    x: 1100,
    y: 100,
    width: 90,
    height: 300,
    kind: "subtitle" as const,
    text: "原文",
    translation: "",
    orientation: "v" as const,
    boxes: [{ start: 1, end: 3 }],
  };
  const { container } = render(
    <SubtitlePreview
      {...props}
      cues={[]}
      regions={[base]}
      now={2}
      blurOriginal
    />,
  );
  expect(container.querySelectorAll(".preview-source-mask")).toHaveLength(0);
});

it("sizes auxiliary text at ninety percent of the region's uniform dialogue size", () => {
  const spoken = {
    ...left,
    text: "Xin chào",
    text_height: 28,
    box: [400, 640, 800, 670],
    band: [0, 600, 1280, 720],
  };
  const aux = {
    ...left,
    id: "aux",
    text: "Gió cuốn bay",
    orientation: "v" as const,
  };
  const { rerender } = render(
    <SubtitlePreview {...props} cues={[spoken, aux]} />,
  );
  expect(parseFloat(nodes()[1].style.fontSize)).toBeCloseTo(33 / (2701 / 2048));
  rerender(<SubtitlePreview {...props} cues={[{ ...spoken, end: 1 }, aux]} />);
  // dot13: one auxiliary size for the whole video (90% of the region's size), also while no dialogue is on screen
  expect(parseFloat(nodes()[0].style.fontSize)).toBeCloseTo(33 / (2701 / 2048));
});

it("allocates vertical slots to same-column neighbours exactly when they start and end", () => {
  const upper = {
    ...left,
    text: Array(35).fill("Bình").join(" "),
    box: [340, 610, 560, 630],
  };
  const lower = {
    ...upper,
    id: "lower",
    start: 2,
    end: 4,
    box: [340, 640, 560, 660],
  };
  const { rerender } = render(
    <SubtitlePreview {...props} cues={[upper, lower]} now={1.999} />,
  );
  expect(parseFloat(nodes()[0].style.top)).toBeCloseTo((622 / 720) * 100);
  expect(parseFloat(nodes()[0].style.fontSize)).toBeCloseTo(32 / (2701 / 2048));
  rerender(<SubtitlePreview {...props} cues={[upper, lower]} now={2} />);
  expect(parseFloat(nodes()[0].style.top)).toBeCloseTo((613 / 720) * 100);
  expect(parseFloat(nodes()[1].style.top)).toBeCloseTo((667 / 720) * 100);
  expect(parseFloat(nodes()[0].style.fontSize)).toBeCloseTo(22 / (2701 / 2048));
  expect(parseFloat(nodes()[1].style.fontSize)).toBeCloseTo(32 / (2701 / 2048));
  const upperBottom =
    (parseFloat(nodes()[0].style.top) * 720) / 100 +
    parseFloat(nodes()[0].style.fontSize) * (2701 / 2048);
  const lowerTop =
    (parseFloat(nodes()[1].style.top) * 720) / 100 -
    parseFloat(nodes()[1].style.fontSize) * (2701 / 2048);
  expect(upperBottom).toBeCloseTo(lowerTop);
  rerender(<SubtitlePreview {...props} cues={[upper, lower]} now={4} />);
  expect(nodes()).toHaveLength(1);
  expect(parseFloat(nodes()[0].style.top)).toBeCloseTo((622 / 720) * 100);
  expect(parseFloat(nodes()[0].style.fontSize)).toBeCloseTo(32 / (2701 / 2048));
});
