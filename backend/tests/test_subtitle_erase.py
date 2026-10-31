import unittest

try:
    import cv2
    import numpy as np
except ImportError:  # backend venv has no cv2
    cv2 = None
if cv2 is not None:
    from dubflow.subtitle_erase import erase_frame, fill_frame, glyph_mask, _ring_of


def _bg(h=120, w=360):
    gx = np.linspace(80, 170, w, dtype=np.float32)[None, :]
    gy = np.linspace(0, 20, h, dtype=np.float32)[:, None]
    return np.clip(gx + gy, 0, 255).astype(np.uint8)


def _with_text(bg):
    img = cv2.cvtColor(bg, cv2.COLOR_GRAY2BGR)
    glyph = np.zeros(bg.shape, np.uint8)
    cv2.putText(glyph, "SUB 88", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.8, 255, 3, cv2.LINE_8)
    outline = cv2.dilate(glyph, np.ones((7, 7), np.uint8)) > 0
    img[outline] = 0
    img[glyph > 0] = 255
    return img


def _gray(img):
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


@unittest.skipUnless(cv2 is not None, "cv2 not available")
class SubtitleEraseTest(unittest.TestCase):
    def setUp(self):
        self.bg = _bg()
        self.clean = cv2.cvtColor(self.bg, cv2.COLOR_GRAY2BGR)
        self.frame = _with_text(self.bg)
        self.gray = _gray(self.frame)
        self.box = (0, 0, self.frame.shape[1], self.frame.shape[0])
        self.mask = glyph_mask(self.gray, 1.0)

    def test_mask_covers_white_glyph_and_outline(self):
        white = self.gray > 200
        outline = self.gray < 60
        self.assertGreaterEqual(self.mask[white].mean(), 0.99)
        self.assertGreaterEqual(self.mask[outline].mean(), 0.95)
        self.assertLessEqual(self.mask.sum(), 2.5 * (white | outline).sum())

    def test_static_background_copied_from_clean_ref(self):
        out = fill_frame(self.frame, self.mask, self.box, self.clean)
        diff = np.abs(out.astype(int) - self.clean.astype(int))[self.mask]
        self.assertLess(diff.mean(), 3)

    def test_moving_background_uses_inpaint_not_ref(self):
        ref = np.roll(self.clean, 20, axis=1)
        out = fill_frame(self.frame, self.mask, self.box, ref)
        self.assertFalse(np.array_equal(out[self.mask], ref[self.mask]))
        self.assertEqual((_gray(out)[self.mask] > 200).sum(), 0)

    def test_no_ref_inpaints(self):
        out = fill_frame(self.frame, self.mask, self.box, None)
        self.assertEqual((_gray(out)[self.mask] > 200).sum(), 0)

    def test_pixels_outside_mask_untouched(self):
        out = fill_frame(self.frame, self.mask, self.box, None)
        self.assertTrue(np.array_equal(out[~self.mask], self.frame[~self.mask]))


def _textured(h=120, w=360, seed=3):
    rng = np.random.default_rng(seed)
    base = cv2.GaussianBlur(rng.normal(120, 40, (h + 40, w + 40)).astype(np.float32), (0, 0), 6)
    return np.clip(base, 0, 255)


def _bgr(g):
    return cv2.cvtColor(np.clip(g, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)


@unittest.skipUnless(cv2 is not None, "cv2 not available")
class TemporalFillTest(unittest.TestCase):
    def _scene(self):
        big = _textured()
        ref = _bgr(big[20:140, 20:380])
        clean = _bgr(big[22:142, 25:385])  # camera moved by (5, 2)
        frame = _with_text(cv2.cvtColor(clean, cv2.COLOR_BGR2GRAY))
        mask = cv2.dilate(glyph_mask(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), 1.0).astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
        return ref, clean, frame, mask

    def test_shifted_static_background_is_recovered(self):
        ref, clean, frame, mask = self._scene()
        h, w = frame.shape[:2]
        out, how, diff = erase_frame(frame, mask, (0, 0, w, h), [ref], (0, h), 1.0)
        self.assertEqual(how, 'ref')
        err = np.abs(out.astype(int) - clean.astype(int))[mask].mean()
        self.assertLess(err, 4)
        self.assertLess(np.abs(np.roll(ref, 5, axis=1).astype(int) - clean.astype(int))[:, 40:-40].mean(), 40)  # shift matters

    def test_no_ref_fill_has_no_faceting(self):
        _, clean, frame, mask = self._scene()
        h, w = frame.shape[:2]
        out, how, _ = erase_frame(frame, mask, (0, 0, w, h), [], (0, h), 1.0)
        self.assertEqual(how, 'smooth')
        g = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY).astype(np.float32)
        grad = np.hypot(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))
        ring = _ring_of(mask)
        self.assertLess(grad[mask].mean(), 2 * grad[ring].mean())
        self.assertEqual((cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)[mask] > 200).sum(), 0)

    def test_untouched_far_from_mask(self):
        _, _, frame, mask = self._scene()
        h, w = frame.shape[:2]
        out, _, _ = erase_frame(frame, mask, (0, 0, w, h), [], (0, h), 1.0)
        far = ~(cv2.dilate(mask.astype(np.uint8), np.ones((41, 41), np.uint8)) > 0)
        self.assertTrue(np.array_equal(out[far], frame[far]))


if __name__ == "__main__":
    unittest.main()
