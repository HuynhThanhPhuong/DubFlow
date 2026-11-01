"""Erase burned-in subtitles on glyph pixels only. Requires cv2 (OCR venv)."""
from __future__ import annotations

import cv2
import numpy as np

WHITE_MIN = 205  # same thresholds as engine_cli subtrack
DARK_MAX = 110
CONTRAST_MAX = 170  # a glyph pixel has a much darker pixel (outline/shadow) within ~5 px


def _odd(n: float) -> int:
    n = max(1, int(round(n)))
    return n if n % 2 else n + 1


def glyph_mask(gray_crop: np.ndarray, scale: float) -> np.ndarray:
    """Bool mask of the white glyph strokes (thin: strokes plus anti-aliased edge, not the gaps between characters).

    A white pixel counts as glyph only when something much darker (outline or drop shadow) is within a few
    pixels, so plain bright background is left alone. The soft shadow itself is handled by erase_frame."""
    white = gray_crop > WHITE_MIN
    r = 2 * int(round(5 * scale)) + 1
    low = cv2.erode(gray_crop, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (r, r)))
    glyph = (white & (low < CONTRAST_MAX)).astype(np.uint8)
    grow = int(round(2 * scale))
    grown = cv2.dilate(glyph, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1))) if grow else glyph
    # absorb stray bright pixels touching the mask so the fill cannot bleed them back in
    grown |= (white & (cv2.dilate(grown, np.ones((3, 3), np.uint8)) > 0)).astype(np.uint8)
    return grown > 0


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


def _pushpull(img: np.ndarray, known: np.ndarray) -> np.ndarray:
    """Multiscale push-pull interpolation of img (HxWxC float32) from the pixels where known (bool) is True."""
    wt = known.astype(np.float32)
    levels = [(img.astype(np.float32) * wt[..., None], wt)]
    while levels[-1][1].shape[0] > 2 and levels[-1][1].shape[1] > 2 and levels[-1][1].min() <= 0:
        num, den = levels[-1]
        sh, sw = max(1, num.shape[0] // 2), max(1, num.shape[1] // 2)
        levels.append((cv2.resize(num, (sw, sh), interpolation=cv2.INTER_AREA).reshape(sh, sw, -1),
                       cv2.resize(den, (sw, sh), interpolation=cv2.INTER_AREA)))
    num, den = levels[-1]
    val = num / np.maximum(den, 1e-4)[..., None]
    if den.max() <= 0:
        val = np.full_like(val, float(img.mean()))
    for num, den in reversed(levels[:-1]):
        up = cv2.resize(val, (num.shape[1], num.shape[0]), interpolation=cv2.INTER_LINEAR).reshape(num.shape)
        a = np.minimum(den * 4, 1.0)[..., None]
        val = num / np.maximum(den, 1e-4)[..., None] * a + up * (1 - a)
    return val


def smooth_fill(frame: np.ndarray, m: np.ndarray, ring: np.ndarray, scale: float = 1.0) -> np.ndarray:
    """Smooth multiscale (push-pull) fill of the masked area, light blur, ring-matched luminance grain."""
    h, w = m.shape
    big = _pushpull(frame.astype(np.float32), ~m)
    sigma = max(1.0, 1.5 * scale)
    big = cv2.GaussianBlur(big, (0, 0), sigma)
    if ring.any():
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
        hf = (gray - cv2.GaussianBlur(gray, (0, 0), 1.5))[ring]
        std = 1.4826 * float(np.median(np.abs(hf - np.median(hf))))  # robust: edges in the ring do not inflate the grain
        if std > 0.3:
            big += (_rng.normal(0, std * 0.8, (h, w)).astype(np.float32))[..., None]
    return np.clip(big, 0, 255).astype(np.uint8)


# Burned-in subtitles usually carry a soft black drop shadow (offset ~3 px, blur ~5 px at 1920 px). It is a
# multiplicative darkening bg * (1 - a), a = lam * AMAX * (1 - exp(-T / TAU)), T = blurred offset glyph mask.
# Constants were fitted on clean/subtitled frame pairs of a static shot; lam is re-estimated from each frame.
SHADOW_AMAX, SHADOW_TAU = 0.42, 0.38
SHADOW_OFFSET, SHADOW_SIGMA = 3.0, 5.0
FILL_GROW, FILL_CLOSE, FILL_FEATHER = 6, 5, 4  # px at 1920: dilation of the strokes, gap closing, edge feather
FILL_GROW_EDGE, FILL_CLOSE_EDGE = 3, 4  # same, near picture edges
EDGE_GRAD, EDGE_REACH = 14.0, 8  # gray levels per px that count as an edge; px around it kept thin


def shadow_field(core: np.ndarray, scale: float = 1.0) -> np.ndarray:
    """Blurred, offset glyph mask T in 0..1 (shape of the drop shadow)."""
    h, w = core.shape
    d = SHADOW_OFFSET * scale
    moved = cv2.warpAffine(core.astype(np.float32), np.float32([[1, 0, d], [0, 1, d]]), (w, h))
    return cv2.GaussianBlur(moved, (0, 0), max(1.0, SHADOW_SIGMA * scale))


def _shadow_unit(T: np.ndarray) -> np.ndarray:
    return SHADOW_AMAX * (1.0 - np.exp(-T / SHADOW_TAU))


def estimate_shadow(gray: np.ndarray, T: np.ndarray, excl: np.ndarray, scale: float = 1.0):
    """Shadow strength lam (1.0 = the fitted drop shadow, 0 = none) or None when the frame has no evidence.

    Compares the luminance just outside the glyphs (where the shadow is strong) with the luminance 20-40 px away,
    in column blocks, and takes the median so a local edge in the picture cannot dominate."""
    h, w = gray.shape
    unit = _shadow_unit(T)
    near = (T > 0.2) & (T < 0.6) & ~excl
    r = 2 * int(round(20 * scale)) + 1
    far = (T < 0.02) & (cv2.dilate((T >= 0.02).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (r, r))) > 0)
    block = max(32, int(round(80 * scale)))
    ratios = []
    for x in range(0, w, block):
        n, f = near[:, x:x + block], far[:, x:x + block]
        if n.sum() < 150 or f.sum() < 150:
            continue
        gf = float(np.median(gray[:, x:x + block][f]))
        if gf < 25:  # shadow on near-black is invisible and the ratio is meaningless
            continue
        expected = float(unit[:, x:x + block][n].mean())
        if expected < 0.05:
            continue
        ratios.append((1.0 - float(np.median(gray[:, x:x + block][n])) / gf) / expected)
    if not ratios:
        return None
    return float(np.clip(np.median(ratios), 0.0, 1.3))


