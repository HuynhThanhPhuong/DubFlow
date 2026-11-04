import type { CSSProperties } from "react";
import type { Cue, Region, SubtitleStyle } from "./types";
import "./subtitle-preview.css";
import advances from "../../backend/dubflow/assets/fonts/Roboto-Bold.metrics.json";

export function fitVideoRect(
  width: number,
  height: number,
  sourceWidth: number,
  sourceHeight: number,
) {
  if (!width || !height || !sourceWidth || !sourceHeight)
    return { left: 0, top: 0, width: 0, height: 0 };
  const scale = Math.min(width / sourceWidth, height / sourceHeight);
  return {
    left: (width - sourceWidth * scale) / 2,
    top: (height - sourceHeight * scale) / 2,
    width: sourceWidth * scale,
    height: sourceHeight * scale,
  };
}

// libass cell height of Roboto (winAscent+winDescent = 2701/2048 em); ASS \fs = size * LIBASS_CELL,
// so CSS font-size = size and line-height = LIBASS_CELL reproduce the export.
export const LIBASS_CELL = 2701 / 2048;
// Mean Roboto Bold advance widths in em (measured with PIL); mirrors backend subtitle_style._units.
const units = (s: string) =>
  [...s].reduce((n, c) => {
    if (/\s/.test(c)) return n + 0.26;
    if (/\p{Nd}/u.test(c)) return n + 0.58;
    if (!/[\p{L}\p{N}]/u.test(c)) return n + 0.33;
    return n + (c !== c.toLowerCase() ? 0.68 : 0.54);
  }, 0);
const regionUnits = (text: string) =>
  [...text.normalize("NFC")].reduce(
    (n, c) =>
      n +
      ((advances as Record<string, number>)[c] ?? (/\p{M}/u.test(c) ? 0 : 1)),
    0,
  );
function wrapText(
  text: string,
  size: number,
  maxWidth: number,
  measure = units,
): string[] {
  const maxUnits = Math.max(1, maxWidth / size);
  const lines: string[] = [];
  for (const paragraph of String(text).split("\n")) {
    let line = "";
    for (const word of paragraph.split(/\s+/).filter(Boolean)) {
      const proposed = (line + " " + word).trim();
      if (line && measure(proposed) > maxUnits) {
        lines.push(line);
        line = word;
      } else line = proposed;
    }
    lines.push(line);
  }
  return lines;
}
// Mirror of backend subtitle_style.fit_lines: shrink up to 15% to fit max_lines.
export function fitLines(
  text: string,
  size: number,
  maxWidth: number,
  maxLines = 2,
) {
  const first = wrapText(text, size, maxWidth);
  if (first.length <= maxLines) return { lines: first, size };
  for (let step = 1; step < 15; step++) {
    const trial = size * (1 - step / 100);
    const lines = wrapText(text, trial, maxWidth);
    if (lines.length <= maxLines) return { lines, size: trial };
  }
  return { lines: wrapText(text, size * 0.85, maxWidth), size: size * 0.85 };
}

// Exact mirror of backend subtitle_style.assign_lanes / lane_y (first free lane in start order).
export function assignLanes(
  cues: {
    start: number;
    end: number;
    region?: number | null;
    box?: number[] | null;
    kind?: Cue["kind"];
    orientation?: Cue["orientation"];
  }[],
): number[] {
  const order = cues
    .map((_, i) => i)
    .sort((a, b) => cues[a].start - cues[b].start || a - b);
  const groups = new Map<string, (typeof cues)[]>();
  const lanes: number[] = new Array(cues.length).fill(0);
  for (const i of order) {
    const c = cues[i];
    if (isSupplementary(c)) continue;
    const group = c.region != null && c.box ? `region-${c.region}` : "legacy";
    const slots = groups.get(group) ?? [];
    groups.set(group, slots);
    const independent = (other: (typeof cues)[number]) => {
      const a = c.box, b = other.box;
      return Boolean(a && b && (c.region !== other.region || a[2] <= b[0] || b[2] <= a[0] || a[3] <= b[1] || b[3] <= a[1]));
    };
    let lane = slots.findIndex((rows) => rows.every((other) => other.end <= c.start || independent(other)));
    if (lane < 0) {
      lane = slots.length;
      slots.push([]);
    }
    slots[lane] = [...slots[lane].filter((other) => other.end > c.start), c];
    lanes[i] = lane;
  }
  return lanes;
}
export const laneY = (y: number, lane: number, fs: number) =>
  Math.max(fs * 1.5, y - lane * fs * 3);

