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