def erase_frame(frame: np.ndarray, mask: np.ndarray, box: tuple, refs: list, band: tuple,
                scale: float = 1.0, static_tol: float = 6.0, style: dict | None = None):
    """Erase glyphs (mask = glyph_mask output, full-frame, limited to box) and their drop shadow.

    refs: band-sized BGR crops (frame[y0b:y1b]). A motion-aligned reference is used when its ring diff <= static_tol
    (the glyph and shadow zone is copied from it); otherwise the shadow is divided out of the frame and only the
    glyph strokes are rebuilt with smooth_fill. style: dict shared across frames; keeps the shadow strength.
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
    core = np.ascontiguousarray(mm[b0:b1])
    gray = cv2.cvtColor(fb, cv2.COLOR_BGR2GRAY)
    # strokes + a few px (anti-aliasing, ringing) and the small gaps inside/between strokes: that is what gets rebuilt
    def grown(px, gap):
        k = int(round(px * scale))
        mk = cv2.dilate(core.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1, 2 * k + 1)))
        c = 2 * int(round(gap * scale)) + 1
        return cv2.morphologyEx(mk, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (c, c))) > 0

    m_small, m_big = grown(FILL_GROW_EDGE, FILL_CLOSE_EDGE), grown(FILL_GROW, FILL_CLOSE)
    T = shadow_field(core, scale)
    lam = estimate_shadow(gray, T, m_small, scale)
    style = style if style is not None else {}
    if lam is not None:
        style['lam'] = lam if 'lam' not in style else 0.7 * style['lam'] + 0.3 * lam
    lam = style.get('lam', 1.0)
    a = lam * _shadow_unit(T)
    a[a < 0.004] = 0.0
    zone = m_big | (a > 0.03)
    ring = _ring_of(zone)
    best, best_diff = None, None
    for ref in refs or []:
        if ref is None or ref.shape != fb.shape:
            continue
        warped, diff = align_ref(fb, ref, zone, ring)
        if best_diff is None or diff < best_diff:
            best, best_diff = warped, diff
    out = frame.copy()
    if best is not None and best_diff <= static_tol:
        alpha = np.maximum(zone.astype(np.float32), cv2.GaussianBlur(zone.astype(np.float32), (0, 0), max(1.0, 2 * scale)))
        mixed = fb.astype(np.float32) * (1 - alpha[..., None]) + best.astype(np.float32) * alpha[..., None]
        out[b0:b1] = np.clip(mixed + .5, 0, 255).astype(np.uint8)
        return out, 'ref', best_diff
    corr = np.clip(fb.astype(np.float32) / (1.0 - a)[..., None] + .5, 0, 255).astype(np.uint8)
    # a wide rebuilt area hides the shadow remnants on smooth backgrounds, but smears picture edges that run under the
    # text, so near edges only the thin mask is rebuilt (textured/edged content hides the small shadow error)
    g = cv2.GaussianBlur(cv2.cvtColor(corr, cv2.COLOR_BGR2GRAY).astype(np.float32), (0, 0), 1.2)
    grad = np.hypot(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)) / 8.0
    k5 = int(round(5 * scale))
    near_text = cv2.dilate(m_small.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k5 + 1, 2 * k5 + 1))) > 0
    edge = (grad > EDGE_GRAD) & ~near_text
    k7 = int(round(EDGE_REACH * scale))
    edge_zone = cv2.dilate(edge.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k7 + 1, 2 * k7 + 1))) > 0
    m = m_small | (m_big & ~edge_zone)
    filled = smooth_fill(corr, m, _ring_of(m), scale)
    mf = m.astype(np.float32)
    wide = cv2.GaussianBlur(mf, (0, 0), max(1.0, FILL_FEATHER * scale))
    thin = cv2.GaussianBlur(mf, (0, 0), max(1.0, 1.5 * scale))
    alpha = np.maximum(mf, np.where(edge_zone, thin, wide))
    mixed = corr.astype(np.float32) * (1 - alpha[..., None]) + filled.astype(np.float32) * alpha[..., None]
    out[b0:b1] = np.clip(mixed + .5, 0, 255).astype(np.uint8)
    return out, 'smooth', best_diff
