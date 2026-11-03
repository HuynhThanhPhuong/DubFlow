import type { AnalysisRegions, SubtitleRegion } from "./types";

export function subtitleRegions(
  regions?: AnalysisRegions | null,
): SubtitleRegion[] {
  const rows =
    regions?.subtitles ?? (regions?.subtitle ? [regions.subtitle] : []);
  return rows.map((row) =>
    Array.isArray(row)
      ? { box: row, orientation: row[3] > 1.5 * row[2] ? "v" : "h" }
      : row,
  );
}

export function sameRegions(
  a?: AnalysisRegions | null,
  b?: AnalysisRegions | null,
) {
  const key = (r?: AnalysisRegions | null) =>
    r
      ? {
          no_hard_subs: r.no_hard_subs,
          subtitles: r.no_hard_subs ? [] : subtitleRegions(r),
          logos: r.logos,
          screen_text: r.screen_text,
        }
      : null;
  return JSON.stringify(key(a)) === JSON.stringify(key(b));
}