const assSize = (size: number) => Math.max(8, Math.round(size * LIBASS_CELL));
export const isSupplementary = (cue: Pick<Cue, "kind" | "orientation">) =>
  cue.kind === "supplementary" || cue.orientation === "v";
const defaultStyle = (width: number, height: number): SubtitleStyle => ({
  font: "Roboto",
  bold: true,
  size: Math.round(height * (height > width ? 0.045 : 0.055)),
  margin_v: Math.round(height * 0.04),
  max_lines: 2,
  outline: Math.round(((3 * height) / 1080) * 10) / 10,
});
/** Mirror of backend subtitle_style.region_layout. Cue box is xyxy. */
export function regionLayout(
  cue: Pick<
    Cue,
    "text" | "box" | "band" | "kind" | "orientation" | "text_height"
  > & { _layout_height?: number },
  width: number,
  height: number,
  custom?: SubtitleStyle | null,
) {
  const st = custom ?? defaultStyle(width, height);
  if (isSupplementary(cue)) {
    const text =
      "[" +
      cue.text
        .trim()
        .replace(/^[\[\]]+|[\[\]]+$/g, "")
        .trim() +
      "]";
    let size = st.size * 0.9;
    const available = Math.max(20, width - 20);
    let lines = wrapText(
      text,
      assSize(size) / LIBASS_CELL,
      available,
      regionUnits,
    );
    while (lines.length > 2 && size > st.size * 0.54 + 0.01) {
      size = Math.max(st.size * 0.54, size - st.size * 0.009);
      lines = wrapText(
        text,
        assSize(size) / LIBASS_CELL,
        available,
        regionUnits,
      );
    }
    if (lines.length > 2) lines = [lines[0], lines.slice(1).join(" ")];
    return {
      x: width / 2,
      y: height - st.margin_v,
      align: 2,
      size,
      lines,
      available,
      overflow: false,
    };
  }
  const box = cue.box;
  if (!box || box.length !== 4) {
    const available = Math.max(20, width - 20);
    const fit = fitLines(cue.text, st.size, available, st.max_lines);
    return {
      ...fit,
      x: width / 2,
      y: height - st.margin_v,
      align: 2,
      available,
      overflow: fit.lines.length > st.max_lines,
    };
  }
  let [x0, y0, x1, y1] = box;
  if (cue.band) {
    const center = (x0 + x1) / 2;
    const available = Math.max(
      1,
      2 *
        Math.min(
          center - Math.max(0, cue.band[0]),
          Math.min(width, cue.band[2]) - center,
        ),
    );
    x0 = center - available / 2;
    x1 = center + available / 2;
    const roomHeight =
      cue._layout_height || Math.max(1, cue.band[3] - cue.band[1]);
    const middle = (y0 + y1) / 2;
    y0 = middle - roomHeight / 2;
    y1 = middle + roomHeight / 2;
  }
  const bw = Math.max(1, x1 - x0),
    bh = Math.max(1, y1 - y0),
    normalMinimum = st.size * 0.6;
  const minimum = cue._layout_height
    ? Math.min(normalMinimum, Math.max(1, bh / 2 / LIBASS_CELL - 0.5))
    : normalMinimum;
  const stroke = 2 * st.outline;
  let maximum = st.size,
    size = maximum,
    lines: string[],
    overflow: boolean,
    available: number;
  {
    maximum = Math.max(
      normalMinimum,
      Math.min(maximum, cue.text_height || maximum),
    );
    const room = Math.max(1, bw - stroke);
    size = maximum;
    lines = wrapText(cue.text, assSize(size) / LIBASS_CELL, room, regionUnits);
    while (
      (lines.length > 2 ||
        lines.some(
          (line) =>
            (regionUnits(line) * assSize(size)) / LIBASS_CELL > room + 0.01,
        ) ||
        assSize(size) * lines.length > bh + 0.01) &&
      size > minimum + 0.01
    ) {
      size = Math.max(minimum, size - maximum * 0.01);
      lines = wrapText(
        cue.text,
        assSize(size) / LIBASS_CELL,
        room,
        regionUnits,
      );
    }
    overflow =
      lines.length > 2 ||
      lines.some(
        (line) =>
          (regionUnits(line) * assSize(size)) / LIBASS_CELL > room + 0.01,
      ) ||
      assSize(size) * lines.length > bh + 0.01 ||
      size < normalMinimum - 0.01;
    if (lines.length > 2) lines = [lines[0], lines.slice(1).join(" ")];
    available = bw;
  }
  return {
    x: (x0 + x1) / 2,
    y: (y0 + y1) / 2,
    align: 5,
    size,
    lines,
    overflow,
    available,
  };
}

