import random
import unittest

try:
    import cv2
    import numpy as np
except ImportError:  # backend venv has no cv2
    cv2 = None
from dubflow.logo_detect import apply_candidates, detect_static, merge_candidates

W, H, SCALE = 320, 180, .5   # downscaled frame; source is 640 x 360


def _background(rng):
    """Smooth random texture that changes every sample (moving scene)."""
    noise = rng.normal(0, 1, (H, W)).astype(np.float32)
    noise = cv2.GaussianBlur(noise, (0, 0), 5)
    noise = noise / noise.std() * 16 + 110
    return np.clip(noise, 0, 255).astype(np.uint8)


def _logo(frame, x=30, y=20):
    cv2.putText(frame, 'LOGO', (x, y + 18), cv2.FONT_HERSHEY_SIMPLEX, .9, 255, 2, cv2.LINE_8)
    return frame


def _sequence(n=40, logo=lambda i: True, seed=1, still=False):
    rng = np.random.default_rng(seed)
    base = _background(rng)
    frames = []
    for i in range(n):
        frame = base.copy() if still else _background(rng)
        if logo(i):
            _logo(frame)
        frames.append(frame)
    return frames, [2. * i for i in range(n)]


@unittest.skipUnless(cv2 is not None, 'cv2 not available')
class DetectStaticTest(unittest.TestCase):
    def test_fixed_logo_on_moving_background(self):
        frames, times = _sequence()
        found = detect_static(frames, times, 80., [], SCALE)
        self.assertEqual(len(found), 1, found)
        r = found[0]
        # LOGO text at small px x 30..~108, y 20..~38  ->  source x 60..~216, y 40..~76
        self.assertAlmostEqual(r['x'], 60 - 6, delta=8)
        self.assertAlmostEqual(r['y'], 40 - 6, delta=12)
        self.assertGreater(r['x'] + r['width'], 190)
        self.assertLess(r['x'] + r['width'], 240)
        self.assertEqual((r['start'], r['end']), (0, 80.))
        self.assertGreaterEqual(r['presence'], .95)

    def test_partial_logo_gets_its_own_time_range(self):
        frames, times = _sequence(logo=lambda i: 10 <= i <= 30)
        found = detect_static(frames, times, 80., [], SCALE)
        self.assertEqual(len(found), 1, found)
        r = found[0]
        self.assertAlmostEqual(r['start'], 19., delta=2.1)
        self.assertAlmostEqual(r['end'], 61., delta=2.1)
        self.assertLess(r['presence'], .8)

    def test_intermittent_pattern_is_one_candidate(self):
        frames, times = _sequence(n=60, logo=lambda i: 2 <= i <= 22 or 30 <= i <= 50)
        found = detect_static(frames, times, 120., [], SCALE)
        self.assertEqual(len(found), 1, found)
        r = found[0]
        self.assertAlmostEqual(r['start'], 3., delta=2.1)
        self.assertAlmostEqual(r['end'], 101., delta=2.1)
        self.assertLess(r['presence'], .8)

    def test_still_shot_is_not_a_logo(self):
        frames, times = _sequence(still=True)
        self.assertEqual(detect_static(frames, times, 80., [], SCALE), [])

    def test_still_shot_with_logo_is_not_a_logo(self):
        frames, times = _sequence(still=True, logo=lambda i: True)
        self.assertEqual(detect_static(frames, times, 80., [], SCALE), [])

    def test_pattern_inside_exclude_box_is_ignored(self):
        frames, times = _sequence()
        self.assertEqual(detect_static(frames, times, 80., [(40, 30, 220, 60)], SCALE), [])
        # an exclude box elsewhere does not hide it
        self.assertEqual(len(detect_static(frames, times, 80., [(400, 200, 100, 100)], SCALE)), 1)

    def test_too_few_samples(self):
        frames, times = _sequence(n=3)
        self.assertEqual(detect_static(frames, times, 6., [], SCALE), [])


