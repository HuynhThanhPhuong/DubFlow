import unittest
from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError:  # backend venv has no cv2
    cv2 = None
if cv2 is not None:
    from dubflow.subtitle_erase import (LAMA_SIZE, SHADOW_AMAX, SHADOW_TAU, _ring_of, erase_frame, estimate_shadow,
                                        glyph_mask, lama_inpaint, open_lama, shadow_field)


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
class GlyphMaskTest(unittest.TestCase):
    def setUp(self):
        self.bg = _bg()
        self.frame = _with_text(self.bg)
        self.gray = _gray(self.frame)
        self.mask = glyph_mask(self.gray, 1.0)

    def test_mask_covers_white_strokes_but_not_the_whole_line(self):
        white = self.gray > 200
        self.assertGreaterEqual(self.mask[white].mean(), 0.99)
        # thin mask: strokes plus a 2 px rim, far less than the old dilated whole-line box
        self.assertLessEqual(self.mask.sum(), 3.5 * white.sum())
        wide = cv2.dilate(self.mask.astype(np.uint8), np.ones((19, 19), np.uint8)) > 0  # the old whole-line style mask
        self.assertLess(self.mask.sum(), 0.5 * wide.sum())

    def test_gaps_between_characters_are_not_masked(self):
        cols = self.mask.any(0)
        white_cols = (self.gray > 200).any(0)
        gap = ~cv2.dilate(white_cols.astype(np.uint8)[None, :], np.ones((1, 15), np.uint8))[0].astype(bool)
        inside = np.arange(len(gap))
        inside = (inside > np.where(white_cols)[0].min()) & (inside < np.where(white_cols)[0].max())
        self.assertFalse(cols[gap & inside].any())

    def test_plain_bright_area_is_not_a_glyph(self):
        bright = np.full((120, 360), 230, np.uint8)
        self.assertEqual(glyph_mask(bright, 1.0).sum(), 0)

    def test_scale_grows_the_rim(self):
        self.assertGreater(glyph_mask(self.gray, 2.0).sum(), self.mask.sum())


def _shadowed(bg_gray, scale=1.0):
    """Frame with white text and a soft drop shadow that follows the fitted model; returns (frame, clean, text_mask)."""
    h, w = bg_gray.shape
    text = np.zeros((h, w), np.uint8)
    cv2.putText(text, "SUB 88", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.8, 255, 5, cv2.LINE_8)
    core = cv2.dilate(text, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))) > 0
    T = shadow_field(core, scale)
    a = SHADOW_AMAX * (1 - np.exp(-T / SHADOW_TAU))
    clean = cv2.cvtColor(bg_gray, cv2.COLOR_GRAY2BGR)
    frame = np.clip(clean.astype(np.float32) * (1 - a)[..., None] + .5, 0, 255).astype(np.uint8)
    frame[text > 0] = 255
    return frame, clean, text > 0


