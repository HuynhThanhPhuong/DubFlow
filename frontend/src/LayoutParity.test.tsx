import { expect, it } from "vitest";
import {
  cueLayout,
  regionSizes,
  anchorBlock,
  LIBASS_CELL,
} from "./SubtitlePreview";
import fixture from "../../backend/tests/fixtures/layout-dot13.json";
import type { Cue, SubtitleStyle } from "./types";

// The fixture is produced by the backend (backend/tests/gen_layout_fixture.py) from subtitle_style.cue_layout, which also
// drives the ASS export; the preview must give the same lines, sizes and positions.
const st = {
  ...fixture.style,
  advances: fixture.advances,
} as unknown as SubtitleStyle;

it.each(Object.entries(fixture.scenarios))(
  "preview layout equals the backend (ASS) layout: %s",
  (_name, scenario) => {
    const cues = scenario.cues as unknown as Cue[];
    for (const row of scenario.rows) {
      const fit = cueLayout(
        cues,
        row.index,
        fixture.width,
        fixture.height,
        row.t,
        st,
      );
      expect(fit.lines).toEqual(row.lines);
      expect(fit.align).toBe(row.align);
      expect(fit.size).toBeCloseTo(row.size, 4);
      expect(fit.x).toBeCloseTo(row.x, 4);
      expect(fit.y).toBeCloseTo(row.y, 4);
      expect(Boolean(fit.overflow)).toBe(row.overflow);
    }
  },
);

it("keeps one size per region and a two-line block inside the 2% bottom safe area", () => {
  const cues = fixture.scenarios.bottom_two_lines.cues as unknown as Cue[];
  expect(regionSizes(cues, st).get(0)).toBe(33);
  const fit = cueLayout(cues, 1, fixture.width, fixture.height, 5, st);
  const fs = Math.round(fit.size * (st.cell ?? LIBASS_CELL));
  expect(fit.lines).toHaveLength(2);
  expect(fit.y + (fs * fit.lines.length) / 2).toBeLessThanOrEqual(
    fixture.height * 0.98,
  );
  expect(anchorBlock(700, 1, 40, 0, 720, 720)).toBeLessThanOrEqual(
    720 * 0.98 - 20,
  );
});