/** Active neighbours constrain width and auxiliary placement exactly as in ASS. */
export function cueLayout(
  cues: Cue[],
  index: number,
  width: number,
  height: number,
  now: number,
  custom?: SubtitleStyle | null,
) {
  const st = custom ?? defaultStyle(width, height);
  const cue = cues[index];
  const active = cues
    .map((_, i) => i)
    .filter(
      (i) => cues[i].text.trim() && cues[i].start <= now && now < cues[i].end,
    );
  let fit = regionLayout(cue, width, height, st);
  const gap = Math.max(4, st.outline * 2);
  if (isSupplementary(cue)) {
    const dialogue: ReturnType<typeof regionLayout>[] = [];
    for (const i of active) {
      if (isSupplementary(cues[i])) continue;
      const other = cueLayout(cues, i, width, height, now, st);
      dialogue.push(other);
      const top =
        other.y -
        (assSize(other.size) * other.lines.length) /
          (other.align === 2 ? 1 : 2);
      fit.y = Math.min(fit.y, top - gap);
    }
    if (dialogue.length) {
      const sized = regionLayout(cue, width, height, {
        ...st,
        size: Math.max(...dialogue.map((d) => d.size)),
      });
      fit.size = sized.size;
      fit.lines = sized.lines;
    }
    for (const i of active) {
      if (i >= index || !isSupplementary(cues[i])) continue;
      const other = regionLayout(cues[i], width, height, st);
      fit.y -= assSize(other.size) * other.lines.length + gap;
    }
    return fit;
  }
  if (cue.band && cue.box) {
    const box = cue.box,
      band = [...cue.band],
      center = (box[0] + box[2]) / 2;
    const centerY = (box[1] + box[3]) / 2;
    let top = band[1],
      bottom = band[3],
      stacked = false;
    for (const i of active) {
      const other = cues[i],
        b = other.box;
      if (i === index || isSupplementary(other) || !b) continue;
      const otherY = (b[1] + b[3]) / 2;
      const overlap = Math.max(
        0,
        Math.min(box[2], b[2]) - Math.max(box[0], b[0]),
      );
      if (
        overlap > 0.25 * Math.min(box[2] - box[0], b[2] - b[0]) &&
        Math.abs(centerY - otherY) >
          0.6 * Math.min(box[3] - box[1], b[3] - b[1])
      ) {
        stacked = true;
        if (otherY > centerY) bottom = Math.min(bottom, (centerY + otherY) / 2);
        else top = Math.max(top, (centerY + otherY) / 2);
        continue;
      }
      if (Math.abs((box[1] + box[3] - b[1] - b[3]) / 2) >= 2 * assSize(st.size))
        continue;
      const otherCenter = (b[0] + b[2]) / 2;
      if (otherCenter > center)
        band[2] = Math.min(band[2], (box[2] + b[0]) / 2);
      else if (otherCenter < center)
        band[0] = Math.max(band[0], (b[2] + box[0]) / 2);
    }
    fit = regionLayout(
      {
        ...cue,
        band,
        ...(stacked ? { _layout_height: Math.max(1, bottom - top) } : {}),
      },
      width,
      height,
      st,
    );
    const half = (assSize(fit.size) * fit.lines.length) / 2;
    fit.y = Math.max(top + half, Math.min(fit.y, bottom - half));
  }
  const lane = assignLanes(cues)[index];
  if (lane) fit.y = laneY(fit.y, lane, assSize(fit.size));
  return fit;
}

export function revealWords(cue: Cue, now: number) {
  if (isSupplementary(cue) || !cue.reveal?.length) return null;
  let fraction = 0;
  for (const point of [...cue.reveal].sort((a, b) => a.t - b.t)) {
    if (point.t > now + 1e-9) break;
    fraction = Math.max(fraction, Math.min(1, Math.max(0, point.fraction)));
  }
  return Math.ceil(
    fraction * cue.text.split(/\s+/).filter(Boolean).length - 1e-9,
  );
}

