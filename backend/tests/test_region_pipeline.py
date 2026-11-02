"""prepare() of a job whose regions the user drew: only those regions are read, nothing is detected automatically."""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dubflow import pipeline as p

LINES = [dict(s=1.0, e=2.5, x0=100, y0=170, x1=220, y1=200, text='你好吗朋友', confidence=1.0, readings=['你好吗朋友']),
         dict(s=3.0, e=3.4, x0=100, y0=170, x1=200, y1=200, text='再见了朋友们', confidence=1.0, readings=['再见了朋友们']),
         dict(s=9.0, e=10.0, x0=100, y0=170, x1=200, y1=200, text='最后一句话了', confidence=1.0, readings=['最后一句话了'])]
ASR = [dict(id='a1', start=1.2, end=2.4, speaker='s', original='你好吗朋友', text=''),   # speech of line 1
       dict(id='a2', start=5.0, end=6.5, speaker='s', original='没有字幕的话', text='')]  # nothing on screen
BOX = [60, 160, 200, 50]


class RegionPrepareTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(dir=p.ROOT)
        self.d = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.d / 'source.mp4').write_bytes(b'src')
        self.calls = []

    def cfg(self, **over):
        return dict(dict(no_hard_subs=False, subtitle=BOX, logos=[], screen_text=[]), **over)

    def stage(self, name, directory, settings, payload, **kwargs):
        self.calls.append((name, payload))
        if name == 'transcribe':
            p.write(directory / 'source-asr-cues.json', ASR)
        elif name == 'subband':
            p.write(directory / 'subtrack.json', dict(version=2, mode='band', box=payload['box'], band=[payload['box'][1], payload['box'][1] + payload['box'][3]], segments=LINES))
        elif name == 'ocr':
            p.write(directory / payload['regions_output'], [dict(id='r1', kind='transient', x=10, y=10, width=50, height=20, start=1.0, end=2.0,
                                                                  text='标题', translation='', enabled=True)])

    def prepare(self, cfg, **job):
        p.write(self.d / 'job.json', dict(source_path='source.mp4', mode='vietsub', analysis_regions=cfg, **job))
        self.calls.clear()
        with patch.object(p, 'probe', return_value=dict(duration=12, width=320, height=240, fps=25)), patch.object(p, 'engine', side_effect=self.stage), \
                patch.object(p, 'audio_rms', return_value=([0.0] * 600, .02)):
            try:
                return p.prepare(self.d, SimpleNamespace(ocr_python=sys.executable), lambda *a: None)
            except p.NeedsReview:
                return None

    def names(self):
        return [c[0] for c in self.calls]

    def test_only_the_drawn_band_is_read_and_nothing_is_detected(self):
        self.prepare(self.cfg(logos=[[5, 5, 40, 20]]))
        self.assertEqual(self.names(), ['transcribe', 'subband', 'erase'])
        self.assertEqual(self.calls[1][1]['box'], BOX)
        for banned in ('subtrack', 'logos'):
            self.assertNotIn(banned, self.names())

    def test_one_ocr_cue_per_line_and_asr_only_in_the_gaps(self):
        self.prepare(self.cfg())
        cues = p.read(self.d / 'cues.json')
        self.assertEqual([(c['source'], c['original']) for c in cues if c['source'] != 'asr'],
                         [('ocr+asr', '你好吗朋友'), ('ocr', '再见了朋友们'), ('ocr', '最后一句话了')])
        asr = [c for c in cues if c['source'] == 'asr']
        self.assertEqual([c['id'] for c in asr], ['a2'])
        self.assertEqual(cues[0]['box'], [100, 170, 220, 200])
        build = p.read(self.d / 'source-build.json')
        self.assertEqual((build['mode'], build['ocr_cues'], build['asr_cues'], build['asr_dropped']), ('regions', 3, 1, 1))

    def test_regions_json_holds_subtitle_windows_and_confirmed_logo_rows(self):
        self.prepare(self.cfg(logos=[[5, 5, 40, 20]]))
        rows = p.read(self.d / 'regions.json')
        sub = [r for r in rows if r['kind'] == 'subtitle']
        self.assertEqual([r['text'] for r in sub], ['你好吗朋友', '再见了朋友们', '最后一句话了'])
        self.assertTrue(all((r['x'], r['y'], r['width'], r['height']) == tuple(BOX) for r in sub))
        self.assertAlmostEqual(sub[0]['end'], sub[1]['start'], places=3)  # 2.5 s and 3.0 s: bridged, the sub never shows through
        logos = [r for r in rows if r['kind'] == 'static']
        self.assertEqual([(r['x'], r['y'], r['width'], r['height'], r['start'], r['end']) for r in logos], [(5, 5, 40, 20, 0.0, 12.0)])
        self.assertTrue(logos[0]['confirmed'] and not logos[0]['auto'] and p.erases_static(logos[0]))
        self.assertTrue(p.read(self.d / 'ocr-complete.json')['region_mode'])
        # erase gets the logo as a static region and the band as subtrack.json (version 2 with the box)
        self.assertEqual(len(p.erase_static_regions(self.d)), 1)
        self.assertEqual(p.read(self.d / 'subtrack.json')['box'], BOX)

    def test_a_logo_only_change_does_not_read_the_band_again_or_touch_the_cues(self):
        self.prepare(self.cfg())
        cues = p.read(self.d / 'cues.json')
        cues[0]['text'] = 'Xin chào'
        p.write(self.d / 'cues.json', cues)
        self.prepare(self.cfg(logos=[[5, 5, 40, 20]]))
        self.assertNotIn('subband', self.names())
        self.assertNotIn('transcribe', self.names())
        self.assertEqual(p.read(self.d / 'cues.json')[0]['text'], 'Xin chào')
        self.assertTrue(any(r['id'] == 'userlogo-1' for r in p.read(self.d / 'regions.json')))
        self.assertIn('erase', self.names())  # the logo changes what is erased

    def test_a_moved_band_rebuilds_the_cues_and_keeps_a_backup(self):
        self.prepare(self.cfg())
        self.prepare(self.cfg(subtitle=[60, 150, 200, 60]))
        self.assertEqual(self.names()[:1], ['subband'])
        self.assertNotIn('transcribe', self.names())
        self.assertEqual(len(list(self.d.glob('cues.before-regions-*.json'))), 1)

    def test_no_hard_subs_uses_asr_and_skips_the_band(self):
        self.prepare(self.cfg(no_hard_subs=True, subtitle=None))
        self.assertEqual(self.names(), ['transcribe'])
        cues = p.read(self.d / 'cues.json')
        self.assertEqual([c['id'] for c in cues], ['a1', 'a2'])
        self.assertEqual(p.read(self.d / 'subtrack.json'), dict(version=2, mode='none', box=None, segments=[]))
        self.assertFalse(p.erase_wanted(self.d))

    def test_no_hard_subs_with_a_logo_still_erases_the_logo(self):
        self.prepare(self.cfg(no_hard_subs=True, subtitle=None, logos=[[5, 5, 40, 20]]))
        self.assertEqual(self.names(), ['transcribe', 'erase'])

    def test_screen_text_boxes_are_the_only_ocr_area_and_are_read_once(self):
        self.prepare(self.cfg(screen_text=[[10, 10, 80, 30]]))
        ocr = [c for c in self.calls if c[0] == 'ocr']
        self.assertEqual(len(ocr), 1)
        self.assertEqual((ocr[0][1]['crop_boxes'], ocr[0][1]['ocr_fps']), ([[10, 10, 80, 30]], 2))
        rows = p.read(self.d / 'regions.json')
        self.assertEqual([r['text'] for r in rows if r['kind'] == 'transient'], ['标题'])
        rows[0]['translation'] = 'Tiêu đề'  # the user translates it
        p.write(self.d / 'regions.json', rows)
        self.prepare(self.cfg(screen_text=[[10, 10, 80, 30]], logos=[[5, 5, 40, 20]]))
        self.assertNotIn('ocr', self.names())
        self.assertEqual([r['translation'] for r in p.read(self.d / 'regions.json') if r['kind'] == 'transient'], ['Tiêu đề'])
        self.prepare(self.cfg(screen_text=[[10, 10, 90, 30]]))
        self.assertIn('ocr', self.names())  # the box changed: read again

    def test_user_choice_on_a_logo_row_survives_reanalysis(self):
        self.prepare(self.cfg(logos=[[5, 5, 40, 20]]))
        rows = p.read(self.d / 'regions.json')
        for r in rows:
            if r['id'] == 'userlogo-1':
                r['enabled'] = False
        p.write(self.d / 'regions.json', rows)
        self.prepare(self.cfg(logos=[[5, 5, 40, 20]]))
        self.assertFalse(next(r for r in p.read(self.d / 'regions.json') if r['id'] == 'userlogo-1')['enabled'])
        self.prepare(self.cfg(logos=[[6, 5, 40, 20]]))  # moved: a new box, enabled again
        self.assertTrue(next(r for r in p.read(self.d / 'regions.json') if r['id'] == 'userlogo-1')['enabled'])

    def test_subband_failure_is_a_warning_and_asr_is_used(self):
        def failing(name, directory, settings, payload, **kwargs):
            self.calls.append((name, payload))
            if name == 'transcribe':
                p.write(directory / 'source-asr-cues.json', ASR)
            elif name == 'subband':
                raise p.NeedsReview('subband unavailable or failed (exit 1); see subband.log (no model downloads attempted)')
        p.write(self.d / 'job.json', dict(source_path='source.mp4', mode='vietsub', analysis_regions=self.cfg()))
        with patch.object(p, 'probe', return_value=dict(duration=12, width=320, height=240, fps=25)), patch.object(p, 'engine', side_effect=failing), \
                patch.object(p, 'audio_rms', return_value=([0.0] * 600, .02)):
            with self.assertRaises(p.NeedsReview):  # the Vietnamese text is still to be entered
                p.prepare(self.d, SimpleNamespace(ocr_python=sys.executable), lambda *a: None)
        self.assertEqual([c['id'] for c in p.read(self.d / 'cues.json')], ['a1', 'a2'])
        self.assertTrue(p.read(self.d / 'source-build.json')['ocr_failed'])
        self.assertFalse(p.erase_wanted(self.d))

    def test_render_never_runs_the_full_frame_ocr_for_a_region_job(self):
        self.prepare(self.cfg(no_hard_subs=True, subtitle=None))  # regions.json is empty: the legacy code would detect now
        self.assertEqual(p.read(self.d / 'regions.json'), [])
        with patch.object(p, 'engine', side_effect=AssertionError('OCR must not run')):
            rows = p.refine_text_regions(self.d, self.d / 'source.mp4', dict(duration=12, width=320, height=240), SimpleNamespace(ocr_python=sys.executable), lambda *a: None)
        self.assertEqual(rows, [])

    def test_jobs_without_regions_keep_the_legacy_detection(self):
        p.write(self.d / 'job.json', dict(source_path='source.mp4', mode='vietsub'))
        self.calls.clear()

        def legacy(name, directory, settings, payload, **kwargs):
            self.calls.append(name)
            if name == 'transcribe':
                p.write(directory / 'source-asr-cues.json', ASR)
            elif name == 'subtrack':
                p.write(directory / 'subtrack.json', dict(version=1, segments=[]))
        with patch.object(p, 'probe', return_value=dict(duration=12, width=320, height=240)), patch.object(p, 'engine', side_effect=legacy), \
                patch.object(p, 'audio_rms', return_value=([0.0] * 600, .02)):
            try:
                p.prepare(self.d, SimpleNamespace(ocr_python=sys.executable), lambda *a: None)
            except p.NeedsReview:
                pass
        self.assertEqual(self.calls[:2], ['transcribe', 'subtrack'])
        self.assertIn('ocr', self.calls)


class KillChildrenTests(unittest.TestCase):
    def test_kill_children_ends_the_processes_wait_owned_is_waiting_on(self):
        import subprocess
        import threading
        import time
        proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        with tempfile.TemporaryDirectory() as tmp:
            result = {}
            t = threading.Thread(target=lambda: result.update(code=p.wait_owned(proc, tmp)))
            t.start()
            for _ in range(50):
                if proc in p.LIVE_PROCESSES:
                    break
                time.sleep(.05)
            self.assertIn(proc, p.LIVE_PROCESSES)
            self.assertEqual(p.kill_children(), 1)
            t.join(10)
            self.assertFalse(t.is_alive())
            self.assertIsNotNone(proc.poll())
            self.assertNotIn(proc, p.LIVE_PROCESSES)
            self.assertEqual(p.kill_children(), 0)


if __name__ == '__main__':
    unittest.main()