@unittest.skipUnless(cv2 is not None, "cv2 not available")
class ShadowEraseTest(unittest.TestCase):
    def setUp(self):
        self.frame, self.clean, self.text = _shadowed(_bg())
        self.h, self.w = self.frame.shape[:2]
        self.mask = glyph_mask(_gray(self.frame), 1.0)

    def _erase(self, refs=()):
        return erase_frame(self.frame, self.mask, (0, 0, self.w, self.h), list(refs), (0, self.h), 1.0, style={})

    def test_shadow_strength_is_estimated(self):
        core = self.mask
        T = shadow_field(core, 1.0)
        lam = estimate_shadow(_gray(self.frame), T, cv2.dilate(core.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0, 1.0)
        self.assertIsNotNone(lam)
        self.assertGreater(lam, 0.6)
        self.assertLess(lam, 1.4)

    def test_no_evidence_gives_none(self):
        empty = np.zeros((60, 60), bool)
        self.assertIsNone(estimate_shadow(np.full((60, 60), 120, np.uint8), shadow_field(empty), empty))

    def test_glyphs_and_soft_shadow_are_gone_without_a_reference(self):
        out, how, _ = self._erase()
        self.assertEqual(how, 'smooth')
        zone = cv2.dilate(self.text.astype(np.uint8), np.ones((31, 31), np.uint8)) > 0
        err = np.abs(_gray(out).astype(int) - _gray(self.clean).astype(int))
        self.assertEqual((_gray(out)[self.text] > 200).sum(), 0)
        self.assertLess(err[zone].mean(), 3.0)
        self.assertLess(err[zone].max(), 25)

    def test_no_embossed_ghost_of_the_text(self):
        out, _, _ = self._erase()
        diff = (_gray(out).astype(np.float32) - _gray(self.clean).astype(np.float32))
        ghost = cv2.GaussianBlur(diff, (0, 0), 2.0)[cv2.dilate(self.text.astype(np.uint8), np.ones((15, 15), np.uint8)) > 0]
        self.assertLess(np.abs(ghost).max(), 5.0)

    def test_pixels_far_from_text_untouched(self):
        out, _, _ = self._erase()
        far = ~(cv2.dilate(self.mask.astype(np.uint8), np.ones((61, 61), np.uint8)) > 0)
        self.assertTrue(np.array_equal(out[far], self.frame[far]))

    def test_static_reference_is_used_when_it_matches(self):
        out, how, diff = self._erase([self.clean])
        self.assertEqual(how, 'ref')
        zone = cv2.dilate(self.text.astype(np.uint8), np.ones((15, 15), np.uint8)) > 0
        self.assertLess(np.abs(out.astype(int) - self.clean.astype(int))[zone].mean(), 2.0)

    def test_moving_reference_is_rejected(self):
        out, how, _ = self._erase([np.roll(self.clean, 30, axis=1)])
        self.assertEqual(how, 'smooth')
        self.assertEqual((_gray(out)[self.text] > 200).sum(), 0)


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



class _FakeLama:
    """Stands in for the onnxruntime session: copies the image, paints the hole mid grey (value 100/255)."""
    def __init__(self):
        self.calls = []

    def get_inputs(self):
        class _I:
            def __init__(self, name):
                self.name = name
        return [_I('image'), _I('mask')]

    def run(self, _outputs, feeds):
        image, mask = feeds['image'], feeds['mask']
        assert image.shape == (1, 3, LAMA_SIZE, LAMA_SIZE) and mask.shape == (1, 1, LAMA_SIZE, LAMA_SIZE)
        self.calls.append(float(mask.sum()))
        out = image * 255.0 * (1 - mask) + 100.0 * mask
        return [out.astype(np.float32)]


@unittest.skipUnless(cv2 is not None, "cv2 not available")
class LamaFillTest(unittest.TestCase):
    def test_only_masked_pixels_change_and_they_take_the_model_output(self):
        img = np.full((200, 300, 3), 180, np.uint8)
        mask = np.zeros((200, 300), bool)
        mask[90:110, 100:200] = True
        fake = _FakeLama()
        out = lama_inpaint(fake, img, mask)
        self.assertEqual(len(fake.calls), 1)
        self.assertTrue((out[mask] == 100).all())
        self.assertTrue((out[~cv2.dilate(mask.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool)] == 180).all())

    def test_wide_mask_is_tiled_and_stays_seamless(self):
        img = np.full((300, 1500, 3), 180, np.uint8)
        mask = np.zeros((300, 1500), bool)
        mask[20:280, 50:1450] = True
        fake = _FakeLama()
        out = lama_inpaint(fake, img, mask)
        self.assertGreaterEqual(len(fake.calls), 2)
        self.assertTrue((out[mask] == 100).all())  # overlap blending of identical tile outputs keeps the value
        self.assertTrue((out[:15] == 180).all() and (out[285:] == 180).all())

    def test_tall_mask_is_tiled_vertically_and_fully_erased(self):
        img = np.full((900, 300, 3), 180, np.uint8)
        mask = np.zeros((900, 300), bool)
        mask[20:880, 40:260] = True  # mask plus context is far taller than one 512 px model input
        fake = _FakeLama()
        out = lama_inpaint(fake, img, mask)
        self.assertGreaterEqual(len(fake.calls), 2)
        self.assertTrue((out[mask] == 100).all())
        self.assertTrue((out[~cv2.dilate(mask.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool)] == 180).all())

    def test_empty_mask_returns_input(self):
        img = np.full((50, 60, 3), 7, np.uint8)
        fake = _FakeLama()
        self.assertIs(lama_inpaint(fake, img, np.zeros((50, 60), bool)), img)
        self.assertEqual(fake.calls, [])

    def test_erase_frame_uses_lama_then_reuses_result_for_a_similar_frame(self):
        frame, _clean, _text = _shadowed(_bg())
        h, w = frame.shape[:2]
        mask = glyph_mask(_gray(frame), 1.0)
        fake, style = _FakeLama(), {}
        out, how, _ = erase_frame(frame, mask, (0, 0, w, h), [], (0, h), 1.0, style=style, lama=fake, reuse_tol=4.5)
        self.assertEqual((how, len(fake.calls)), ('lama', 1))
        self.assertFalse(((out == 255).all(axis=2) & mask).any())  # no white glyph pixel left
        out2, how2, diff = erase_frame(frame, mask, (0, 0, w, h), [], (0, h), 1.0, style=style, lama=fake, reuse_tol=4.5)
        self.assertEqual((how2, len(fake.calls)), ('lamaref', 1))
        self.assertLessEqual(diff, 4.5)

    def test_reuse_off_is_one_model_call_per_frame(self):
        frame, _clean, _text = _shadowed(_bg())
        h, w = frame.shape[:2]
        mask = glyph_mask(_gray(frame), 1.0)
        fake, style = _FakeLama(), {}
        for n in (1, 2, 3):
            _, how, _ = erase_frame(frame, mask, (0, 0, w, h), [], (0, h), 1.0, style=style, lama=fake, reuse_tol=0)
            self.assertEqual((how, len(fake.calls)), ('lama', n))
        self.assertFalse(style.get('lama_keys'))

    def test_changed_content_triggers_a_new_model_call(self):
        frame, _clean, _text = _shadowed(_bg())
        h, w = frame.shape[:2]
        mask = glyph_mask(_gray(frame), 1.0)
        fake, style = _FakeLama(), {}
        erase_frame(frame, mask, (0, 0, w, h), [], (0, h), 1.0, style=style, lama=fake, reuse_tol=4.5)
        moved = np.clip(frame.astype(np.int16) + 40, 0, 255).astype(np.uint8)
        moved[np.repeat(mask[..., None], 3, axis=2)] = 255
        _, how, _ = erase_frame(moved, mask, (0, 0, w, h), [], (0, h), 1.0, style=style, lama=fake, reuse_tol=4.5)
        self.assertEqual((how, len(fake.calls)), ('lama', 2))

    def test_open_lama_falls_back_to_cpu_with_a_warning(self):
        from unittest.mock import patch
        import onnxruntime as ort
        model = Path(__file__).resolve().parents[2] / 'models/lama/lama_fp32.onnx'
        if not model.is_file():
            self.skipTest('LaMa model not installed')
        _s, provider, warning = open_lama(model, '/no/such/dir')
        self.assertEqual(provider, 'cpu')
        self.assertIn('CPU', warning)
        with patch.object(ort, 'get_available_providers', return_value=['CPUExecutionProvider']):
            _s, provider, warning = open_lama(model, None)
        self.assertEqual(provider, 'cpu')
        self.assertIn('onnxruntime-gpu', warning)


class _Failing(_FakeLama):
    def __init__(self, error):
        super().__init__()
        self.error = error

    def run(self, _outputs, feeds):
        raise self.error


@unittest.skipUnless(cv2 is not None, "cv2 not available")
class LamaFallbackTest(unittest.TestCase):
    def setUp(self):
        self.model = Path(__file__).resolve().parents[2] / 'models/lama/lama_fp32.onnx'

    def test_missing_onnxruntime_means_smooth_fill_with_a_warning(self):
        import sys
        from unittest.mock import patch
        with patch.dict(sys.modules, {'onnxruntime': None}):
            session, provider, warning = open_lama('whatever.onnx', None)
        self.assertEqual((session, provider), (None, None))
        self.assertIn('smooth', warning)

    def test_unopenable_model_means_smooth_fill_with_a_warning(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / 'bad.onnx'
            bad.write_bytes(b'not an onnx model')
            session, provider, warning = open_lama(bad, None)
        self.assertEqual((session, provider), (None, None))
        self.assertIn('cannot be opened', warning)

    def test_session_open_failure_is_mocked_too(self):
        from unittest.mock import patch
        import onnxruntime as ort
        with patch.object(ort, 'InferenceSession', side_effect=RuntimeError('boom')):
            session, provider, warning = open_lama('x.onnx', None)
        self.assertIsNone(session)
        self.assertIn('boom', warning)

    def test_cuda_run_failure_is_retried_on_a_lazily_created_cpu_session(self):
        from unittest.mock import patch
        import onnxruntime as ort
        from dubflow.subtitle_erase import LamaSession
        cpu = _FakeLama()
        wrapper = LamaSession(_Failing(RuntimeError('CUDA out of memory')), 'cuda', 'm.onnx')
        self.assertIsNone(wrapper.cpu)
        with patch.object(ort, 'InferenceSession', return_value=cpu) as make:
            img = np.full((100, 200, 3), 180, np.uint8)
            mask = np.zeros((100, 200), bool)
            mask[40:60, 50:150] = True
            out = lama_inpaint(wrapper, img, mask)
            lama_inpaint(wrapper, img, mask)
        self.assertEqual(make.call_count, 1)  # created once, lazily
        self.assertEqual(len(cpu.calls), 2)
        self.assertTrue((out[mask] == 100).all())
        self.assertTrue(wrapper.events and 'out of memory' in wrapper.events[0])

    def test_after_one_cuda_failure_the_rest_of_the_run_stays_on_cpu(self):
        from unittest.mock import patch
        import onnxruntime as ort
        from dubflow.subtitle_erase import LamaSession
        failing = _Failing(RuntimeError('oom'))
        runs = []
        original = failing.run
        failing.run = lambda *a: (runs.append(1), original(*a))[1]
        wrapper = LamaSession(failing, 'cuda', 'm.onnx')
        cpu = _FakeLama()
        feeds = {'image': np.zeros((1, 3, LAMA_SIZE, LAMA_SIZE), np.float32), 'mask': np.zeros((1, 1, LAMA_SIZE, LAMA_SIZE), np.float32)}
        with patch.object(ort, 'InferenceSession', return_value=cpu):
            for _ in range(20):
                wrapper.run(None, feeds)
        self.assertEqual(len(runs), 1)  # CUDA tried once only
        self.assertEqual(len(cpu.calls), 20)
        self.assertEqual((len(wrapper.events), wrapper.event_count), (1, 1))
        wrapper.events, wrapper.event_count = [], 0
        for i in range(10):
            wrapper._note(str(i))
        self.assertEqual((len(wrapper.events), wrapper.event_count), (3, 10))  # capped list plus a count

    def test_cpu_run_failure_gives_smooth_fill_for_that_frame(self):
        frame, _clean, _text = _shadowed(_bg())
        h, w = frame.shape[:2]
        mask = glyph_mask(_gray(frame), 1.0)
        style = {}
        out, how, _ = erase_frame(frame, mask, (0, 0, w, h), [], (0, h), 1.0, style=style,
                                  lama=_Failing(RuntimeError('cpu failed too')), reuse_tol=0)
        self.assertEqual(how, 'smooth')
        self.assertEqual(style['lama_failed'], 1)
        self.assertEqual((_gray(out)[_text] > 200).sum(), 0)

    def test_pipeline_defaults_match_the_erase_constants(self):
        from dubflow.pipeline import ERASE_KNOBS
        from dubflow.subtitle_erase import LAMA_REUSE_TOL, STATIC_TOL
        self.assertEqual((ERASE_KNOBS['erase_static_tol'], ERASE_KNOBS['lama_reuse_tol']), (STATIC_TOL, LAMA_REUSE_TOL))


@unittest.skipUnless(cv2 is not None, "cv2 not available")
class ActiveSegmentsTest(unittest.TestCase):
    def test_long_segment_does_not_keep_ended_segments_active(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dubflow'))
        from engine_cli import active_segments
        segs = [dict(s=0.0, e=600.0)] + [dict(s=10.0 * i, e=10.0 * i + 2) for i in range(1, 50)]
        for t in (5.0, 123.4, 300.0, 489.9):
            active, upcoming = active_segments(segs, 0, t, 0.25)  # first stays 0: the long segment never ends
            self.assertTrue(all(s['s'] - 0.25 <= t < s['e'] + 0.25 for s in active))
            self.assertLessEqual(len(active), 2)  # the long one plus at most the current short one
            self.assertIn(segs[0], active)
            self.assertTrue(upcoming is None or upcoming - 0.25 > t)
        active, upcoming = active_segments(segs, 0, 121.0, 0.25)
        self.assertEqual([s['s'] for s in active], [0.0, 120.0])
        self.assertEqual(upcoming, 130.0)

    def test_overlapping_segments_stay_active_until_each_ends(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dubflow'))
        from engine_cli import active_segments
        segs = [dict(s=0.0, e=5.0), dict(s=1.0, e=2.0), dict(s=1.5, e=8.0)]
        self.assertEqual(len(active_segments(segs, 0, 1.7, 0.25)[0]), 3)
        self.assertEqual([s['e'] for s in active_segments(segs, 0, 3.0, 0.25)[0]], [5.0, 8.0])


@unittest.skipUnless(cv2 is not None, "cv2 not available")
class EraseStageTest(unittest.TestCase):
    def _run(self, duration, tmp, audio=2, expected=None):
        import json, shutil, subprocess, sys
        from pathlib import Path
        import os
        ff = os.getenv('DUBFLOW_FFMPEG') or shutil.which('ffmpeg')
        if not ff:
            try:
                from dubflow.config import Settings
                ff = Settings().ffmpeg  # same resolution as the backend settings
            except Exception:
                ff = None
        if not ff or not (Path(ff).exists() or shutil.which(ff)):
            self.skipTest('ffmpeg unavailable')
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dubflow'))
        import engine_cli
        d = Path(tmp)
        src = d / 'source.mp4'
        subprocess.run([ff, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=gray:s=320x240:r=25:d=2', '-f', 'lavfi', '-i', f'sine=d={audio}',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(src)], check=True)
        (d / 'subtrack.json').write_text(json.dumps(dict(version=1, fps=10, band=[170, 220],
            segments=[dict(s=.5, e=1.2, x0=60, y0=180, x1=260, y1=210, text='a')])))
        req = dict(ffmpeg=ff, source=str(src), width=320, height=240, fps_arg='25', duration=duration,
                   source_hash='h', subtrack_hash='s', source_size=1, source_mtime_ns=2)
        if expected:
            req['expected_frames'] = expected
        engine_cli.erase(d, req)
        return d

    def test_complete_decode_writes_clean_mp4_with_audio(self):
        import json, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            d = self._run(2.0, tmp)
            self.assertTrue((d / 'clean.mp4').is_file())
            done = json.loads((d / 'erase.json').read_text())
            self.assertEqual(done['version'], 5)
            self.assertEqual((done['fill'], done['provider']), ('smooth', None))
            self.assertFalse(done['lama'])  # no model configured: smooth fallback and a warning
            self.assertTrue(any('LaMa' in w for w in done['warnings']))
            self.assertFalse((d / 'clean.tmp.mp4').exists())
            self.assertFalse((d / 'erase-refs').exists())
            stamp = json.loads((d / 'erase.json').read_text())
            self.assertEqual((stamp['version'], stamp['fps']), (5, '25'))

    def test_audio_longer_than_video_is_not_truncation(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            # container duration is 3 s (audio) but the video stream has 50 frames; expected comes from the video stream
            d = self._run(3.0, tmp, audio=3, expected=50)
            self.assertTrue((d / 'clean.mp4').is_file())

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