def _frag(i, rng, text, x=100, y=50, w=200, h=40):
    return dict(id=f'r{i}', kind='static', x=x + rng.randint(-3, 3), y=y + rng.randint(-3, 3),
                width=w + rng.randint(-4, 4), height=h + rng.randint(-3, 3),
                start=i * .5, end=i * .5 + .6, text=text, translation='', enabled=True)


class MergeTest(unittest.TestCase):
    def test_jittered_fragments_become_one_text_region(self):
        rng = random.Random(3)
        frags = [_frag(i, rng, '予你心动' if i % 3 else '子你心动') for i in range(300)]
        out = merge_candidates([], frags, 150.)
        self.assertEqual(len(out), 1)
        r = out[0]
        self.assertEqual((r['kind'], r['label'], r['text']), ('static', 'Chữ cố định', '予你心动'))
        self.assertTrue(r['auto'] and r['enabled'] and not r['confirmed'])
        self.assertEqual(len(r['merged_ids']), 300)
        self.assertLessEqual(r['x'], 97)
        self.assertGreaterEqual(r['x'] + r['width'], 303)
        self.assertEqual(r['start'], 0)
        self.assertLessEqual(r['end'], 150.)

    def test_detected_logo_without_text_is_a_logo(self):
        out = merge_candidates([dict(x=10, y=10, width=50, height=30, start=0, end=100., presence=.9)], [], 100.)
        self.assertEqual([(r['label'], r['text']) for r in out], [('Logo', '')])

    def test_text_folds_into_overlapping_detected_box(self):
        rng = random.Random(1)
        frags = [_frag(i, rng, '予你心动', x=105, y=55, w=190, h=30) for i in range(50)]
        det = [dict(x=100, y=50, width=200, height=40, start=0, end=150., presence=.95)]
        out = merge_candidates(det, frags, 150.)
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0]['label'], out[0]['text']), ('Chữ cố định', '予你心动'))
        self.assertEqual(len(out[0]['merged_ids']), 50)

    def test_user_owned_fragments_are_not_merged(self):
        rng = random.Random(4)
        frags = [_frag(i, rng, '予你心动') for i in range(20)]
        frags[3]['translation'] = 'Dư tâm động'
        frags[5]['enabled'] = False
        out = merge_candidates([], frags, 100.)
        self.assertEqual(len(out), 1)
        self.assertEqual(len(out[0]['merged_ids']), 18)
        self.assertNotIn('r3', out[0]['merged_ids'])
        self.assertNotIn('r5', out[0]['merged_ids'])

    def test_separate_places_stay_separate(self):
        rng = random.Random(2)
        frags = [_frag(i, rng, 'A') for i in range(10)] + [_frag(100 + i, rng, 'B', x=700, y=400) for i in range(10)]
        self.assertEqual(len(merge_candidates([], frags, 100.)), 2)


