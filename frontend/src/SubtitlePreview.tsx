import type { CSSProperties } from "react";
import type { Cue, Region, SubtitleStyle } from "./types";
import "./subtitle-preview.css";

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
function wrapText(text: string, size: number, maxWidth: number): string[] {
  const maxUnits = Math.max(1, maxWidth / size);
  const lines: string[] = [];
  for (const paragraph of String(text).split("\n")) {
    let line = "";
    for (const word of paragraph.split(/\s+/).filter(Boolean)) {
      const proposed = (line + " " + word).trim();
      if (line && units(proposed) > maxUnits) {
        lines.push(line);
        line = word;
      } else line = proposed;
    }
    lines.push(line);
  }
  return lines;
}
// Mirror of backend subtitle_style.fit_lines: shrink up to 15% to fit max_lines.
export function fitLines(text: string, size: number, maxWidth: number, maxLines = 2) {
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
export function assignLanes(cues: { start: number; end: number }[]): number[] {
  const order = cues.map((_, i) => i).sort((a, b) => cues[a].start - cues[b].start || a - b);
  const ends: number[] = [];
  const lanes: number[] = new Array(cues.length).fill(0);
  for (const i of order) {
    let lane = ends.findIndex((end) => end <= cues[i].start);
    if (lane < 0) {
      lane = ends.length;
      ends.push(cues[i].end);
    } else ends[lane] = cues[i].end;
    lanes[i] = lane;
  }
  return lanes;
}
export const laneY = (y: number, lane: number, fs: number) => Math.max(fs * 1.5, y - lane * fs * 3);

type MaskRegion = Partial<Region> & {preview_mask_url?: string};
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
}: {
  cues: Cue[];
  now: number;
  regions: TimedRegion[];
  width: number;
  height: number;
  rect: ReturnType<typeof fitVideoRect>;
  blurOriginal: boolean;
  subtitleStyle?: SubtitleStyle | null;
}) {
  const lyrics = cues.filter((c) => c.text.trim());
  const laneOf = assignLanes(lyrics);
  const active = lyrics.map((c, i) => ({ c, lane: laneOf[i] })).filter(({ c }) => c.start <= now && now < c.end);
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
    outline: Math.round((3 * height) / 1080 * 10) / 10,
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
              ...(r.preview_mask_url ? {maskImage: `url("${r.preview_mask_url}")`, WebkitMaskImage: `url("${r.preview_mask_url}")`, maskMode: 'luminance' as const, maskSize: '100% 100%', WebkitMaskSize:'100% 100%'} : {}),
              left: `${(r.x / width) * 100}%`,
              top: `${(r.y / height) * 100}%`,
              width: `${(Math.min(r.width, width - r.x) / width) * 100}%`,
              height: `${(Math.min(r.height, height - r.y) / height) * 100}%`,
            }}
          />
        ))}
      {active.map(({ c, lane }) => {
        const box = c.box && c.box.length === 4 ? c.box : null;
        const x = box ? (box[0] + box[2]) / 2 : width / 2;
        const y = box ? (box[1] + box[3]) / 2 : height - st.margin_v;
        const fs = Math.max(8, Math.round(st.size * LIBASS_CELL));
        const yLane = laneY(y, lane, fs);
        const available = Math.max(20, 2 * Math.min(x, width - x) - 20);
        const fit = fitLines(c.text, st.size, available, st.max_lines);
        return (
          <div
            key={c.id}
            className={`vietnamese-preview${box ? "" : " at-bottom"}`}
            aria-label="Phụ đề Việt xem trước"
            style={{
              left: `${(x / width) * 100}%`,
              top: `${(yLane / height) * 100}%`,
              maxWidth: `${(available / width) * 100}%`,
              fontSize: ratio ? fit.size * ratio : 16,
              WebkitTextStrokeWidth: outline * 2,
            }}
          >
            <span>{fit.lines.join("\n")}</span>
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
