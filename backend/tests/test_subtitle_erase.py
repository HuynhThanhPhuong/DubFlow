import unittest

try:
    import cv2
    import numpy as np
except ImportError:  # backend venv has no cv2
    cv2 = None
if cv2 is not None:
    from dubflow.subtitle_erase import fill_frame, glyph_mask


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


if __name__ == "__main__":
    unittest.main()
