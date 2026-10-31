"""Erase burned-in subtitles on glyph pixels only. Requires cv2 (OCR venv)."""
from __future__ import annotations

import cv2
import numpy as np

WHITE_MIN = 205  # same thresholds as engine_cli subtrack
DARK_MAX = 110


def _odd(n: float) -> int:
    n = max(1, int(round(n)))
    return n if n % 2 else n + 1


def glyph_mask(gray_crop: np.ndarray, scale: float) -> np.ndarray:
    """Bool mask of white glyph pixels with a dark outline, grown to cover outline and halo."""
    white = gray_crop > WHITE_MIN
    dark = (gray_crop < DARK_MAX).astype(np.uint8)
    near = cv2.dilate(dark, cv2.getStructuringElement(cv2.MORPH_CROSS, (_odd(7 * scale),) * 2)) > 0
    glyph = (white & near).astype(np.uint8)
    grow = int(round(2 * scale)) + 1
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (2 * grow + 1, 2 * grow + 1))
    grown = cv2.dilate(glyph, k)
    # absorb stray bright pixels touching the mask so inpainting cannot bleed them back in
    grown |= (white & (cv2.dilate(grown, np.ones((3, 3), np.uint8)) > 0)).astype(np.uint8)
    return grown > 0


def fill_frame(frame: np.ndarray, mask: np.ndarray, box: tuple, clean_ref: np.ndarray | None,
               static_tol: float = 6.0) -> np.ndarray:
    """Replace mask pixels inside box=(x0, y0, x1, y1). mask has the same HxW as frame."""
    x0, y0, x1, y1 = (int(v) for v in box)
    H, W = frame.shape[:2]
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
    m = np.zeros((H, W), bool)
    m[y0:y1, x0:x1] = mask[y0:y1, x0:x1]
    out = frame.copy()
    if not m.any():
        return out
    m8 = m.astype(np.uint8)
    ring = (cv2.dilate(m8, cv2.getStructuringElement(cv2.MORPH_RECT, (17, 17))) > 0) & ~m
    ring[:y0], ring[y1:], ring[:, :x0], ring[:, x1:] = False, False, False, False
    use_ref = False
    if clean_ref is not None and clean_ref.shape == frame.shape and ring.any():
        use_ref = float(np.abs(frame[ring].astype(np.float32) - clean_ref[ring].astype(np.float32)).mean()) <= static_tol
    if use_ref:
        filled = clean_ref
    else:
        filled = cv2.inpaint(np.ascontiguousarray(frame), m8 * 255, 3, cv2.INPAINT_TELEA)
    # 1 px edge blend: the mask boundary pixels take the mean of the filled pixel and its
    # 3x3 blurred neighbourhood of the filled image; pixels outside the mask stay exact.
    smooth = cv2.blur(filled, (3, 3))
    edge = m & ~(cv2.erode(m8, np.ones((3, 3), np.uint8)) > 0)
    repl = filled.copy()
    repl[edge] = ((filled[edge].astype(np.uint16) + smooth[edge].astype(np.uint16)) // 2).astype(filled.dtype)
    out[m] = repl[m]
    return out


_rng = np.random.default_rng(12345)


def _ring_of(m: np.ndarray, size: int = 17) -> np.ndarray:
    m8 = m.astype(np.uint8)
    return (cv2.dilate(m8, cv2.getStructuringElement(cv2.MORPH_RECT, (size, size))) > 0) & ~m


def align_ref(frame: np.ndarray, ref: np.ndarray, m: np.ndarray, ring: np.ndarray, max_shift: float = 40.0):
    """Warp ref (same shape as frame) by the global shift that best matches frame outside the mask.

    Returns (warped_ref, ring_mean_abs_diff). Candidates: no shift and the phase-correlation shift (both signs)."""
    gf = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gr = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY).astype(np.float32)
    keep = ~m
    if keep.any():
        gf[m], gr[m] = gf[keep].mean(), gr[keep].mean()
    h, w = gf.shape
    cands = [(0.0, 0.0)]
    try:
        win = cv2.createHanningWindow((w, h), cv2.CV_32F)
        (dx, dy), _ = cv2.phaseCorrelate(gf, gr, win)
        if abs(dx) <= max_shift and abs(dy) <= max_shift and (abs(dx) > .05 or abs(dy) > .05):
            cands += [(dx, dy), (-dx, -dy)]
    except cv2.error:
        pass
    best, best_diff = ref, None
    for dx, dy in cands:
        warped = ref if not (dx or dy) else cv2.warpAffine(ref, np.float32([[1, 0, dx], [0, 1, dy]]), (w, h),
                                                          flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        diff = float(np.abs(frame[ring].astype(np.float32) - warped[ring].astype(np.float32)).mean()) if ring.any() else 255.0
        if best_diff is None or diff < best_diff:
            best, best_diff = warped, diff
    return best, best_diff


def smooth_fill(frame: np.ndarray, m: np.ndarray, ring: np.ndarray, scale: float = 1.0) -> np.ndarray:
    """Smooth multiscale (push-pull) fill of the masked area, light blur, ring-matched luminance grain."""
    h, w = m.shape
    # push-pull: weighted averages down a pyramid, then fill unknown pixels from coarser levels (no facets)
    wt = (~m).astype(np.float32)
    levels = [(frame.astype(np.float32) * wt[..., None], wt)]
    while levels[-1][1].shape[0] > 2 and levels[-1][1].shape[1] > 2 and levels[-1][1].min() <= 0:
        num, den = levels[-1]
        sh, sw = max(1, num.shape[0] // 2), max(1, num.shape[1] // 2)
        levels.append((cv2.resize(num, (sw, sh), interpolation=cv2.INTER_AREA), cv2.resize(den, (sw, sh), interpolation=cv2.INTER_AREA)))
    num, den = levels[-1]
    val = num / np.maximum(den, 1e-4)[..., None]
    if den.max() <= 0:
        val = np.full_like(val, float(frame.reshape(-1, 3).mean(0)[0]))
    for num, den in reversed(levels[:-1]):
        up = cv2.resize(val, (num.shape[1], num.shape[0]), interpolation=cv2.INTER_LINEAR)
        a = np.minimum(den * 4, 1.0)[..., None]
        val = num / np.maximum(den, 1e-4)[..., None] * a + up * (1 - a)
    big = val
    sigma = max(1.0, 1.5 * scale)
    big = cv2.GaussianBlur(big, (0, 0), sigma)
    if ring.any():
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
        hf = gray - cv2.GaussianBlur(gray, (0, 0), 1.5)
        std = float(hf[ring].std())
        if std > 0.3:
            big += (_rng.normal(0, std * 0.8, (h, w)).astype(np.float32))[..., None]
    return np.clip(big, 0, 255).astype(np.uint8)


def erase_frame(frame: np.ndarray, mask: np.ndarray, box: tuple, refs: list, band: tuple,
                scale: float = 1.0, static_tol: float = 6.0):
    """Erase masked pixels (mask full-frame, limited to box). refs: band-sized BGR crops (frame[y0b:y1b]).

    Uses the best motion-aligned reference when its ring diff <= static_tol, otherwise smooth_fill.
    Returns (out, how, ring_diff) with how in {'none','ref','smooth'}."""
    x0, y0, x1, y1 = (int(v) for v in box)
    H, W = frame.shape[:2]
    b0, b1 = max(0, int(band[0])), min(H, int(band[1]))
    mm = np.zeros((H, W), bool)
    mm[max(0, y0):min(H, y1), max(0, x0):min(W, x1)] = mask[max(0, y0):min(H, y1), max(0, x0):min(W, x1)]
    mm[:b0], mm[b1:] = False, False
    if not mm.any():
        return frame.copy(), 'none', None
    fb = np.ascontiguousarray(frame[b0:b1])
    m = np.ascontiguousarray(mm[b0:b1])
    # close small holes (inside letters) so shadow remnants there cannot survive as dark specks
    close = 2 * int(round(8 * scale)) + 1
    m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (close, close))) > 0
    ring = _ring_of(m)
    best, best_diff = None, None
    for ref in refs or []:
        if ref is None or ref.shape != fb.shape:
            continue
        warped, diff = align_ref(fb, ref, m, ring)
        if best_diff is None or diff < best_diff:
            best, best_diff = warped, diff
    if best is not None and best_diff <= static_tol:
        filled, how = best, 'ref'
    else:
        filled, how = smooth_fill(fb, m, ring, scale), 'smooth'
    sigma = max(1.0, 4 * scale)
    alpha = np.maximum(m.astype(np.float32), cv2.GaussianBlur(m.astype(np.float32), (0, 0), sigma))
    if how == 'ref':
        alpha = np.maximum(m.astype(np.float32), cv2.GaussianBlur(m.astype(np.float32), (0, 0), max(1.0, 2 * scale)))
    mixed = fb.astype(np.float32) * (1 - alpha[..., None]) + filled.astype(np.float32) * alpha[..., None]
    out = frame.copy()
    out[b0:b1] = np.clip(mixed + .5, 0, 255).astype(np.uint8)
    return out, how, best_diff
