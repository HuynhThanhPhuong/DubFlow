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


@unittest.skipUnless(cv2 is not None, "cv2 not available")
class EraseStageTest(unittest.TestCase):
    def _run(self, duration, tmp):
        import json, shutil, subprocess, sys
        from pathlib import Path
        ff = shutil.which('ffmpeg') or 'D:/OmniVoice/tools/ffmpeg.exe'
        if not Path(ff).exists():
            self.skipTest('ffmpeg unavailable')
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dubflow'))
        import engine_cli
        d = Path(tmp)
        src = d / 'source.mp4'
        subprocess.run([ff, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=gray:s=320x240:r=25:d=2', '-f', 'lavfi', '-i', 'sine=d=2',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(src)], check=True)
        (d / 'subtrack.json').write_text(json.dumps(dict(version=1, fps=10, band=[170, 220],
            segments=[dict(s=.5, e=1.2, x0=60, y0=180, x1=260, y1=210, text='a')])))
        req = dict(ffmpeg=ff, source=str(src), width=320, height=240, fps_arg='25', duration=duration,
                   source_hash='h', subtrack_hash='s', source_size=1, source_mtime_ns=2)
        engine_cli.erase(d, req)
        return d

    def test_complete_decode_writes_clean_mp4_with_audio(self):
        import json, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            d = self._run(2.0, tmp)
            self.assertTrue((d / 'clean.mp4').is_file())
            self.assertFalse((d / 'clean.tmp.mp4').exists())
            self.assertFalse((d / 'erase-refs').exists())
            stamp = json.loads((d / 'erase.json').read_text())
            self.assertEqual((stamp['version'], stamp['fps']), (2, '25'))

    def test_truncated_decode_is_rejected(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, 'truncated'):
                self._run(10.0, tmp)  # source has 2 s but metadata claims 10 s
            self.assertFalse((Path(tmp) / 'clean.mp4').exists())
            self.assertFalse((Path(tmp) / 'clean.tmp.mp4').exists())


if __name__ == "__main__":
    unittest.main()
