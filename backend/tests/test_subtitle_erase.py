import unittest
from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError:  # backend venv has no cv2
    cv2 = None
if cv2 is not None:
    from dubflow.subtitle_erase import (LAMA_SIZE, SHADOW_AMAX, SHADOW_TAU, _ring_of, erase_frame, estimate_shadow,
                                        bright_strokes, fill_weak_cells, glyph_mask, lama_inpaint, open_lama, shadow_field)
    from dubflow.subtitle_erase import LamaBatch, LamaJobs, Pending


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
            self.assertEqual(done['version'], 9)
            self.assertEqual((done['static_hash'], done['static_ids']), ('', []))
            self.assertEqual((done['fill'], done['provider']), ('smooth', None))
            self.assertFalse(done['lama'])  # no model configured: smooth fallback and a warning
            self.assertTrue(any('LaMa' in w for w in done['warnings']))
            self.assertFalse((d / 'clean.tmp.mp4').exists())
            self.assertFalse((d / 'erase-refs').exists())
            stamp = json.loads((d / 'erase.json').read_text())
            self.assertEqual((stamp['version'], stamp['fps']), (9, '25'))

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


@unittest.skipUnless(cv2 is not None, "cv2 not available")
class StaticEraseStageTest(unittest.TestCase):
    """erase() on a synthetic clip: a red box drawn all the time on grey is erased only inside its region and time range."""
    W, H, FPS = 320, 240, 25

    def _ff(self):
        import os, shutil
        ff = os.getenv('DUBFLOW_FFMPEG') or shutil.which('ffmpeg')
        if not ff:
            try:
                from dubflow.config import Settings
                ff = Settings().ffmpeg
            except Exception:
                ff = None
        if not ff or not (Path(ff).exists() or shutil.which(ff)):
            self.skipTest('ffmpeg unavailable')
        return ff

    def _frames(self, ff, path):
        import subprocess
        import numpy as np
        raw = subprocess.run([ff, '-v', 'error', '-i', str(path), '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'], check=True, capture_output=True).stdout
        size = self.W * self.H * 3
        return np.frombuffer(raw, np.uint8).reshape(-1, self.H, self.W, 3)

    def _erase(self, tmp, statics, segments=(), drawn=(100, 60, 60, 40)):
        import json, subprocess, sys
        ff = self._ff()
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dubflow'))
        import engine_cli
        d = Path(tmp)
        x, y, w, h = drawn
        src = d / 'source.mp4'
        subprocess.run([ff, '-v', 'error', '-y', '-f', 'lavfi', '-i', f'color=c=0x808080:s={self.W}x{self.H}:r={self.FPS}:d=2',
                        '-vf', f'drawbox=x={x}:y={y}:w={w}:h={h}:color=red:t=fill', '-c:v', 'libx264', '-crf', '12', '-pix_fmt', 'yuv420p', str(src)], check=True)
        (d / 'subtrack.json').write_text(json.dumps(dict(version=1, fps=10, band=[170, 220], segments=list(segments))))
        req = dict(ffmpeg=ff, source=str(src), width=self.W, height=self.H, fps_arg=str(self.FPS), duration=2.0, static_regions=statics,
                   static_hash='sh', source_hash='h', subtrack_hash='s', source_size=1, source_mtime_ns=2)
        engine_cli.erase(d, req)
        return ff, d

    def test_static_box_is_erased_only_inside_its_region_and_time_range(self):
        import json, tempfile
        import numpy as np
        region = dict(id='logo', x=92, y=52, width=76, height=56, start=0.5, end=1.5)
        with tempfile.TemporaryDirectory() as tmp:
            ff, d = self._erase(tmp, [region])  # no subtitle segments at all: clean.mp4 is still produced
            self.assertTrue((d / 'clean.mp4').is_file())
            done = json.loads((d / 'erase.json').read_text())
            self.assertEqual((done['version'], done['static_hash'], done['static_ids']), (9, 'sh', ['logo']))
            self.assertEqual(done['frames_touched'], 0)
            self.assertEqual(done['static_frames'], 25)  # 0.5 s .. 1.5 s at 25 fps
            frames = self._frames(ff, d / 'clean.mp4')
            self.assertEqual(len(frames), 50)
            box = (slice(60, 100), slice(100, 160))  # the red rectangle, inside the region
            red = lambda f: float(f[box][..., 2].mean() - f[box][..., 1].mean())  # R - G: 0 on grey
            self.assertGreater(red(frames[5]), 80)    # t = 0.2 s: before the range, untouched
            self.assertGreater(red(frames[45]), 80)   # t = 1.8 s: after the range, untouched
            for i in (13, 25, 37):                    # inside the range: the box is gone
                self.assertLess(red(frames[i]), 12, i)
            grey = frames[25].astype(int)
            far = np.ones((self.H, self.W), bool)
            far[52 - 6:108 + 6, 92 - 6:168 + 6] = False  # everything farther than 6 px from the region
            self.assertLess(float(np.abs(grey[far] - 128).max()), 6)  # nothing outside the region changed (codec noise only)

    def test_static_box_and_subtitle_erase_in_one_clip(self):
        import tempfile
        seg = dict(s=.5, e=1.2, x0=60, y0=180, x1=260, y1=210, text='a')
        region = dict(id='logo', x=92, y=52, width=76, height=56, start=0, end=2)
        with tempfile.TemporaryDirectory() as tmp:
            ff, d = self._erase(tmp, [region], segments=[seg])
            frames = self._frames(ff, d / 'clean.mp4')
            self.assertLess(float(frames[20][60:100, 100:160, 2].mean() - frames[20][60:100, 100:160, 1].mean()), 12)

    def test_clusters_are_transitive_fast_and_computed_once_per_live_set(self):
        import sys, time
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dubflow'))
        import engine_cli
        from engine_cli import erase_static_boxes, static_clusters
        # a chain that only touches pairwise, and a box that joins two groups only through their bounding boxes
        self.assertEqual(static_clusters([(0, 0, 10, 10), (12, 0, 22, 10), (24, 0, 34, 10)], 2), [[0, 1, 2]])
        self.assertEqual(static_clusters([(0, 0, 100, 10), (0, 40, 100, 50), (40, 20, 60, 30)], 6), [[0, 1, 2]])
        boxes = [(i * 3, (i % 7) * 40, i * 3 + 40, (i % 7) * 40 + 20) for i in range(600)]
        started = time.monotonic()
        groups = static_clusters(boxes, 10)
        self.assertLess(time.monotonic() - started, 2.0)  # the restart-from-scratch version was cubic
        self.assertEqual(sorted(i for g in groups for i in g), list(range(600)))
        import numpy as np
        frame = np.full((240, 320, 3), 128, np.uint8)
        calls, real = [], engine_cli.static_clusters
        engine_cli.static_clusters = lambda b, m: (calls.append(1), real(b, m))[1]
        try:
            cache, styles = {}, {}
            for _ in range(5):
                erase_static_boxes(frame, [(10, 10, 50, 30)], 1.0, None, 6.0, 2.5, styles, cache)
            erase_static_boxes(frame, [(10, 10, 50, 30), (200, 100, 240, 130)], 1.0, None, 6.0, 2.5, styles, cache)
            erase_static_boxes(frame, [(10, 10, 50, 30)], 1.0, None, 6.0, 2.5, styles, cache)
        finally:
            engine_cli.static_clusters = real
        self.assertEqual(len(calls), 2)  # one per distinct live set

    def test_box_group_helpers(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dubflow'))
        from engine_cli import clean_static_regions, static_clusters
        self.assertEqual(static_clusters([(0, 0, 10, 10), (12, 0, 20, 10), (200, 200, 220, 220)], 4), [[0, 1], [2]])
        self.assertEqual(static_clusters([(0, 0, 10, 10), (200, 0, 210, 10)], 4), [[0], [1]])
        rows = clean_static_regions(dict(static_regions=[dict(id='a', x=-5, y=10, width=30, height=20, start=0, end=1),
                                                         dict(id='bad', x=1, y=1, width=0, height=5, end=1),
                                                         dict(id='late', x=1, y=1, width=5, height=5, start=2, end=1),
                                                         dict(id='out', x=500, y=1, width=5, height=5, end=1)]), 320, 240)
        self.assertEqual([(r['id'], r['x0'], r['x1']) for r in rows], [('a', 0, 25)])


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(cv2 is not None, "cv2 not available")
class BandEraseStageTest(unittest.TestCase):
    """The user drew the band: erase only inside it, through the whole window of a line, also on frames the detector misses."""
    W, H, FPS = 1280, 720, 25
    BAND = (160, 620, 960, 80)  # x y w h

    def _clip(self, tmp):
        """Grey picture; the text is white with a dark outline from 0.6 s to 1.8 s, except 1.0-1.2 s where it is dim
        (no white pixel, no outline: the glyph detector sees nothing). A white blob outside the band stays all the time."""
        import os, shutil, subprocess, sys
        ff = os.getenv('DUBFLOW_FFMPEG') or shutil.which('ffmpeg')
        if not ff:
            try:
                from dubflow.config import Settings
                ff = Settings().ffmpeg
            except Exception:
                ff = None
        if not ff or not (Path(ff).exists() or shutil.which(ff)):
            self.skipTest('ffmpeg unavailable')
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dubflow'))
        d = Path(tmp)
        raw = d / 'raw.bin'
        with raw.open('wb') as out:
            for n in range(int(2.5 * self.FPS)):
                t = n / self.FPS
                img = np.full((self.H, self.W), 120, np.uint8)
                cv2.circle(img, (640, 150), 30, 255, -1)  # outside the band
                if .6 <= t < 1.8:
                    glyph = np.zeros(img.shape, np.uint8)
                    cv2.putText(glyph, 'SUB 88', (300, 680), cv2.FONT_HERSHEY_SIMPLEX, 2.0, 255, 3, cv2.LINE_8)
                    if 1.0 <= t < 1.2:
                        img[glyph > 0] = 150
                    else:
                        img[cv2.dilate(glyph, np.ones((5, 5), np.uint8)) > 0] = 0
                        img[glyph > 0] = 255
                out.write(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR).tobytes())
        src = d / 'source.mp4'
        subprocess.run([ff, '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{self.W}x{self.H}', '-r', str(self.FPS), '-i', str(raw),
                        '-c:v', 'libx264', '-crf', '10', '-pix_fmt', 'yuv420p', str(src)], check=True)
        raw.unlink()
        return ff, src

    def _frames(self, ff, path):
        import subprocess
        raw = subprocess.run([ff, '-v', 'error', '-i', str(path), '-f', 'rawvideo', '-pix_fmt', 'gray', '-'], check=True, capture_output=True).stdout
        return np.frombuffer(raw, np.uint8).reshape(-1, self.H, self.W)

    def _erase(self, tmp, lines):
        import json
        ff, src = self._clip(tmp)
        import engine_cli
        d = Path(tmp)
        x, y, w, h = self.BAND
        (d / 'subtrack.json').write_text(json.dumps(dict(version=2, mode='band', box=list(self.BAND), band=[y, y + h], segments=lines)))
        engine_cli.erase(d, dict(ffmpeg=ff, source=str(src), width=self.W, height=self.H, fps_arg=str(self.FPS), duration=2.5,
                                 source_hash='h', subtrack_hash='s', source_size=1, source_mtime_ns=2))
        return ff, src, d

    def test_the_whole_line_is_erased_on_every_frame_of_its_window_and_nothing_else(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            # two readings of the same sentence 0.2 s apart: the windows are bridged, the dim frames in between are erased too
            ff, src, d = self._erase(tmp, [dict(s=.6, e=1.2, x0=300, y0=630, x1=560, y1=690, text='a'), dict(s=1.4, e=1.8, x0=300, y0=630, x1=560, y1=690, text='b')])
            done = json.loads((d / 'erase.json').read_text())
            self.assertEqual((done['version'], done['windows']), (9, 2))
            before, after = self._frames(ff, src), self._frames(ff, d / 'clean.mp4')
            text = (slice(630, 700), slice(290, 580))
            for n in range(int(.6 * self.FPS), int(1.8 * self.FPS)):
                self.assertLess(int(after[n][text].max()), 150, f'frame {n} (t={n / self.FPS:.2f}) still shows the text')
            self.assertGreater(int(before[27][text].max()), 140)  # the dim text really was there
            self.assertGreater(int(before[20][text].max()), 250)
            for n in (5, 60):  # outside every window the picture is not touched (codec noise only)
                self.assertLess(float(np.abs(after[n].astype(int) - before[n].astype(int)).mean()), 3, n)
            blob = (slice(120, 180), slice(610, 670))  # outside the band: never changed, also inside the window
            self.assertGreater(int(after[20][blob].max()), 240)

    def test_nothing_outside_the_drawn_band_is_touched_inside_a_window(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            ff, src, d = self._erase(tmp, [dict(s=.6, e=1.8, x0=300, y0=630, x1=560, y1=690, text='a')])
            before, after = self._frames(ff, src), self._frames(ff, d / 'clean.mp4')
            x, y, w, h = self.BAND
            outside = np.ones((self.H, self.W), bool)
            outside[y - 30:y + h + 30, x - 30:x + w + 30] = False  # the band and the context LaMa may look at
            self.assertLess(float(np.abs(after[20].astype(int) - before[20].astype(int))[outside].mean()), 3)


@unittest.skipUnless(cv2 is not None, "cv2 not available")
class SubbandStageTest(unittest.TestCase):
    """subband() on a synthetic clip: OCR of the band only, one line per displayed subtitle."""
    W, H, FPS = 640, 360, 10

    def test_one_segment_per_displayed_line_with_its_first_and_last_frame(self):
        import json, os, shutil, subprocess, sys, tempfile
        try:
            import rapidocr_onnxruntime  # noqa: F401
        except ImportError:
            self.skipTest('rapidocr unavailable')
        ff = os.getenv('DUBFLOW_FFMPEG') or shutil.which('ffmpeg')
        if not ff:
            try:
                from dubflow.config import Settings
                ff = Settings().ffmpeg
            except Exception:
                ff = None
        if not ff or not (Path(ff).exists() or shutil.which(ff)):
            self.skipTest('ffmpeg unavailable')
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dubflow'))
        import engine_cli
        shows = [(1.0, 3.0, 'HELLO WORLD'), (3.0, 4.6, 'GOOD MORNING')]  # the second line replaces the first at once
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            raw = d / 'raw.bin'
            with raw.open('wb') as out:
                for n in range(int(6 * self.FPS)):
                    t = n / self.FPS
                    img = np.full((self.H, self.W, 3), 110, np.uint8)
                    text = next((x for a, b, x in shows if a <= t < b), None)
                    if text:
                        cv2.putText(img, text, (150, 330), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (0, 0, 0), 6, cv2.LINE_AA)
                        cv2.putText(img, text, (150, 330), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (255, 255, 255), 2, cv2.LINE_AA)
                    out.write(img.tobytes())
            src = d / 'source.mp4'
            subprocess.run([ff, '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{self.W}x{self.H}', '-r', str(self.FPS), '-i', str(raw),
                            '-c:v', 'libx264', '-crf', '10', '-pix_fmt', 'yuv420p', str(src)], check=True)
            engine_cli.subband(d, dict(ffmpeg=ff, source=str(src), width=self.W, height=self.H, duration=6.0, box=[100, 285, 460, 60]))
            track = json.loads((d / 'subtrack.json').read_text())
            self.assertEqual((track['version'], track['box']), (2, [100, 285, 460, 60]))
            lines = track['segments']
            self.assertEqual([l['text'].replace(' ', '').upper() for l in lines], ['HELLOWORLD', 'GOODMORNING'])
            for line, (a, b, _) in zip(lines, shows):
                self.assertLessEqual(abs(line['s'] - a), .3, line)
                self.assertLessEqual(abs(line['e'] - b), .3, line)
                self.assertTrue(100 <= line['x0'] < line['x1'] <= 560 and 285 <= line['y0'] < line['y1'] <= 345, line)
            self.assertLess(track['ocr_reads'], 6 * 5)  # sampled at 2.5 fps plus the frames at the edges, not every frame


@unittest.skipUnless(cv2 is not None, "cv2 not available")
class ConfinedEraseTest(unittest.TestCase):
    """The drawn box is the only area that may change: glyph pixels at its edge, the stroke growth, the shadow zone and the
    feathered model output must not reach a pixel outside it, in every fill path (reviewer finding: 13 pixels leaked)."""

    def _case(self):
        frame, clean, _text = _shadowed(_bg())
        h, w = frame.shape[:2]
        mask = glyph_mask(_gray(frame), 1.0)
        ys, xs = np.nonzero(mask)
        box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)  # glyph pixels touch every side of it
        outside = np.ones((h, w), bool)
        outside[box[1]:box[3], box[0]:box[2]] = False
        return frame, clean, mask, box, outside, h

    def test_without_confine_the_repair_reaches_beyond_the_box(self):
        frame, _clean, mask, box, outside, h = self._case()
        out, how, _ = erase_frame(frame, mask, box, [], (0, h), 1.0, lama=_FakeLama(), reuse_tol=0)
        self.assertEqual(how, 'lama')
        self.assertTrue((out != frame).any(axis=2)[outside].any())

    def test_every_fill_path_leaves_the_pixels_outside_the_box_exactly_as_they_were(self):
        frame, clean, mask, box, outside, h = self._case()
        wide = (max(0, box[0] - 14), max(0, box[1] - 14), box[2] + 14, box[3] + 14)  # a clean reference only matches with the shadow inside the box
        for refs, lama, edge, want in (([], _FakeLama(), box, 'lama'), ([clean], None, wide, 'ref'), ([], None, box, 'smooth')):
            out_of = np.ones_like(outside)
            out_of[edge[1]:edge[3], edge[0]:edge[2]] = False
            out, how, _ = erase_frame(frame, mask, edge, refs, (0, h), 1.0, style={}, lama=lama, reuse_tol=0, confine=True)
            self.assertEqual(how, want)
            self.assertTrue(np.array_equal(out[out_of], frame[out_of]), want)
            self.assertTrue((out != frame).any(), want)  # and the inside did change
        fake, style = _FakeLama(), {}
        out, how, _ = erase_frame(frame, mask, box, [], (0, h), 1.0, style=style, lama=fake, reuse_tol=4.5, confine=True)
        out2, how2, _ = erase_frame(frame, mask, box, [], (0, h), 1.0, style=style, lama=fake, reuse_tol=4.5, confine=True)
        self.assertEqual((how, how2), ('lama', 'lamaref'))
        for o in (out, out2):
            self.assertTrue(np.array_equal(o[outside], frame[outside]))

    def test_the_mask_handed_to_the_model_stays_inside_the_box_and_rows_outside_the_band_are_untouched(self):
        import dubflow.subtitle_erase as module
        frame, _clean, mask, box, outside, h = self._case()
        seen, real = [], module.lama_inpaint

        def spy(session, image, hole, scale=1.0, feather=1.2):
            seen.append(int(hole[outside].sum()))
            return real(session, image, hole, scale, feather)
        module.lama_inpaint = spy
        try:
            band = (box[1] - 3, box[3] + 3)
            out, how, _ = erase_frame(frame, mask, box, [], band, 1.0, lama=_FakeLama(), reuse_tol=0, confine=True)
        finally:
            module.lama_inpaint = real
        self.assertEqual((how, seen), ('lama', [0]))
        self.assertTrue(np.array_equal(out[:band[0]], frame[:band[0]]) and np.array_equal(out[band[1]:], frame[band[1]:]))

    def test_a_rigid_box_changes_nothing_outside_its_own_pixels(self):
        frame = _shadowed(_bg())[0]
        h, w = frame.shape[:2]
        mask = np.zeros((h, w), bool)
        mask[40:70, 100:220] = True
        out, how, _ = erase_frame(frame, mask, (0, 0, w, h), [], (0, h), 1.0, style={}, lama=_FakeLama(), reuse_tol=0, rigid=True, confine=True)
        self.assertEqual(how, 'lama')
        self.assertTrue(np.array_equal(out[~mask], frame[~mask]))


def _ffmpeg_or_skip(case):
    import os, shutil, sys
    ff = os.getenv('DUBFLOW_FFMPEG') or shutil.which('ffmpeg')
    if not ff:
        try:
            from dubflow.config import Settings
            ff = Settings().ffmpeg
        except Exception:
            ff = None
    if not ff or not (Path(ff).exists() or shutil.which(ff)):
        case.skipTest('ffmpeg unavailable')
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dubflow'))
    return ff


@unittest.skipUnless(cv2 is not None, "cv2 not available")
class OddBandGeometryTest(unittest.TestCase):
    """A box with odd size / position on a yuv420p video: every pass must decode exactly the pixels of the drawn box
    (ffmpeg's crop rounds such a box down to even numbers unless exact=1, which shifted every following byte)."""
    W, H, FPS = 128, 96, 10
    BOX = [7, 21, 101, 31]  # x y w h, all odd

    def _clip(self, tmp, ff, shows):
        """Black picture; a bright block fills the whole box while a line is shown (frame ranges in `shows`); yuv420p."""
        import subprocess
        frames = np.zeros((10, self.H, self.W, 3), np.uint8)
        x, y, w, h = self.BOX
        for a, b in shows:
            frames[a:b, y:y + h, x:x + w] = 255
        src = Path(tmp) / 'source.mp4'
        subprocess.run([ff, '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{self.W}x{self.H}', '-r', str(self.FPS), '-i', '-',
                        '-c:v', 'libx264', '-crf', '0', '-pix_fmt', 'yuv420p', str(src)], input=frames.tobytes(), check=True)
        return src

    def test_an_odd_crop_decodes_exactly_the_boxed_bytes_and_the_stages_ask_for_it(self):
        import subprocess, tempfile
        ff = _ffmpeg_or_skip(self)
        import engine_cli
        with tempfile.TemporaryDirectory() as tmp:
            src = self._clip(tmp, ff, [(2, 4)])
            x, y, w, h = self.BOX
            raw = subprocess.run([ff, '-v', 'error', '-i', str(src), '-vf', f'fps=5,crop={w}:{h}:{x}:{y}:exact=1', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'],
                                 capture_output=True, check=True).stdout
            self.assertEqual(len(raw), 5 * w * h * 3)
            raw = subprocess.run([ff, '-v', 'error', '-i', str(src), '-vf', f'fps=5,crop={w}:{h}:{x}:{y}:exact=1,format=gray', '-f', 'rawvideo', '-'],
                                 capture_output=True, check=True).stdout
            self.assertEqual(len(raw), 5 * w * h)
        text = Path(engine_cli.__file__).read_text(encoding='utf-8')
        self.assertEqual(text.count('crop='), text.count(':exact=1'))  # subband, footprints, refs scan, legacy ocr

    def test_subband_hands_the_reader_boxed_frames_of_the_declared_size_and_position(self):
        import json, tempfile
        ff = _ffmpeg_or_skip(self)
        try:
            import rapidocr_onnxruntime  # noqa: F401
        except ImportError:
            self.skipTest('rapidocr unavailable')
        import engine_cli
        from unittest.mock import patch
        shapes, means = [], []

        class Reader:
            def __init__(self, **kwargs):
                pass

            def __call__(self, image, **kwargs):
                shapes.append(image.shape)
                means.append(float(image.mean()))
                return ([([[2, 2], [90, 2], [90, 25], [2, 25]], '快跑快跑', .99)], None) if image.mean() > 100 else ([], None)
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            src = self._clip(tmp, ff, [(0, 6)])  # shown from 0 to 0.6 s
            with patch('rapidocr_onnxruntime.RapidOCR', Reader):
                engine_cli.subband(d, dict(ffmpeg=ff, source=str(src), width=self.W, height=self.H, duration=1.0, box=self.BOX))
            track = json.loads((d / 'subtrack.json').read_text(encoding='utf-8'))
        x, y, w, h = self.BOX
        self.assertEqual(set(shapes), {(h, w, 3)})
        self.assertTrue(all(m > 240 or m < 1 for m in means), means)  # the box is wholly bright or wholly dark: a shifted crop shows a mix
        self.assertEqual(len(track['segments']), 1)
        seg = track['segments'][0]
        self.assertLess(seg['s'], .15)
        self.assertTrue(x <= seg['x0'] and seg['x1'] <= x + w and y <= seg['y0'] and seg['y1'] <= y + h, seg)

    def test_a_subtitle_that_shows_only_between_two_samples_is_read(self):
        """The frame between two samples (0.2 s from each) is read when it differs from both, also when both are empty."""
        import json, tempfile
        ff = _ffmpeg_or_skip(self)
        try:
            import rapidocr_onnxruntime  # noqa: F401
        except ImportError:
            self.skipTest('rapidocr unavailable')
        import engine_cli
        from unittest.mock import patch
        reads = []

        class Reader:
            def __init__(self, **kwargs):
                pass

            def __call__(self, image, **kwargs):
                reads.append(float(image.mean()))
                return ([([[0, 0], [99, 0], [99, 29], [0, 29]], '快跑', .99)], None) if image.mean() > 100 else ([], None)
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            src = self._clip(tmp, ff, [(2, 4)])  # 0.2-0.4 s: at 5 fps only the 0.2 s frame shows it, and that is not a sample
            with patch('rapidocr_onnxruntime.RapidOCR', Reader):
                engine_cli.subband(d, dict(ffmpeg=ff, source=str(src), width=self.W, height=self.H, duration=1.0, box=self.BOX))
            track = json.loads((d / 'subtrack.json').read_text(encoding='utf-8'))
        self.assertTrue(any(m > 100 for m in reads), reads)
        self.assertEqual([s['text'] for s in track['segments']], ['快跑'], track)
        seg = track['segments'][0]
        self.assertTrue(.0 <= seg['s'] <= .3 and .2 <= seg['e'] <= .5, seg)


@unittest.skipUnless(cv2 is not None, "cv2 not available")
class OddBandEraseStageTest(BandEraseStageTest):
    """The band stage tests again with a drawn band that has odd size and position (yuv420p source)."""
    BAND = (161, 621, 959, 79)

    def test_erase_json_records_the_text_box_pass(self):
        import json, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            _ff, _src, d = self._erase(tmp, [dict(s=.6, e=1.8, x0=300, y0=630, x1=560, y1=690, text='a')])
            done = json.loads((d / 'erase.json').read_text())
            self.assertGreater(done['frames_touched'], 20)
            self.assertIn('text_box_frames', done)


@unittest.skipUnless(cv2 is not None, "cv2 not available")
class WeakCellTest(unittest.TestCase):
    """White text on a bright patch: some characters found, others not. The share of the whole box looks fine, so the whole
    box is not masked; the characters the detector missed are filled cell by cell (the residue at 80 s / 90 s of test2)."""

    @staticmethod
    def part(found):
        part = np.zeros((40, 400), bool)
        for i in range(10):  # ten character cells of the 40 px box height
            if i in found:
                part[8:32:2, i * 40 + 6:i * 40 + 34] = True  # strokes: about 25% of the cell
        return part

    def test_cells_without_strokes_are_filled_whole_and_good_cells_are_left_alone(self):
        part = self.part({0, 1, 2, 5, 6, 7, 8, 9})  # cells 3 and 4 missed
        before = part.copy()
        self.assertEqual(fill_weak_cells(part, (0, 0, 400, 40)), 2)
        self.assertTrue(part[:, 120:200].all())
        self.assertTrue((part[:, :120] == before[:, :120]).all() and (part[:, 200:] == before[:, 200:]).all())

    def test_a_complete_detection_changes_nothing(self):
        part = self.part(set(range(10)))
        before = part.copy()
        self.assertEqual(fill_weak_cells(part, (0, 0, 400, 40)), 0)
        self.assertTrue((part == before).all())

    def test_a_line_found_nowhere_is_left_to_the_whole_box_rule(self):
        part = self.part(set())
        self.assertEqual(fill_weak_cells(part, (0, 0, 400, 40)), 0)
        self.assertFalse(part.any())

    def test_a_few_dense_cells_among_missed_ones_still_fill_the_rest(self):
        # a bright patch hid most characters (found: 3 of 10), the whole-box share is above the whole-box limit
        part = self.part({4, 5, 6})
        part[:, 160:280] = True  # dense on the characters that were found
        self.assertEqual(fill_weak_cells(part, (0, 0, 400, 40)), 7)
        self.assertTrue(part.all())


@unittest.skipUnless(cv2 is not None, "cv2 not available")
class BrightStrokesTest(unittest.TestCase):
    """White text on a pale patch has no dark outline (glyph_mask finds nothing) but is a few levels brighter than the picture."""

    @staticmethod
    def pale_text():
        gray = np.full((58, 400), 212, np.uint8)
        gray[:, 200:] = 190
        cv2.putText(gray, "TEXT", (30, 42), cv2.FONT_HERSHEY_SIMPLEX, 1.3, 236, 3, cv2.LINE_8)
        return gray

    def test_low_contrast_strokes_are_found_where_the_outline_detector_sees_nothing(self):
        gray = self.pale_text()
        self.assertLess(glyph_mask(gray, 2 / 3).mean(), .003)
        mask = bright_strokes(gray, 2 / 3, (0, 0, 400, 58))
        self.assertGreater(mask[:, 25:150].mean(), .15)
        self.assertLess(mask[:, 200:].mean(), .01)

    def test_only_the_given_box_is_looked_at_and_a_flat_picture_gives_nothing(self):
        gray = self.pale_text()
        mask = bright_strokes(gray, 2 / 3, (150, 0, 400, 58))
        self.assertFalse(mask[:, :150].any())
        self.assertFalse(bright_strokes(np.full((58, 400), 230, np.uint8), 2 / 3, (0, 0, 400, 58)).any())


@unittest.skipUnless(cv2 is not None, "cv2 not available")
class LamaBatchTest(unittest.TestCase):
    """Frames that need the model share its canvases: the same pixels as one call per frame, a fraction of the calls."""

    def _line(self, seed=0):
        img = np.full((140, 400, 3), 150, np.uint8)
        img[:, :, 0] = (np.arange(400) // 4 + seed) % 200
        mask = np.zeros((140, 400), bool)
        mask[50:90, 60:340] = True
        return img, mask

    def test_jobs_share_canvases_and_give_the_single_call_result(self):
        fake = _FakeLama()
        jobs = LamaJobs(fake, .5)
        pairs = [self._line(s) for s in range(4)]
        for img, mask in pairs:
            jobs.add(img, mask)
        outs = jobs.run()
        self.assertEqual(len(fake.calls), 1)  # four 88-row tiles in one 512x512 canvas
        for (img, mask), out in zip(pairs, outs):
            self.assertTrue(np.array_equal(out, lama_inpaint(_FakeLama(), img, mask, .5)))
        self.assertFalse(jobs.ready())  # room for one more line
        jobs.add(*self._line(9))
        self.assertTrue(jobs.ready())  # now another one would not fit

    def test_batched_erase_frame_matches_the_synchronous_result_including_reuse(self):
        frames = [_shadowed(_bg())[0] for _ in range(3)]
        h, w = frames[0].shape[:2]
        mask = glyph_mask(_gray(frames[0]), 1.0)
        sync_style, sync = {}, []
        for f in frames:
            sync.append(erase_frame(f, mask, (0, 0, w, h), [], (0, h), 1.0, style=sync_style, lama=_FakeLama(), reuse_tol=4.5, confine=True))
        fake, style = _FakeLama(), {}
        batch = LamaBatch(fake, 1.0)
        got = [erase_frame(f, mask, (0, 0, w, h), [], (0, h), 1.0, style=style, lama=fake, reuse_tol=4.5, confine=True, batch=batch) for f in frames]
        self.assertTrue(all(isinstance(g[0], Pending) for g in got))  # the first needs the model, the others wait for it
        self.assertEqual([g[1] for g in got], [s[1] for s in sync])
        self.assertEqual(fake.calls, [])
        batch.flush()
        self.assertEqual(len(fake.calls), 1)
        for g, s in zip(got, sync):
            self.assertEqual(g[0].how, s[1])
            self.assertLessEqual(int(np.abs(g[0].out.astype(int) - s[0].astype(int)).max()), 2)
        self.assertTrue(all(k.item is None for k in style['lama_keys']))  # the stand-in keys now hold the real result

    def test_a_failing_model_gives_the_smooth_fill_for_the_waiting_frames(self):
        class Boom(_FakeLama):
            def run(self, *_):
                raise RuntimeError('cuda lost')
        frame = _shadowed(_bg())[0]
        h, w = frame.shape[:2]
        mask = glyph_mask(_gray(frame), 1.0)
        batch, style = LamaBatch(Boom(), 1.0), {}
        item, how, _ = erase_frame(frame, mask, (0, 0, w, h), [], (0, h), 1.0, style=style, lama=batch.session, reuse_tol=0, batch=batch)
        self.assertEqual(how, 'lama')
        batch.flush()
        self.assertEqual(item.how, 'smooth')
        self.assertEqual(style['lama_failed'], 1)
        self.assertEqual(int(((item.out == 255).all(axis=2) & mask).sum()), 0)