class ApplyTest(unittest.TestCase):
    def cand(self, **kw):
        return dict(dict(id='logo-1', kind='static', x=100, y=50, width=200, height=40, start=0, end=100., text='', translation='',
                         enabled=True, auto=True, confirmed=False, label='Logo', merged_ids=[], presence=.9), **kw)

    def reg(self, id, kind='static', **kw):
        return dict(dict(id=id, kind=kind, x=100, y=50, width=200, height=40, start=0, end=100., text='', translation='',
                         enabled=True, auto=False, confirmed=False, label=''), **kw)

    def test_rejected_region_is_kept_and_not_readded(self):
        rejected = self.reg('logo-1', auto=True, confirmed=True, enabled=False)
        out = apply_candidates([rejected], [self.cand(x=104, y=52)])
        self.assertEqual(out, [rejected])

    def test_confirmed_and_drawn_regions_survive(self):
        confirmed = self.reg('a', auto=True, confirmed=True)
        drawn = self.reg('b', x=400, auto=False, confirmed=True)
        out = apply_candidates([confirmed, drawn], [self.cand(x=400, y=300)])
        self.assertEqual([r['id'] for r in out], ['a', 'b', 'logo-1'])

    def test_replaces_unconfirmed_auto_and_merged_fragments_only(self):
        sub = self.reg('s', 'subtitle', y=300)
        old_auto = self.reg('logo-1', auto=True)
        frag = self.reg('r1')
        other_static = self.reg('r2', x=500, y=200)
        trans = self.reg('t', 'transient', x=500, y=200)
        out = apply_candidates([sub, old_auto, frag, other_static, trans], [self.cand(x=10, y=10, width=40, height=20, merged_ids=['r1'])])
        self.assertEqual([r['id'] for r in out], ['s', 'r2', 't', 'logo-1'])
        new = out[-1]
        self.assertNotIn('merged_ids', new)
        self.assertNotIn('presence', new)
        self.assertEqual((new['x'], new['auto'], new['confirmed'], new['enabled']), (10, True, False, True))

    def test_translated_or_disabled_fragments_survive_even_if_listed_as_merged(self):
        translated = self.reg('r1', translation='Bản dịch')
        disabled = self.reg('r2', enabled=False)
        plain = self.reg('r3')
        out = apply_candidates([translated, disabled, plain], [self.cand(x=10, y=10, width=40, height=20, merged_ids=['r1', 'r2', 'r3'])])
        self.assertEqual([r['id'] for r in out], ['r1', 'r2', 'logo-1'])
        self.assertEqual(out[0]['translation'], 'Bản dịch')

    def test_new_ids_do_not_collide(self):
        kept = self.reg('logo-1', auto=True, confirmed=True, x=500, y=300)
        out = apply_candidates([kept], [self.cand(id='logo-1', x=10, y=10, width=40, height=20)])
        self.assertEqual([r['id'] for r in out], ['logo-1', 'logo-2'])

    def test_rerun_is_stable(self):
        first = apply_candidates([self.reg('r1')], [self.cand(merged_ids=['r1'])])
        again = apply_candidates(first, [self.cand()])
        self.assertEqual([(r['id'], r['x']) for r in again], [('logo-1', 100)])


def _ffmpeg(test):
    import os
    import shutil
    from pathlib import Path
    ff = os.getenv('DUBFLOW_FFMPEG') or shutil.which('ffmpeg')
    if not ff:
        try:
            from dubflow.config import Settings
            ff = Settings().ffmpeg
        except Exception:
            ff = None
    if not ff or not (Path(ff).exists() or shutil.which(ff)):
        test.skipTest('ffmpeg unavailable')
    return ff


