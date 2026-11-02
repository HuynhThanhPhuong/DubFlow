import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dubflow'))
import pipeline as p

ENGINE = Path(p.__file__).with_name('engine_cli.py')
SIMPLE = 'def {}(x):\n    return x\n\n'


class TakeCodeHashTests(unittest.TestCase):
    def copy(self, directory, transform):
        path = Path(directory)/'engine_cli.py'
        path.write_text(transform(ENGINE.read_text(encoding='utf-8')), encoding='utf-8')
        return path

    def test_unrelated_edit_keeps_key_and_gen_edit_changes_it(self):
        with tempfile.TemporaryDirectory(dir=p.ROOT/'tmp') as d:
            base = p.take_code_hash(ENGINE)
            self.assertEqual(p.take_code_hash(self.copy(d, lambda t: t)), base)
            ocr = self.copy(d, lambda t: t.replace('def ocr(directory, request):\n', 'def ocr(directory, request):\n    unrelated = 1\n', 1))
            self.assertNotEqual(ocr.read_text(encoding='utf-8'), ENGINE.read_text(encoding='utf-8'))
            self.assertEqual(p.take_code_hash(ocr), base)
            erase = self.copy(d, lambda t: t.replace('def erase(directory, request):\n', 'def erase(directory, request):\n    unrelated = 1\n', 1) + '\n\ndef extra():\n    return 1\n')
            self.assertEqual(p.take_code_hash(erase), base)
            gen = self.copy(d, lambda t: t.replace('def gen(directory, request):\n', 'def gen(directory, request):\n    changed = 1\n', 1))
            self.assertNotEqual(p.take_code_hash(gen), base)
            match = self.copy(d, lambda t: t.replace('token_distance(got, want) <= 1', 'token_distance(got, want) <= 2', 1))
            self.assertNotEqual(p.take_code_hash(match), base)

    def test_every_named_function_exists(self):
        self.assertTrue(p.take_code_hash())


class RenderCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=p.ROOT/'tmp')
        self.folder = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        (self.folder/'source.mp4').write_bytes(b'src')
        self.logo_id = 'a'*64
        (self.folder/'logos').mkdir()
        (self.folder/'logos'/f'{self.logo_id}.png').write_bytes(b'png1')
        self.meta = dict(width=120, height=90, duration=2, fps=25)
        self.runs = []
        self.set_cues('xin chao')
        self.set_job([])

    def set_cues(self, text):
        p.write(self.folder/'cues.json', [dict(id='1', start=0, end=1, speaker='s', original='a', text=text)])

    def set_job(self, overlays):
        p.write(self.folder/'job.json', dict(mode='vietsub', source_path='source.mp4', overlays=overlays))

    def render(self):
        def fake_run(cmd, cwd=None, **kwargs):
            if cmd[-1] == 'output.mp4':
                self.runs.append(cmd)
                (Path(cwd)/'output.mp4').write_bytes(b'video%d' % len(self.runs))
            return ''
        job = p.read(self.folder/'job.json')
        settings = SimpleNamespace(blur_original=False, data_dir=self.folder)
        with patch.object(p, 'context', return_value=(self.folder, job, self.folder/'source.mp4', self.meta)), \
                patch.object(p, 'run', side_effect=fake_run), patch.object(p, 'video_encoder', return_value=p.X264_ARGS), \
                patch.object(p, 'frames_missing', return_value=False):
            return p.render(self.folder, settings, lambda *a: None)

    def test_identical_render_is_skipped(self):
        self.render()
        self.assertEqual(len(self.runs), 1)
        self.assertTrue((self.folder/'render-key.json').exists())
        self.render()
        self.assertEqual(len(self.runs), 1)

    def test_changed_cue_overlay_or_logo_file_reencodes(self):
        self.render()
        self.set_cues('xin chao ban')
        self.render()
        self.assertEqual(len(self.runs), 2)
        overlay = dict(logo_id=self.logo_id, x=1, y=2, width=10, height=10, opacity=1, start=0, end=1)
        self.set_job([overlay])
        self.render()
        self.assertEqual(len(self.runs), 3)
        self.set_job([dict(overlay, x=5)])  # the filter graph text changes
        self.render()
        self.assertEqual(len(self.runs), 4)
        (self.folder/'logos'/f'{self.logo_id}.png').write_bytes(b'png2')
        self.render()
        self.assertEqual(len(self.runs), 5)
        self.render()
        self.assertEqual(len(self.runs), 5)

    def test_missing_output_or_failed_check_reencodes(self):
        self.render()
        (self.folder/'output.mp4').unlink()
        self.render()
        self.assertEqual(len(self.runs), 2)
        with patch.object(p, 'frames_missing', return_value=True):
            job = p.read(self.folder/'job.json')
            with patch.object(p, 'context', return_value=(self.folder, job, self.folder/'source.mp4', self.meta)), \
                    patch.object(p, 'run', side_effect=lambda cmd, cwd=None, **k: (self.runs.append(cmd) if cmd[-1] == 'output.mp4' else None) or ''), \
                    patch.object(p, 'video_encoder', return_value=p.X264_ARGS):
                p.render(self.folder, SimpleNamespace(blur_original=False, data_dir=self.folder), lambda *a: None)
        self.assertEqual(len(self.runs), 3)


class PrepareStampTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=p.ROOT/'tmp')
        self.folder = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        (self.folder/'source.mp4').write_bytes(b'one')
        p.write(self.folder/'regions.json', [])
        p.write(self.folder/'ocr-complete.json', {})

    def prepare(self, mode):
        p.write(self.folder/'job.json', dict(source_path='source.mp4', mode=mode))
        calls = []
        def stage(name, directory, settings, payload, **kwargs):
            calls.append(name)
            if name == 'separate':
                (directory/'background.wav').write_bytes(b'b')
                (directory/'vocals.wav').write_bytes(b'v')
            elif name == 'transcribe':
                p.write(directory/'source-asr-cues.json', [dict(id='a1', start=1.0, end=2.0, speaker='s', original='x', text='')])
            elif name == 'subtrack':
                p.write(directory/'subtrack.json', dict(version=1, fps=10, band=[1, 2], segments=[]))
        with patch.object(p, 'probe', return_value=dict(duration=5, width=320, height=240)), patch.object(p, 'engine', side_effect=stage), \
                patch.object(p, 'audio_rms', return_value=([0.0]*250, .02)):
            try:
                p.prepare(self.folder, SimpleNamespace(), lambda *a: None)
            except Exception:  # noqa: BLE001 - later stages are out of scope here
                pass
        return calls

    def test_transcribe_reruns_only_when_source_changes(self):
        self.assertIn('transcribe', self.prepare('vietsub'))
        self.assertTrue(p.read(self.folder/'cues.json'))
        self.assertNotIn('transcribe', self.prepare('vietsub'))
        (self.folder/'source.mp4').write_bytes(b'two')
        self.assertIn('transcribe', self.prepare('vietsub'))

    def test_separate_reruns_when_source_replaced(self):
        self.assertIn('separate', self.prepare('dub'))
        self.assertNotIn('separate', self.prepare('dub'))
        (self.folder/'source.mp4').write_bytes(b'two')
        calls = self.prepare('dub')
        self.assertIn('separate', calls)

    def test_job_without_stamps_keeps_outputs(self):
        (self.folder/'background.wav').write_bytes(b'b')
        (self.folder/'vocals.wav').write_bytes(b'v')
        p.write(self.folder/'cues.json', [dict(id='1', start=0, end=1, speaker='s', original='x', text='y')])
        calls = self.prepare('dub')
        self.assertNotIn('separate', calls)
        self.assertNotIn('transcribe', calls)


if __name__ == '__main__':
    unittest.main()
