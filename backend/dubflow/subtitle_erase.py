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


def align_ref(frame: np.ndarray, ref: np.ndarray, m: np.ndarray, ring: np.ndarray, max_shift: float = 40.0, good: float = 0.0):
    """Warp ref (same shape as frame) by the global shift that best matches frame outside the mask.

    Returns (warped_ref, ring_mean_abs_diff). Candidates: no shift and the phase-correlation shift (both signs).
    When the unshifted ref already matches within good (about the video noise), the phase correlation is skipped."""
    gf = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gr = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY).astype(np.float32)
    keep = ~m
    if keep.any():
        gf[m], gr[m] = gf[keep].mean(), gr[keep].mean()
    h, w = gf.shape
    if good > 0 and ring.any():
        d0 = float(np.abs(frame[ring].astype(np.float32) - ref[ring].astype(np.float32)).mean())
        if d0 <= good:
            return ref, d0
    cands = [(0.0, 0.0)]
    try:
        # half size is enough: the candidates are scored on the ring afterwards
        hh, hw = max(2, h // 2), max(2, w // 2)
        win = cv2.createHanningWindow((hw, hh), cv2.CV_32F)
        (dx, dy), _ = cv2.phaseCorrelate(cv2.resize(gf, (hw, hh), interpolation=cv2.INTER_AREA),
                                         cv2.resize(gr, (hw, hh), interpolation=cv2.INTER_AREA), win)
        dx, dy = dx * w / hw, dy * h / hh
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


LAMA_SIZE, LAMA_CTX, LAMA_OVERLAP = 512, 48, 64  # model input side; context rows/cols around the mask; tile overlap
LAMA_REUSE_TOL = 2.5  # ring diff (gray levels) under which an earlier LaMa result is reused (video noise ~1-1.7); 0 = one model call per frame
LAMA_KEEP = 4  # number of recent LaMa-filled band crops kept as references (only when reuse is on)
ALIGN_GOOD = 1.6  # ring diff (gray levels) that counts as a perfect match (video noise floor 1-1.7): stop searching
STATIC_TOL = 6.0  # ring diff under which a motion-aligned clean reference replaces the glyph zone


class LamaSession:
    """onnxruntime session wrapper that survives run-time failures.

    A failing CUDA run (e.g. out of memory) is retried on a CPU session that is created lazily; when that fails too the
    exception reaches erase_frame, which uses the smooth fill for that frame. Every CUDA -> CPU retry is recorded in
    events so the stage can note the fallback in erase.json."""

    def __init__(self, session, provider, model):
        self.session, self.provider, self.model = session, provider, model
        self.cpu = None
        self.on_cpu = False  # after one CUDA failure the rest of the run stays on CPU
        self.events = []  # first few messages only
        self.event_count = 0

    def get_inputs(self):
        return self.session.get_inputs()

    def _note(self, text):
        self.event_count += 1
        if len(self.events) < 3:
            self.events.append(text)

    def run(self, outputs, feeds):
        if not self.on_cpu:
            try:
                return self.session.run(outputs, feeds)
            except Exception as exc:  # noqa: BLE001 - any runtime failure (CUDA OOM, driver reset) falls back
                if self.provider != 'cuda':
                    raise
                self._note(f'LaMa CUDA run failed, using CPU for the rest of the run ({str(exc)[:120]})')
                self.on_cpu = True
        if self.cpu is None:
            import onnxruntime as ort
            self.cpu = ort.InferenceSession(str(self.model), providers=['CPUExecutionProvider'])
        return self.cpu.run(outputs, feeds)


def open_lama(model, dll_dir=None):
    """Open the LaMa ONNX model on CUDA when possible. Returns (session, provider, warning).

    provider is 'cuda' or 'cpu'; warning is None or a short text when the slow CPU path is used. When onnxruntime is
    missing or no session can be opened, returns (None, None, warning) and the caller uses the smooth fill. The CUDA 12 /
    cuDNN 9 DLLs are looked up in dll_dir (a setting, e.g. the torch/lib folder of another environment); nothing is copied."""
    import os
    try:
        import onnxruntime as ort
    except Exception as exc:  # noqa: BLE001 - ImportError or a broken native install
        return None, None, f'LaMa unavailable, smooth fill used: onnxruntime cannot be imported ({str(exc)[:120]})'
    warning = None
    cuda_listed = 'CUDAExecutionProvider' in ort.get_available_providers()
    if not cuda_listed:
        warning = 'LaMa runs on CPU (slow): this onnxruntime has no CUDA provider (install onnxruntime-gpu)'
    elif not dll_dir or not os.path.isdir(dll_dir):
        warning = f'LaMa runs on CPU (slow): CUDA/cuDNN DLL folder missing ({dll_dir or "not configured"})'
    else:
        os.add_dll_directory(str(dll_dir))
        os.environ['PATH'] = str(dll_dir) + os.pathsep + os.environ.get('PATH', '')
        so = ort.SessionOptions()
        so.log_severity_level = 3
        try:
            session = ort.InferenceSession(str(model), so, providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
            if session.get_providers()[0] == 'CUDAExecutionProvider':
                return LamaSession(session, 'cuda', model), 'cuda', None
            warning = 'LaMa runs on CPU (slow): CUDA provider could not start (see DLL folder and driver)'
        except Exception as exc:  # noqa: BLE001 - any CUDA init failure falls back to CPU
            warning = f'LaMa runs on CPU (slow): CUDA provider failed ({str(exc)[:120]})'
    try:
        return LamaSession(ort.InferenceSession(str(model), providers=['CPUExecutionProvider']), 'cpu', model), 'cpu', warning
    except Exception as exc:  # noqa: BLE001 - corrupt or unreadable model
        return None, None, f'LaMa unavailable, smooth fill used: model cannot be opened ({str(exc)[:120]})'


def _tile_spans(lo: int, hi: int, limit: int):
    """Overlapping [a, b) spans of width <= LAMA_SIZE covering [lo, hi), clipped to [0, limit)."""
    lo, hi = max(0, lo), min(limit, hi)
    if hi - lo <= LAMA_SIZE:
        return [(lo, hi)]
    n = -(-(hi - lo - LAMA_OVERLAP) // (LAMA_SIZE - LAMA_OVERLAP))
    step = (hi - lo - LAMA_SIZE) / (n - 1)
    return [(int(round(lo + i * step)), int(round(lo + i * step)) + LAMA_SIZE) for i in range(n)]


def lama_inpaint(session, img: np.ndarray, mask: np.ndarray, scale: float = 1.0, feather: float = 1.2) -> np.ndarray:
    """Inpaint the True pixels of mask (same HxW as img, BGR uint8) with a LaMa ONNX session (fixed 512x512 input).

    The mask bounding box plus context is cut into overlapping bands (<= 512 rows) and, inside a band, overlapping tiles
    (<= 512 px wide); a band's tiles are stacked into 512x512 canvases at native scale, so one model call normally covers
    a whole subtitle line. Overlaps are blended. Only masked pixels change (feathered ~1 px); the rest of img is returned
    untouched."""
    ys, xs = np.nonzero(mask)
    if not len(ys):
        return img
    H, W = mask.shape
    ctx = int(round(LAMA_CTX * scale))
    y_lo, y_hi = max(0, int(ys.min()) - ctx), min(H, int(ys.max()) + 1 + ctx)
    col_spans = _tile_spans(int(xs.min()) - ctx, int(xs.max()) + 1 + ctx, W)
    names = [i.name for i in session.get_inputs()]
    # everything below works on the rows/columns the tiles cover, not on the whole frame (4x faster than full-frame math)
    cx0, cx1 = min(a for a, _ in col_spans), max(b for _, b in col_spans)
    rgb = cv2.cvtColor(np.ascontiguousarray(img[y_lo:y_hi, cx0:cx1]), cv2.COLOR_BGR2RGB)
    mc = mask[y_lo:y_hi, cx0:cx1]
    acc = np.zeros(rgb.shape, np.float32)
    wsum = np.zeros(rgb.shape[:2], np.float32)

    def ramp_weights(a, b, limit):
        w = np.ones(b - a, np.float32)
        r = min(LAMA_OVERLAP, b - a)
        if a > 0:
            w[:r] = np.minimum(w[:r], np.linspace(0.05, 1, r, dtype=np.float32))
        if b < limit:
            w[-r:] = np.minimum(w[-r:], np.linspace(1, 0.05, r, dtype=np.float32))
        return w

    for ya, yb in _tile_spans(y_lo, y_hi, H):  # bands of <= LAMA_SIZE rows, overlapping when the mask is taller
        th = yb - ya
        spans = [s for s in col_spans if mask[ya:yb, s[0]:s[1]].any()]
        if not spans:
            continue
        wy = ramp_weights(ya, yb, H)
        r0, r1 = ya - y_lo, yb - y_lo
        per = max(1, LAMA_SIZE // th)  # tiles stacked per canvas
        for c0 in range(0, len(spans), per):
            group = spans[c0:c0 + per]
            canvas = np.zeros((LAMA_SIZE, LAMA_SIZE, 3), np.float32)
            cmask = np.zeros((LAMA_SIZE, LAMA_SIZE), np.float32)
            for j, (a, b) in enumerate(group):
                canvas[j * th:(j + 1) * th, :b - a] = rgb[r0:r1, a - cx0:b - cx0]
                cmask[j * th:(j + 1) * th, :b - a] = mc[r0:r1, a - cx0:b - cx0]
            # pad the unused canvas area with the nearest content so it does not look like a huge black hole edge
            used = len(group) * th
            if used < LAMA_SIZE:
                canvas[used:] = canvas[used - 1:used]
            feeds = {names[0]: (canvas / 255.0).transpose(2, 0, 1)[None].astype(np.float32), names[1]: cmask[None, None]}
            res = np.asarray(session.run(None, feeds)[0])[0].transpose(1, 2, 0)
            for j, (a, b) in enumerate(group):
                w = ramp_weights(a, b, W)[None, :] * wy[:, None]
                acc[r0:r1, a - cx0:b - cx0] += res[j * th:(j + 1) * th, :b - a] * w[..., None]
                wsum[r0:r1, a - cx0:b - cx0] += w
    got = wsum > 0
    filled = np.where(got[..., None], acc / np.maximum(wsum, 1e-6)[..., None], rgb.astype(np.float32))
    mf = mc.astype(np.float32)
    alpha = np.maximum(mf, cv2.GaussianBlur(mf, (0, 0), max(0.8, feather * scale)))
    alpha = np.minimum(alpha, 1.0) * got
    patch = rgb.astype(np.float32) * (1 - alpha[..., None]) + filled * alpha[..., None]
    out = img.copy()
    out[y_lo:y_hi, cx0:cx1] =cv2.cvtColor(np.clip(patch + .5, 0, 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
    return out


def _paste_ref(fb: np.ndarray, ref: np.ndarray, zone: np.ndarray, scale: float) -> np.ndarray:
    """Copy ref (aligned, same shape as fb) into the zone of fb with a ~2 px feathered edge.

    The reference was shot at another moment: the smooth brightness/colour offset measured around the zone is carried
    into it, so the pasted patch does not show up as a faint lighter/darker shape of the glyphs."""
    alpha = np.maximum(zone.astype(np.float32), cv2.GaussianBlur(zone.astype(np.float32), (0, 0), max(1.0, 2 * scale)))
    ref = ref.astype(np.float32)
    # the offset is smooth, so it is interpolated at 1/4 size (16x cheaper) and scaled back up
    h, w = zone.shape
    sh, sw = max(1, h // 4), max(1, w // 4)
    known = (~zone).astype(np.float32)
    wt = cv2.resize(known, (sw, sh), interpolation=cv2.INTER_AREA)
    num = cv2.resize((fb.astype(np.float32) - ref) * known[..., None], (sw, sh), interpolation=cv2.INTER_AREA).reshape(sh, sw, -1)
    small = _pushpull(num / np.maximum(wt, 1e-4)[..., None], wt > 0.5)
    offset = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR).reshape(h, w, -1)
    ref = ref + cv2.GaussianBlur(offset, (0, 0), max(2.0, 2 * scale))
    mixed = fb.astype(np.float32) * (1 - alpha[..., None]) + ref * alpha[..., None]
    return np.clip(mixed + .5, 0, 255).astype(np.uint8)


def erase_frame(frame: np.ndarray, mask: np.ndarray, box: tuple, refs: list, band: tuple,
                scale: float = 1.0, static_tol: float = STATIC_TOL, style: dict | None = None, lama=None,
                reuse_tol: float = LAMA_REUSE_TOL):
    """Erase glyphs (mask = glyph_mask output, full-frame, limited to box) and their drop shadow.

    refs: band-sized BGR crops (frame[y0b:y1b]). A motion-aligned reference is used when its ring diff <= static_tol
    (the glyph and shadow zone is copied from it); otherwise the shadow is divided out of the frame and only the
    glyph strokes are rebuilt. With lama (an onnxruntime session) they are inpainted by LaMa on every such frame (an
    earlier LaMa result is reused only when reuse_tol > 0 and its ring diff <= reuse_tol: faster, but can leave stale
    patches); without it they use smooth_fill.
    style: dict shared across frames; keeps the shadow strength and the recent LaMa results.
    Returns (out, how, ring_diff) with how in {'none','ref','lamaref','lama','smooth'}."""
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
        warped, diff = align_ref(fb, ref, zone, ring, good=ALIGN_GOOD)
        if best_diff is None or diff < best_diff:
            best, best_diff = warped, diff
        if best_diff <= ALIGN_GOOD:
            break
    out = frame.copy()
    if best is not None and best_diff <= static_tol:
        out[b0:b1] = _paste_ref(fb, best, zone, scale)
        return out, 'ref', best_diff
    if lama is not None:
        keys = style.setdefault('lama_keys', [])
        kbest, kdiff = None, None
        for key in (keys if reuse_tol > 0 else []):
            if key.shape != fb.shape:
                continue
            warped, diff = align_ref(fb, key, zone, ring, good=ALIGN_GOOD)
            if kdiff is None or diff < kdiff:
                kbest, kdiff = warped, diff
            if kdiff <= ALIGN_GOOD:
                break
        if kbest is not None and kdiff <= reuse_tol:
            out[b0:b1] = _paste_ref(fb, kbest, zone, scale)
            return out, 'lamaref', kdiff
        # LaMa rebuilds glyphs and the shadow zone from the untouched frame (measured cleaner than dividing the shadow
        # out and inpainting only the strokes, which left grey smudges at object edges)
        hole = np.zeros((H, W), bool)
        hole[b0:b1] = zone
        try:
            lama_out = lama_inpaint(lama, frame, hole, scale)
        except Exception:  # noqa: BLE001 - model failed even after the CPU retry: smooth fill for this frame
            style['lama_failed'] = style.get('lama_failed', 0) + 1
            lama_out = None
        if lama_out is not None:
            out = lama_out
            if reuse_tol > 0:
                keys.append(np.ascontiguousarray(out[b0:b1]))
                del keys[:-LAMA_KEEP]
            return out, 'lama', best_diff
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