def _write_video(ff, path, seed):
    import subprocess
    rng = np.random.default_rng(seed)
    enc = subprocess.Popen([ff, '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'gray', '-s', '640x360', '-r', '1', '-i', '-',
                            '-c:v', 'libx264', '-crf', '10', '-g', '1', '-pix_fmt', 'yuv420p', str(path)], stdin=subprocess.PIPE)
    for _ in range(30):
        frame = cv2.resize(_background(rng), (640, 360), interpolation=cv2.INTER_LINEAR)
        cv2.putText(frame, 'LOGO', (60, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.8, 255, 4, cv2.LINE_8)
        enc.stdin.write(frame.tobytes())
    enc.stdin.close()
    assert enc.wait() == 0


@unittest.skipUnless(cv2 is not None, 'cv2 not available')
class LogosStageTest(unittest.TestCase):
    def setUp(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dubflow'))

    def test_stage_writes_candidates_and_keeps_user_decisions(self):
        import json
        import tempfile
        from pathlib import Path
        import engine_cli
        ff = _ffmpeg(self)
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            src = d / 'source.mp4'
            _write_video(ff, src, 5)
            frag = dict(id='r1', kind='static', x=60, y=40, width=150, height=40, start=0, end=30., text='LOGO', translation='', enabled=True)
            rejected = dict(frag, id='rej', x=500, y=300, width=60, height=30, text='', auto=True, confirmed=True, enabled=False, label='Logo')
            sub = dict(frag, id='s1', kind='subtitle', x=100, y=300, width=300, height=40)
            (d / 'regions.json').write_text(json.dumps([frag, rejected, sub]))
            (d / 'subtrack.json').write_text(json.dumps(dict(version=1, segments=[])))
            request = dict(ffmpeg=ff, source=str(src), width=640, height=360, duration=30., source_hash='abc')
            engine_cli.logos(d, request)
            got = json.loads((d / 'regions.json').read_text(encoding='utf-8'))
            marker = json.loads((d / 'logo-candidates.json').read_text(encoding='utf-8'))
            self.assertEqual(marker['source_hash'], 'abc')
            ids = [r['id'] for r in got]
            self.assertEqual(ids[:2], ['rej', 's1'])
            self.assertNotIn('r1', ids)
            new = [r for r in got if r.get('auto') and not r.get('confirmed')]
            self.assertEqual(len(new), 1, got)
            self.assertEqual((new[0]['label'], new[0]['text'], new[0]['enabled']), ('Chữ cố định', 'LOGO', True))
            self.assertAlmostEqual(new[0]['x'], 60, delta=14)
            self.assertAlmostEqual(new[0]['y'], 26, delta=10)
            self.assertEqual(new[0]['start'], 0)
            # a second run replaces only the unconfirmed candidate, keeping the decision
            engine_cli.logos(d, request)
            again = json.loads((d / 'regions.json').read_text(encoding='utf-8'))
            self.assertEqual([r['id'] for r in again if r['id'] in ('rej', 's1')], ['rej', 's1'])
            self.assertEqual(len([r for r in again if r.get('auto') and not r.get('confirmed')]), 1)

    def test_subtitle_segment_boxes_are_excluded(self):
        import json
        import tempfile
        from pathlib import Path
        import engine_cli
        ff = _ffmpeg(self)
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            src = d / 'source.mp4'
            _write_video(ff, src, 6)
            (d / 'regions.json').write_text('[]')
            (d / 'subtrack.json').write_text(json.dumps(dict(version=1, segments=[dict(s=0, e=30, x0=40, y0=30, x1=260, y1=100, text='x')])))
            engine_cli.logos(d, dict(ffmpeg=ff, source=str(src), width=640, height=360, duration=30., source_hash='abc'))
            self.assertEqual(json.loads((d / 'regions.json').read_text(encoding='utf-8')), [])


class ExcludeBoxesTest(unittest.TestCase):
    def setUp(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dubflow'))

    def test_subtitle_regions_and_their_union_are_excluded(self):
        import engine_cli
        regions = [dict(kind='subtitle', x=100, y=300, width=50, height=20), dict(kind='subtitle', x=400, y=310, width=60, height=40),
                   dict(kind='static', x=0, y=0, width=10, height=10)]
        got = engine_cli.exclude_boxes({}, regions)
        self.assertEqual(got, [(100, 300, 50, 20), (400, 310, 60, 40), (100, 300, 360, 50)])

    def test_track_segments_and_band(self):
        import engine_cli
        track = dict(segments=[dict(x0=10, y0=20, x1=60, y1=40), dict(x0=0, y0=0, x1=0, y1=0)], band=[15, 45])
        self.assertEqual(engine_cli.exclude_boxes(track, []), [(10, 20, 50, 20), (10, 15, 50, 30)])
        self.assertEqual(engine_cli.exclude_boxes(None, None), [])


@unittest.skipUnless(cv2 is not None, 'cv2 not available')
class SubtitleExcludedDetectTest(unittest.TestCase):
    def test_pattern_inside_subtitle_region_is_not_detected(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dubflow'))
        import engine_cli
        frames, times = _sequence()
        ex = engine_cli.exclude_boxes({}, [dict(kind='subtitle', x=40, y=30, width=220, height=60)])
        self.assertEqual(detect_static(frames, times, 80., ex, SCALE), [])


class PipelineHookTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.source = self.dir / 'source.mp4'
        self.source.write_bytes(b'video')
        self.settings = SimpleNamespace(ocr_python='python')
        self.events = []

    def tearDown(self):
        self.tmp.cleanup()

    def emit(self, *args):
        self.events.append(args)

    def run_hook(self, **kw):
        from unittest.mock import patch
        from dubflow import pipeline
        with patch.object(pipeline, 'engine') as engine:
            pipeline.detect_logos(self.dir, self.source, dict(width=10, height=10, duration=5.), self.settings, self.emit, **kw)
        return engine

    def test_runs_once_per_source_hash(self):
        from dubflow import pipeline
        engine = self.run_hook()
        self.assertEqual(engine.call_args.args[0], 'logos')
        payload = engine.call_args.args[3]
        self.assertEqual(payload['source_hash'], pipeline.file_hash(self.source))
        pipeline.write(self.dir / 'logo-candidates.json', dict(source_hash=payload['source_hash']))
        self.assertFalse(self.run_hook().called)
        self.assertTrue(self.run_hook(force=True).called)
        self.source.write_bytes(b'other video')
        self.assertTrue(self.run_hook().called)

    def test_ocr_rerun_invalidates_candidates_so_prepare_detects_again(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from dubflow import pipeline as p
        p.write(self.dir / 'job.json', dict(source_path='source.mp4', mode='vietsub'))
        p.write(self.dir / 'ocr-complete.json', {})
        p.write(self.dir / 'logo-candidates.json', dict(source_hash=p.file_hash(self.source)))
        calls = []

        def stage(name, directory, settings, payload, **kwargs):
            calls.append(name)
            if name == 'subtrack':
                p.write(directory / 'subtrack.json', dict(version=1, segments=[]))
            elif name == 'ocr':
                p.write(directory / 'regions.json', [])
        # regions.json is missing: OCR runs; the old candidates file (same source) must not stop the logo stage
        with patch.object(p, 'probe', return_value=dict(duration=3, width=320, height=240)), patch.object(p, 'engine', side_effect=stage):
            try:
                p.prepare(self.dir, SimpleNamespace(ocr_python='python'), lambda *a: None)
            except p.NeedsReview:
                pass
        self.assertIn('ocr', calls)
        self.assertEqual(calls[calls.index('ocr') + 1], 'logos')
        # without an OCR rewrite the same marker does skip the stage
        p.write(self.dir / 'logo-candidates.json', dict(source_hash=p.file_hash(self.source)))
        p.write(self.dir / 'regions.json', [dict(id='r1', kind='static', x=0, y=0, width=5, height=5, start=0, end=1, enabled=False)])
        calls.clear()
        with patch.object(p, 'probe', return_value=dict(duration=3, width=320, height=240)), patch.object(p, 'engine', side_effect=stage):
            try:
                p.prepare(self.dir, SimpleNamespace(ocr_python='python'), lambda *a: None)
            except p.NeedsReview:
                pass
        self.assertNotIn('logos', calls)

    def test_without_ocr_python_nothing_runs(self):
        self.settings.ocr_python = None
        self.assertFalse(self.run_hook().called)

    def test_failure_is_a_warning_in_prepare_but_raises_on_demand(self):
        from unittest.mock import patch
        from dubflow import pipeline
        warnings = []
        with patch.object(pipeline, 'engine', side_effect=pipeline.NeedsReview('logos unavailable')):
            pipeline.detect_logos(self.dir, self.source, {}, self.settings, self.emit, warnings)
            self.assertEqual(len(warnings), 1)
            with self.assertRaises(pipeline.NeedsReview):
                pipeline.detect_logos(self.dir, self.source, {}, self.settings, self.emit)

    def test_cancel_always_propagates(self):
        from unittest.mock import patch
        from dubflow import pipeline
        with patch.object(pipeline, 'engine', side_effect=pipeline.Cancelled('x')):
            with self.assertRaises(pipeline.Cancelled):
                pipeline.detect_logos(self.dir, self.source, {}, self.settings, self.emit, [])


try:
    from fastapi.testclient import TestClient
except ImportError:
    TestClient = None


@unittest.skipUnless(TestClient is not None, 'fastapi not available')
class DetectLogosApiTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from dubflow.app import create_app
        from dubflow.config import Settings
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.cfg = Settings(root=root, data_dir=root / 'data', system_voices=root / 'voices')
        self.app = create_app(self.cfg, start_worker=False)
        self.client = TestClient(self.app)
        self.store = self.app.state.store
        job = self.store.create_job(dict(title='t', mode='vietsub', status='done', stage='done', progress=100, duration=100, width=1280, height=720))
        self.jid = job['id']
        self.store.update_job(self.jid, source_path=str(root / 'source.mp4'))
        self.folder = self.cfg.jobs_dir / self.jid
        self.folder.mkdir()
        self.url = f'/api/jobs/{self.jid}/detect-logos'

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def test_body_is_required(self):
        r = self.client.post(self.url, content='', headers={'content-type': 'text/plain'})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.store.active_tasks(), [])

    def test_enqueues_a_task_and_second_call_is_409(self):
        r = self.client.post(self.url, json={})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([t['action'] for t in self.store.active_tasks()], ['detect_logos'])
        self.assertEqual(self.client.post(self.url, json={}).status_code, 409)

    def test_busy_job_is_409(self):
        self.store.update_job(self.jid, status='rendering')
        self.assertEqual(self.client.post(self.url, json={}).status_code, 409)
        self.assertEqual(self.store.active_tasks(), [])

    def test_unknown_job_is_404(self):
        self.assertEqual(self.client.post('/api/jobs/nope/detect-logos', json={}).status_code, 404)

    def test_worker_runs_detection_and_restores_previous_status(self):
        from unittest.mock import patch
        from dubflow.worker import run_task
        with patch('dubflow.pipeline.context', return_value=(self.folder, {}, 'src.mp4', {'duration': 100})), \
                patch('dubflow.pipeline.detect_logos') as detect:
            self.assertEqual(self.client.post(self.url, json={}).status_code, 200)
            run_task(self.store.claim_next(), self.cfg, self.store)
        self.assertEqual(detect.call_args.kwargs.get('force'), True)
        job = self.store.get_job(self.jid)
        self.assertEqual((job['status'], job['stage'], job['progress']), ('done', 'done', 100))
        self.assertEqual(self.store.active_tasks(), [])
        self.assertFalse((self.folder / 'detect-logos-request.json').exists())
        (self.folder / 'output.mp4').write_bytes(b'x')
        self.assertTrue(self.client.get(f'/api/jobs/{self.jid}').json()['output_url'])

    def test_worker_failure_warns_and_keeps_previous_status(self):
        from unittest.mock import patch
        from dubflow import pipeline
        from dubflow.worker import run_task
        with patch('dubflow.pipeline.context', return_value=(self.folder, {}, 'src.mp4', {'duration': 100})),                 patch('dubflow.pipeline.detect_logos', side_effect=pipeline.NeedsReview('logos failed (exit 1)')):
            self.assertEqual(self.client.post(self.url, json={}).status_code, 200)
            run_task(self.store.claim_next(), self.cfg, self.store)
        job = self.store.get_job(self.jid)
        self.assertEqual((job['status'], job['stage'], job['progress']), ('done', 'done', 100))
        self.assertIsNone(job['error'])
        self.assertTrue(any('logos failed' in w for w in job['warnings']), job['warnings'])
        self.assertEqual(self.store.active_tasks(), [])

    def test_region_flags_round_trip(self):
        region = dict(id='logo-1', kind='static', x=10, y=10, width=50, height=20, start=0, end=50, text='', translation='',
                      enabled=False, auto=True, confirmed=True, label='Logo')
        r = self.client.put(f'/api/jobs/{self.jid}/regions', json=[region])
        self.assertEqual(r.status_code, 200, r.text)
        got = self.client.get(f'/api/jobs/{self.jid}/regions').json()[0]
        self.assertEqual((got['auto'], got['confirmed'], got['label'], got['enabled']), (True, True, 'Logo', False))
        plain = {k: v for k, v in dict(region, id='x').items() if k not in ('auto', 'confirmed', 'label')}
        got = self.client.put(f'/api/jobs/{self.jid}/regions', json=[plain]).json()[0]
        self.assertEqual((got['auto'], got['confirmed'], got['label']), (False, False, ''))


if __name__ == '__main__':
    unittest.main()
