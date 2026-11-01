export interface VideoRect {
  left: number;
  top: number;
  width: number;
  height: number;
}
export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}
export const MIN_BOX = 8;

const clamp = (v: number, lo: number, hi: number) =>
  Math.min(hi, Math.max(lo, v));

/** Display point (relative to the frame that contains `rect`) -> source pixels, clamped to the frame. */
export function toSource(
  pt: { x: number; y: number },
  rect: VideoRect,
  vw: number,
  vh: number,
): { x: number; y: number } {
  if (!rect.width || !rect.height || !vw || !vh) return { x: 0, y: 0 };
  return {
    x: clamp(((pt.x - rect.left) * vw) / rect.width, 0, vw),
    y: clamp(((pt.y - rect.top) * vh) / rect.height, 0, vh),
  };
}

/** Source-pixel box -> display rectangle relative to the same frame as `rect`. */
export function toDisplay(box: Box, rect: VideoRect, vw: number, vh: number) {
  if (!vw || !vh) return { left: 0, top: 0, width: 0, height: 0 };
  const sx = rect.width / vw;
  const sy = rect.height / vh;
  return {
    left: rect.left + box.x * sx,
    top: rect.top + box.y * sy,
    width: box.width * sx,
    height: box.height * sy,
  };
}

/** Min/max box from two corner points, at least MIN_BOX source px per side. */
export function normalizeBox(
  a: { x: number; y: number },
  b: { x: number; y: number },
): Box {
  return {
    x: Math.min(a.x, b.x),
    y: Math.min(a.y, b.y),
    width: Math.max(MIN_BOX, Math.abs(a.x - b.x)),
    height: Math.max(MIN_BOX, Math.abs(a.y - b.y)),
  };
}