type MaskRegion = Partial<Region> & { preview_mask_url?: string };
type TimedRegion = Region & { boxes?: MaskRegion[]; preview_mask_url?: string };
export function SubtitlePreview({
  cues,
  now,
  regions,
  width,
  height,
  rect,
  blurOriginal,
  subtitleStyle,
  cleanVideo = false,
}: {
  cues: Cue[];
  now: number;
  regions: TimedRegion[];
  width: number;
  height: number;
  rect: ReturnType<typeof fitVideoRect>;
  blurOriginal: boolean;
  subtitleStyle?: SubtitleStyle | null;
  cleanVideo?: boolean;
}) {
  const active = cues
    .map((c, index) => ({ c, index }))
    .filter(({ c }) => c.text.trim() && c.start <= now && now < c.end);
  const measured = regions
    .flatMap((parent) =>
      (parent.boxes ?? [parent]).map((box) => ({
        ...parent,
        ...box,
        start: Math.max(parent.start, box.start ?? parent.start),
        end: Math.min(parent.end, box.end ?? parent.end),
      })),
    )
    .filter(
      (r) =>
        r.enabled &&
        r.orientation !== "v" &&
        !r.erased &&
        !(cleanVideo && r.kind === "subtitle") &&
        [r.x, r.y, r.width, r.height].every(Number.isFinite) &&
        r.width > 0 &&
        r.height > 0,
    );
  const visible = measured.filter((r) => r.start <= now && now < r.end);
  const style: CSSProperties = rect.width
    ? { left: rect.left, top: rect.top, width: rect.width, height: rect.height }
    : { inset: 0 };
  const st = subtitleStyle ?? {
    font: "Roboto",
    bold: true,
    size: Math.round(height * (height > width ? 0.045 : 0.055)),
    outline: Math.round(((3 * height) / 1080) * 10) / 10,
    max_lines: 2,
    margin_v: Math.round(height * 0.04),
  };
  const ratio = rect.height && height ? rect.height / height : 0;
  // Same typography as the exported ASS: size and outline scale with displayed/video height.
  const outline = ratio ? st.outline * ratio : 0;
  return (
    <div
      className="subtitle-preview-stage"
      style={style}
      data-testid="subtitle-preview-stage"
    >
      {blurOriginal &&
        visible.map((r, i) => (
          <div
            key={r.id + "-" + i}
            className="preview-source-mask"
            aria-hidden="true"
            style={{
              ...(r.preview_mask_url
                ? {
                    maskImage: `url("${r.preview_mask_url}")`,
                    WebkitMaskImage: `url("${r.preview_mask_url}")`,
                    maskMode: "luminance" as const,
                    maskSize: "100% 100%",
                    WebkitMaskSize: "100% 100%",
                  }
                : {}),
              left: `${(r.x / width) * 100}%`,
              top: `${(r.y / height) * 100}%`,
              width: `${(Math.min(r.width, width - r.x) / width) * 100}%`,
              height: `${(Math.min(r.height, height - r.y) / height) * 100}%`,
            }}
          />
        ))}
      {active.map(({ c, index }) => {
        const fit = cueLayout(cues, index, width, height, now, st);
        const fs = assSize(fit.size);
        const x = Math.round(fit.x),
          y = Math.round(fit.y);
        let remaining = revealWords(c, now);
        return (
          <div
            key={c.id}
            className={`vietnamese-preview${fit.align === 2 ? " at-bottom" : ""}`}
            aria-label="Phụ đề Việt xem trước"
            style={{
              left: `${(x / width) * 100}%`,
              top: `${(y / height) * 100}%`,
              maxWidth: `${(fit.available / width) * 100}%`,
              fontSize: ratio ? (fs / LIBASS_CELL) * ratio : 16,
              lineHeight: LIBASS_CELL,
              WebkitTextStrokeWidth: outline * 2,
            }}
          >
            <span>
              {remaining === null
                ? fit.lines.join("\n")
                : fit.lines.map((line, i) => {
                    const words = line.split(/\s+/).filter(Boolean);
                    const shown = Math.max(
                      0,
                      Math.min(remaining!, words.length),
                    );
                    remaining! -= shown;
                    const visible = words.slice(0, shown).join(" ");
                    const hidden = words.slice(shown).join(" ");
                    return (
                      <span key={i}>
                        {i > 0 ? "\n" : ""}
                        {visible}
                        {hidden && (
                          <span
                            aria-hidden="true"
                            style={{ visibility: "hidden" }}
                          >
                            {(visible ? " " : "") + hidden}
                          </span>
                        )}
                      </span>
                    );
                  })}
            </span>
          </div>
        );
      })}
      {visible
        .filter((r) => r.kind === "transient" && r.translation?.trim())
        .map((r, i) => (
          <div
            key={r.id + "-" + i}
            className="preview-translated-note"
            style={{
              left: `${((r.x + r.width / 2) / width) * 100}%`,
              top: `${((r.y + r.height / 2) / height) * 100}%`,
              fontSize: ratio ? r.height * 0.78 * ratio : 16,
              WebkitTextStrokeWidth: outline * 2,
            }}
          >
            {r.translation}
          </div>
        ))}
    </div>
  );
}
