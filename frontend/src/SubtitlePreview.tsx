import type { CSSProperties } from "react";
import type { Cue, Region } from "./types";
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
}: {
  cues: Cue[];
  now: number;
  regions: TimedRegion[];
  width: number;
  height: number;
  rect: ReturnType<typeof fitVideoRect>;
  blurOriginal: boolean;
}) {
  const active = cues.filter(
    (c) => c.text.trim() && c.start <= now && now < c.end,
  );
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
  const allSubs = measured.filter((r) => r.kind === 'subtitle');
  // Match the renderer: keep one position/font throughout a cue, including OCR gaps.
  const matched = allSubs.filter((r) => active.some((c) => r.start < c.end && r.end > c.start));
  const subs = matched.length ? matched : allSubs;
  const left = subs.length
    ? ((Math.min(...subs.map((r) => r.x)) +
        Math.max(...subs.map((r) => r.x + r.width))) /
        2 /
        width) *
      100
    : 50;
  const top = subs.length
    ? ((Math.min(...subs.map((r) => r.y)) +
        Math.max(...subs.map((r) => r.y + r.height))) /
        2 /
        height) *
      100
    : 92;
  const style: CSSProperties = rect.width
    ? { left: rect.left, top: rect.top, width: rect.width, height: rect.height }
    : { inset: 0 };
  const sizes = allSubs.map((r) => r.height).sort((a,b) => a-b);
  const middle = Math.floor(sizes.length / 2);
  const median = sizes.length ? (sizes.length % 2 ? sizes[middle] : (sizes[middle-1]+sizes[middle])/2) : 0;
  const sourceFont = Math.max(12, Math.round(median ? median * .88 : height * .035));
  const font = rect.height && height ? sourceFont * rect.height / height : 16;
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
      {!!active.length && (
        <div
          className="vietnamese-preview"
          aria-label="Phụ đề Việt xem trước"
          style={{ left: `${left}%`, top: `${top}%`, fontSize: font }}
        >
          {active.map((c) => (
            <span key={c.id}>{c.text}</span>
          ))}
        </div>
      )}
      {visible
        .filter((r) => r.kind === "transient" && r.translation?.trim())
        .map((r, i) => (
          <div
            key={r.id + "-" + i}
            className="preview-translated-note"
            style={{
              left: `${((r.x + r.width / 2) / width) * 100}%`,
              top: `${((r.y + r.height / 2) / height) * 100}%`,
              fontSize: Math.min(font, 24),
            }}
          >
            {r.translation}
          </div>
        ))}
    </div>
  );
}
