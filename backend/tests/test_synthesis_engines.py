"""Voice engines: OmniVoice stage, engine order, fallback budget, pronounce map and the voice report.
The engines themselves are stubbed through the pipeline.engine() seam; nothing loads a model."""
import copy
import shutil
import sys
import tempfile
import types
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dubflow import pipeline as p


def ffmpeg_path(test):
    ff = shutil.which('ffmpeg') or 'D:/OmniVoice/tools/ffmpeg.exe'
    if not Path(ff).exists():
        test.skipTest('ffmpeg unavailable')
    return ff


def silent_wav(path, seconds=.5):
    with wave.open(str(path), 'wb') as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(48000)
        audio.writeframes(b'\0\0' * int(48000 * seconds))


def tone_wav(path, seconds=3., amplitude=8000):
    import array
    import math
    samples = array.array('h', (int(amplitude * math.sin(2 * math.pi * 220 * n / 48000)) for n in range(int(48000 * seconds))))
    with wave.open(str(path), 'wb') as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(48000)
        audio.writeframes(samples.tobytes())


class Rig:
    """A job directory plus a stub for pipeline.engine that passes lines according to `policy(engine, cue_index)`."""

    def __init__(self, test, mode='tm', texts=('Xin chào', 'Tạm biệt'), voice_ref=None, policy=lambda engine, i: False, crash=(),
                 ref_seconds=3., ref_amplitude=8000):
        self.test = test
        self.policy = policy
        self.crash = set(crash)  # stages whose engine() call fails like a crashed subprocess
        self.calls = []        # (stage, cue indexes, count)
        self.payloads = []     # (stage, deep-copied payload)
        tmp = tempfile.TemporaryDirectory(dir=p.ROOT)
        test.addCleanup(tmp.cleanup)
        self.dir = d = Path(tmp.name)
        tone_wav(d / 'ref.wav', ref_seconds, ref_amplitude)
        tone_wav(d / 'primer.wav')
        cues = [dict(id=str(i + 1), start=i * 1., end=i * 1. + 1., speaker='A', original='原文', text=t) for i, t in enumerate(texts)]
        job = dict(source_path='source.mp4', mode=mode)
        if mode == 'tm':
            job['voice_ref'] = voice_ref or dict(path='ref.wav', text='reference', hash='ignored')
        else:
            job['export_kind'] = 'auto'
            (d / 'vocals.wav').write_bytes(b'vocals')
            p.write(d / 'primer.json', dict(path='primer.wav', text='đoạn mồi'))
        p.write(d / 'job.json', job)
        p.write(d / 'cues.json', cues)
        self.settings = SimpleNamespace(ffmpeg=ffmpeg_path(test), max_takes=8, fallback_takes=4, asr_cache='', model_cache='', vi_prompt=str(d / 'primer.json'))

    def stage(self, name, directory, settings, payload, **kwargs):
        tasks = payload.get('tasks')
        self.calls.append((name, [t['i'] for t in tasks] if tasks else None, payload.get('count')))
        self.payloads.append((name, copy.deepcopy(payload)))
        if name in self.crash:
            raise p.NeedsReview(f'{name} unavailable or failed (exit 1); see {name}.log (no model downloads attempted)')
        if name == 'refs':
            p.write(directory / 'speaker-refs.json', dict(A=dict(path=str(directory / 'ref.wav'), text='lời gốc của người nói', hash='x')))
        if name == 'pick':
            shutil.copyfile(directory / 'ref.wav', directory / 'lines/take.wav')
            state = p.read(directory / 'state.json', {})
            for task in tasks:
                engine = task['params']['engine']
                entry = state.setdefault(task['key'], {'takes': {}})
                for seed in range(1000, 1000 + payload['count']):
                    entry['takes'].setdefault(str(seed), dict(path='lines/take.wav', duration=.5, exact=False, seed=seed, engine=engine))
                if self.policy(engine, task['i']):
                    entry['accepted'] = dict(path='lines/take.wav', duration=.5, seed=1000, engine=engine, exact=True)
            p.write(directory / 'state.json', state)

    def run(self):
        with patch.object(p, 'probe', return_value=dict(duration=4, width=320, height=240)), patch.object(p, 'engine', side_effect=self.stage):
            return p.synthesize(self.dir, self.settings, lambda *a: None)

    def tasks(self, stage):
        return [t for name, payload in self.payloads if name == stage for t in payload['tasks']]


class EngineOrderTests(unittest.TestCase):
    def test_tm_runs_omnivoice_first_and_voxcpm_only_for_lines_still_failing(self):
        rig = Rig(self, policy=lambda engine, i: (engine, i) in {('omnivoice', 0), ('voxcpm2', 1)})
        rig.run()
        self.assertEqual(rig.calls, [('gen_omni', [0, 1], 4), ('pick', [0, 1], 4), ('gen_omni', [1], 8), ('pick', [1], 8), ('gen', [1], 4), ('pick', [1], 4)])
        manifest = p.read(rig.dir / 'manifest.json')
        self.assertEqual([row['engine'] for row in manifest['lines']], ['omnivoice', 'voxcpm2'])

    def test_tm_fallback_is_not_started_when_omnivoice_passes_everything(self):
        rig = Rig(self, policy=lambda engine, i: engine == 'omnivoice')
        rig.run()
        self.assertEqual([c[0] for c in rig.calls], ['gen_omni', 'pick'])

    def test_dub_runs_voxcpm_mix_first_and_omnivoice_only_for_lines_still_failing(self):
        rig = Rig(self, mode='dub', policy=lambda engine, i: (engine, i) in {('voxcpm2', 0), ('omnivoice', 1)})
        rig.run()
        self.assertEqual([c for c in rig.calls if c[0] != 'refs'],
                         [('gen', [0, 1], 4), ('pick', [0, 1], 4), ('gen', [1], 8), ('pick', [1], 8), ('gen_omni', [1], 4), ('pick', [1], 4)])
        manifest = p.read(rig.dir / 'manifest.json')
        self.assertEqual([row['engine'] for row in manifest['lines']], ['voxcpm2', 'omnivoice'])

    def test_dub_omnivoice_uses_the_speaker_clip_with_default_settings(self):
        rig = Rig(self, mode='dub', policy=lambda engine, i: engine == 'omnivoice')
        rig.run()
        omni = rig.tasks('gen_omni')[0]
        self.assertEqual(omni['ref']['path'], str((rig.dir / 'ref.wav').resolve()))
        self.assertEqual(omni['ref']['text'], 'lời gốc của người nói')
        params = omni['params']
        self.assertEqual((params['num_step'], params['guidance_scale'], params['language']), (32, 2., 'Vietnamese'))
        self.assertIsNone(omni['prompt'])  # the Vietnamese primer belongs to the VoxCPM2 mix only
        self.assertTrue(rig.tasks('gen')[0]['prompt']['text'])

    def test_dub_reads_the_primer_from_the_vi_prompt_setting(self):
        rig = Rig(self, mode='dub', policy=lambda engine, i: engine == 'voxcpm2')
        rig.run()
        self.assertEqual(rig.tasks('gen')[0]['prompt']['text'], 'đoạn mồi')
        rig.settings.vi_prompt = str(rig.dir / 'missing.json')
        shutil.rmtree(rig.dir / 'lines'); (rig.dir / 'state.json').unlink()
        with self.assertRaisesRegex(p.NeedsReview, 'vi-prompt'):
            rig.run()

    def test_cache_key_differs_by_engine(self):
        rig = Rig(self, texts=('Xin chào',))
        with self.assertRaises(p.NeedsReview):
            rig.run()
        omni, vox = rig.tasks('gen_omni')[0], rig.tasks('gen')[0]
        self.assertEqual((omni['params']['engine'], vox['params']['engine']), ('omnivoice', 'voxcpm2'))
        self.assertNotEqual(omni['key'], vox['key'])
        params = dict(omni['params'])
        self.assertNotEqual(p.cache_key(params), p.cache_key(dict(params, engine='voxcpm2')))
        self.assertNotEqual(p.cache_key(params), p.cache_key(dict(params, num_step=params['num_step'] + 1)))

    def test_budgets_follow_max_takes_then_fallback_takes(self):
        rig = Rig(self, texts=('Xin chào',))
        rig.settings.max_takes, rig.settings.fallback_takes = 10, 8
        with self.assertRaises(p.NeedsReview):
            rig.run()
        self.assertEqual([c[2] for c in rig.calls if c[0] == 'gen_omni'], [4, 8, 10])
        self.assertEqual([c[2] for c in rig.calls if c[0] == 'gen'], [4, 8])
        self.assertEqual(p.take_rounds(0), [])

    def test_omnivoice_is_skipped_for_a_reference_without_transcript(self):
        rig = Rig(self, mode='dub', policy=lambda engine, i: True)
        original = rig.stage
        def no_text(name, directory, *a, **k):
            original(name, directory, *a, **k)
            if name == 'refs':
                p.write(directory / 'speaker-refs.json', dict(A=dict(path=str(directory / 'ref.wav'), text='', hash='x')))
        with patch.object(p, 'probe', return_value=dict(duration=4, width=320, height=240)), patch.object(p, 'engine', side_effect=no_text):
            p.synthesize(rig.dir, rig.settings, lambda *a: None)
        self.assertEqual({c[0] for c in rig.calls} - {'refs'}, {'gen', 'pick'})


class FailureTests(unittest.TestCase):
    def test_both_engines_failing_needs_review_naming_the_lines(self):
        rig = Rig(self, texts=('Một', 'Hai', 'Ba'), policy=lambda engine, i: i == 1)
        with self.assertRaises(p.NeedsReview) as caught:
            rig.run()
        message = str(caught.exception)
        self.assertIn('dòng 1, 3', message)
        self.assertNotIn('2,', message.split('dòng')[1].split('bằng')[0])
        report = p.read(rig.dir / 'voice-report.json')  # the report is kept for the failed run too
        self.assertEqual([line['engine'] for line in report['lines']], [None, 'omnivoice', None])
        self.assertFalse((rig.dir / 'manifest.json').exists())


class CrashIsolationTests(unittest.TestCase):
    def test_a_crashed_primary_does_not_stop_the_fallback(self):
        rig = Rig(self, crash={'gen_omni'}, policy=lambda engine, i: engine == 'voxcpm2')
        rig.run()
        self.assertEqual(rig.calls, [('gen_omni', [0, 1], 4), ('gen', [0, 1], 4), ('pick', [0, 1], 4)])  # the crashed engine is not retried
        report = p.read(rig.dir / 'voice-report.json')
        self.assertEqual([line['engine'] for line in report['lines']], ['voxcpm2', 'voxcpm2'])
        self.assertIn('gen_omni', report['errors']['omnivoice'])
        self.assertEqual([row['engine'] for row in p.read(rig.dir / 'manifest.json')['lines']], ['voxcpm2', 'voxcpm2'])

    def test_a_crashed_fallback_keeps_the_primary_takes(self):
        rig = Rig(self, mode='dub', crash={'gen_omni'}, policy=lambda engine, i: engine == 'voxcpm2' and i == 0)
        with self.assertRaises(p.NeedsReview) as caught:
            rig.run()
        self.assertIn('dòng 2', str(caught.exception))
        self.assertEqual([line['engine'] for line in p.read(rig.dir / 'voice-report.json')['lines']], ['voxcpm2', None])

    def test_both_crashing_names_both_causes_in_vietnamese(self):
        rig = Rig(self, crash={'gen_omni', 'gen'})
        with self.assertRaises(p.NeedsReview) as caught:
            rig.run()
        message = str(caught.exception)
        self.assertIn('dòng 1, 2', message)
        self.assertIn('omnivoice: Bước gen_omni không khả dụng', message)
        self.assertIn('voxcpm2: Bước gen không khả dụng', message)
        self.assertIn('Đã thử: omnivoice rồi voxcpm2', message)

    def test_message_names_only_the_engines_that_ran(self):
        rig = Rig(self, texts=('Xin chào',))
        rig.settings.fallback_takes = 0
        with self.assertRaises(p.NeedsReview) as caught:
            rig.run()
        message = str(caught.exception)
        self.assertIn('Đã thử: omnivoice.', message)
        self.assertNotIn('voxcpm2', message)
        self.assertNotIn('Lỗi', message)

    def test_cancellation_is_not_swallowed_as_an_engine_failure(self):
        rig = Rig(self)
        def cancel(name, *a, **k):
            raise p.Cancelled('Pipeline cancelled')
        with patch.object(p, 'probe', return_value=dict(duration=4, width=320, height=240)), patch.object(p, 'engine', side_effect=cancel):
            with self.assertRaises(p.Cancelled):
                p.synthesize(rig.dir, rig.settings, lambda *a: None)


class DubReferenceTests(unittest.TestCase):
    def test_short_or_quiet_speaker_reference_skips_omnivoice_and_says_so(self):
        for label, kwargs, reason in (('short', dict(ref_seconds=1.2), 'chỉ dài'), ('quiet', dict(ref_amplitude=100), 'quá nhỏ')):
            with self.subTest(label):
                rig = Rig(self, mode='dub', texts=('Xin chào',), **kwargs)
                with self.assertRaises(p.NeedsReview) as caught:
                    rig.run()
                self.assertNotIn('gen_omni', [c[0] for c in rig.calls])
                self.assertIn('Đã thử: voxcpm2.', str(caught.exception))
                line = p.read(rig.dir / 'voice-report.json')['lines'][0]
                self.assertIn(reason, line['skipped']['omnivoice'])
                self.assertEqual(line['takes']['omnivoice'], 0)

    def test_usable_reference_keeps_omnivoice_and_reports_no_skip(self):
        rig = Rig(self, mode='dub', texts=('Xin chào',), policy=lambda engine, i: engine == 'omnivoice')
        rig.run()
        line = p.read(rig.dir / 'voice-report.json')['lines'][0]
        self.assertNotIn('skipped', line)
        self.assertEqual(line['engine'], 'omnivoice')

    def test_missing_transcript_is_reported_as_skipped(self):
        rig = Rig(self, mode='dub', texts=('Xin chào',))
        original = rig.stage
        def no_text(name, directory, *a, **k):
            original(name, directory, *a, **k)
            if name == 'refs':
                p.write(directory / 'speaker-refs.json', dict(A=dict(path=str(directory / 'ref.wav'), text='', hash='x')))
        with patch.object(p, 'probe', return_value=dict(duration=4, width=320, height=240)), patch.object(p, 'engine', side_effect=no_text):
            with self.assertRaises(p.NeedsReview):
                p.synthesize(rig.dir, rig.settings, lambda *a: None)
        self.assertIn('lời gốc', p.read(rig.dir / 'voice-report.json')['lines'][0]['skipped']['omnivoice'])


class SettingsWiringTests(unittest.TestCase):
    def test_saved_take_budgets_reach_the_settings_synthesize_reads(self):
        from dubflow.config import Settings
        from dubflow.preferences import effective_settings, Preferences
        class Store:
            def get_record(self, kind, name): return dict(max_takes=12, fallback_takes=0)
            def put_record(self, *a): pass
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            cfg = effective_settings(Store(), Settings(data_dir=Path(d)))
            self.assertEqual((cfg.max_takes, cfg.fallback_takes), (12, 0))
            self.assertEqual(Preferences(output_dir=str(Path(d).resolve())).fallback_takes, 8)  # default

    def test_budget_of_zero_disables_the_fallback(self):
        rig = Rig(self, texts=('Xin chào',))
        rig.settings.max_takes, rig.settings.fallback_takes = 4, 0
        with self.assertRaises(p.NeedsReview):
            rig.run()
        self.assertEqual({c[0] for c in rig.calls}, {'gen_omni', 'pick'})

    def test_preferences_validate_the_range(self):
        from dubflow.preferences import Preferences
        for bad in (-1, 25):
            with self.assertRaises(ValueError):
                Preferences(output_dir=str(p.ROOT), fallback_takes=bad)
        self.assertEqual(Preferences(output_dir=str(p.ROOT), fallback_takes=0).fallback_takes, 0)


class VoiceRefreshTests(unittest.TestCase):
    def rig(self):
        import json
        rig = Rig(self, voice_ref=dict(path='ref.wav', text='reference', hash='stale'), policy=lambda engine, i: True)
        voices = rig.dir / 'voices'
        voices.mkdir()
        tone_wav(voices / 'v.wav')
        (voices / 'v.json').write_text(json.dumps(dict(ref_audio=str(voices / 'v.wav'), ref_text='lời mẫu', num_step=64, pronounce={'KOC': 'cây ô ci'})), encoding='utf-8')
        p.write(rig.dir / 'job.json', dict(p.read(rig.dir / 'job.json'), voice_id='system-v'))
        rig.settings.system_voices, rig.settings.data_dir = voices, rig.dir / 'data'
        return rig

    def test_tm_rereads_the_voice_and_keeps_job_and_manifest_in_step(self):
        rig = self.rig()
        p.write(rig.dir / 'cues.json', [dict(id='1', start=0, end=1, speaker='A', original='x', text='Anh KOC')])
        rig.run()
        omni = rig.tasks('gen_omni')[0]['params']
        self.assertEqual((omni['num_step'], omni['text']), (64, 'Anh cây ô ci'))
        job = p.read(rig.dir / 'job.json')
        self.assertEqual(job['voice_ref']['omni'], dict(num_step=64))
        self.assertEqual(job['voice_ref']['text'], 'lời mẫu')
        manifest = p.read(rig.dir / 'manifest.json')
        self.assertEqual(manifest['voice_ref'], job['voice_ref'])
        # the worker rewrites job.json from the store (stale record) before each task; context() still hands render the fresh one
        p.write(rig.dir / 'job.json', dict(job, voice_ref=dict(path='ref.wav', text='reference', hash='stale')))
        with patch.object(p, 'probe', return_value=dict(duration=4, width=320, height=240)):
            self.assertEqual(p.context(rig.dir, rig.settings)[1]['voice_ref'], manifest['voice_ref'])

    def test_without_voice_id_or_a_found_voice_the_stored_record_is_used(self):
        rig = Rig(self, policy=lambda engine, i: True)  # SimpleNamespace settings, no voice_id
        rig.run()
        self.assertEqual(p.read(rig.dir / 'job.json')['voice_ref'], dict(path='ref.wav', text='reference', hash='ignored'))
        rig = self.rig()
        rig.settings.system_voices = rig.dir / 'nowhere'  # voice not found: keep the stored record
        rig.run()
        self.assertEqual(p.read(rig.dir / 'job.json')['voice_ref']['hash'], 'stale')


class ReportTests(unittest.TestCase):
    def test_voice_report_lists_engine_takes_and_short_rule_per_line(self):
        rig = Rig(self, policy=lambda engine, i: (engine, i) in {('omnivoice', 0), ('voxcpm2', 1)})
        original = rig.stage
        def mark_short(name, directory, settings, payload, **kwargs):
            original(name, directory, settings, payload, **kwargs)
            if name == 'pick':
                state = p.read(directory / 'state.json')
                for entry in state.values():
                    if entry.get('accepted', {}).get('engine') == 'voxcpm2':
                        entry['accepted']['short_rule'] = True
                p.write(directory / 'state.json', state)
        with patch.object(p, 'probe', return_value=dict(duration=4, width=320, height=240)), patch.object(p, 'engine', side_effect=mark_short):
            p.synthesize(rig.dir, rig.settings, lambda *a: None)
        report = p.read(rig.dir / 'voice-report.json')
        self.assertEqual(report['order'], ['omnivoice', 'voxcpm2'])
        self.assertEqual(report['lines'], [
            dict(id='1', line=1, engine='omnivoice', takes=dict(omnivoice=4, voxcpm2=0), short_rule=False),
            dict(id='2', line=2, engine='voxcpm2', takes=dict(omnivoice=8, voxcpm2=4), short_rule=True)])


class PronounceTests(unittest.TestCase):
    VOICE = dict(path='ref.wav', text='reference', hash='ignored', pronounce={'KOC': 'cây ô ci', 'GMV': 'gi em vi'},
                 omni=dict(num_step=64, speed=1.1))

    def test_map_is_whole_word_and_case_sensitive(self):
        mapping = {'KOC': 'cây ô ci', 'KO': 'ka ô'}
        self.assertEqual(p.apply_pronounce('KOC, KOCS, koc, xKOC và KO.', mapping), 'cây ô ci, KOCS, koc, xKOC và ka ô.')
        self.assertEqual(p.apply_pronounce('GMV tăng', {}), 'GMV tăng')
        self.assertEqual(p.apply_pronounce('A B', {'A': 'B', 'B': 'C'}), 'B C')  # one pass: replacements are not mapped again

    def test_engine_text_is_pronounced_but_the_cue_text_is_not(self):
        text = 'Anh KOC bán GMV cao'
        rig = Rig(self, texts=(text,), voice_ref=self.VOICE, policy=lambda engine, i: True)
        rig.run()
        task = rig.tasks('gen_omni')[0]
        self.assertEqual(task['params']['text'], 'Anh cây ô ci bán gi em vi cao')
        self.assertEqual(task['cue']['text'], text)
        self.assertEqual(p.read(rig.dir / 'cues.json')[0]['text'], text)
        self.assertEqual(p.read(rig.dir / 'manifest.json')['input_cues'][0]['text'], text)

    def test_voice_settings_reach_the_omnivoice_params_and_the_fallback_text_too(self):
        rig = Rig(self, texts=('Anh KOC',), voice_ref=self.VOICE)
        with self.assertRaises(p.NeedsReview):
            rig.run()
        params = rig.tasks('gen_omni')[0]['params']
        self.assertEqual((params['num_step'], params['speed'], params['guidance_scale'], params['denoise']), (64, 1.1, 2., True))
        self.assertEqual(rig.tasks('gen')[0]['params']['text'], 'Anh cây ô ci')

    def test_voice_json_fields_reach_the_job_voice_ref(self):
        from dubflow.voices import voice_ref
        base = dict(ref_audio=str(Path(__file__)), ref_text='t')
        self.assertEqual(set(voice_ref(base)), {'path', 'text', 'hash'})  # unchanged for voices without engine settings
        full = voice_ref(dict(base, omni=dict(num_step=64), pronounce={'KOC': 'cây ô ci'}))
        self.assertEqual((full['omni'], full['pronounce']), (dict(num_step=64), {'KOC': 'cây ô ci'}))

    def test_system_voice_file_provides_omnivoice_settings_and_pronounce(self):
        import json
        from dubflow.voices import all_voices
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            d = Path(d)
            silent_wav(d / 'v.wav')
            (d / 'v.json').write_text(json.dumps(dict(ref_audio=str(d / 'v.wav'), ref_text='t', num_step=64, speed=1.0, denoise=True, pronounce={'KOC': 'cây ô ci'}, language='vi')), encoding='utf-8')
            voice = all_voices(SimpleNamespace(system_voices=d, data_dir=d / 'none'))[0]
            self.assertEqual(voice['omni'], dict(num_step=64, speed=1.0, denoise=True))
            self.assertEqual(voice['pronounce'], {'KOC': 'cây ô ci'})


class PrepareTests(unittest.TestCase):
    def prepare_calls(self, mode):
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory = Path(d)
            (directory / 'source.mp4').write_bytes(b'src')
            (directory / 'vocals.wav').write_bytes(b'v'); (directory / 'background.wav').write_bytes(b'b')
            p.write(directory / 'job.json', dict(source_path='source.mp4', mode=mode))
            p.write(directory / 'regions.json', []); p.write(directory / 'ocr-complete.json', {})
            p.write(directory / 'cues.json', [dict(id='u', start=0, end=1, speaker='s', original='x', text='y')])
            p.write(directory / 'subtrack.json', dict(version=1, fps=10, band=[1, 2], segments=[]))
            calls = []
            with patch.object(p, 'probe', return_value=dict(duration=5, width=320, height=240)), patch.object(p, 'engine', side_effect=lambda name, *a, **k: calls.append(name)):
                try:
                    p.prepare(directory, SimpleNamespace(ocr_python=sys.executable, speaker_python=sys.executable), lambda *a: None)
                except p.NeedsReview:
                    pass
            return calls

    def test_tm_prepare_does_not_group_speakers(self):
        self.assertNotIn('speakers', self.prepare_calls('tm'))

    def test_dub_prepare_still_groups_speakers(self):
        self.assertIn('speakers', self.prepare_calls('dub'))


class EngineStageTests(unittest.TestCase):
    def run_stage(self, code=0):
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory = Path(d)
            seen = {}
            def popen(cmd, **kwargs):
                seen.update(cmd=cmd, env=kwargs['env'])
                return object()
            settings = SimpleNamespace(asr_python=sys.executable, tts_python='tts-missing')
            with patch.object(p.subprocess, 'Popen', side_effect=popen), patch.object(p, 'wait_owned', return_value=code):
                try:
                    p.engine('gen_omni', directory, settings, dict(tasks=[], count=4))
                finally:
                    seen['dir'] = directory
            return seen

    def test_gen_omni_uses_the_omnivoice_python_offline_with_job_local_temp(self):
        seen = self.run_stage()
        self.assertEqual((seen['cmd'][0], seen['cmd'][2]), (sys.executable, 'gen_omni'))
        env = seen['env']
        self.assertEqual((env['HF_HUB_OFFLINE'], env['TRANSFORMERS_OFFLINE']), ('1', '1'))
        for name in ('TMP', 'TEMP'):
            self.assertEqual(Path(env[name]), seen['dir'] / 'tmp')

    def test_a_failing_stage_points_at_its_log(self):
        with self.assertRaisesRegex(p.NeedsReview, 'gen_omni'):
            self.run_stage(code=1)


def take(seed, duration, similarity=None, exact=True):
    row = dict(path='lines/take.wav', duration=duration, seed=seed, exact=exact, passed=exact, engine='omnivoice')
    if similarity is not None:
        row['similarity'] = similarity
    return row


class ChooseTakeTests(unittest.TestCase):
    def test_highest_similarity_wins_over_a_better_duration_fit(self):
        best = p.choose_take([take(1, 1.0, .5), take(2, .7, .8)], slot=1.0)
        self.assertEqual(best['seed'], 2)

    def test_ties_within_002_go_to_the_best_duration_fit(self):
        best = p.choose_take([take(1, .6, .80), take(2, .95, .79), take(3, 1.0, .70)], slot=1.0)
        self.assertEqual(best['seed'], 2)

    def test_a_take_longer_than_slot_plus_03_does_not_fit(self):
        self.assertEqual(p.choose_take([take(1, 1.5, .8), take(2, 1.25, .8)], slot=1.0)['seed'], 2)  # 1.25 fits, 1.5 does not
        self.assertEqual(p.choose_take([take(1, 2.0, .8), take(2, 1.6, .8)], slot=1.0)['seed'], 2)  # none fits: the shortest

    def test_failing_takes_are_never_chosen(self):
        self.assertEqual(p.choose_take([take(1, 1., .99, exact=False), take(2, 1., .1)], slot=1.)['seed'], 2)
        self.assertIsNone(p.choose_take([take(1, 1., .99, exact=False)], slot=1.))

    def test_missing_scores_fall_back_to_duration_only(self):
        self.assertEqual(p.choose_take([take(1, .6, .9), take(2, 1.0)], slot=1.0)['seed'], 2)


class SimilarityPipelineTests(unittest.TestCase):
    def rig(self, fail_similarity=False):
        scores = {1000: .5, 1001: .9, 1002: .88}  # seed -> similarity; durations differ so the tie is decided by fit
        durations = {1000: 1.0, 1001: .5, 1002: .95}
        rig = Rig(self, texts=('Xin chào',), policy=lambda engine, i: False, crash=('similarity',) if fail_similarity else ())
        base = rig.stage

        def stage(name, directory, settings, payload, **kwargs):
            base(name, directory, settings, payload, **kwargs)
            if name == 'pick' and payload['tasks']:
                state = p.read(directory / 'state.json', {})
                for task in payload['tasks']:
                    state[task['key']]['takes'] = {str(s): take(s, durations[s]) for s in scores}
                p.write(directory / 'state.json', state)
            if name == 'similarity':
                state = p.read(directory / 'state.json', {})
                for task in payload['tasks']:
                    for s, row in state[task['key']]['takes'].items():
                        row['similarity'] = scores[int(s)]
                p.write(directory / 'state.json', state)
        rig.stage = stage
        return rig

    def test_similarity_runs_after_pick_and_the_pipeline_chooses(self):
        rig = self.rig()
        rig.run()
        self.assertEqual([c[0] for c in rig.calls], ['gen_omni', 'pick', 'similarity'])
        self.assertEqual(rig.payloads[-1][1]['tasks'][0]['ref']['path'], str((rig.dir / 'ref.wav').resolve()))
        manifest = p.read(rig.dir / 'manifest.json')
        self.assertEqual(manifest['lines'][0]['seed'], 1002)  # 0.90 and 0.88 tie; 0.95 s fits the 1 s slot better than 0.5 s

    def test_similarity_failure_falls_back_to_duration_with_a_warning(self):
        rig = self.rig(fail_similarity=True)
        with self.assertLogs('dubflow.pipeline', 'WARNING'):
            rig.run()
        manifest = p.read(rig.dir / 'manifest.json')
        self.assertEqual(manifest['lines'][0]['seed'], 1000)  # 1.0 s is the exact slot, whatever the similarity
        self.assertEqual(len(manifest['warnings']), 1)
        self.assertIn('độ giống giọng', manifest['warnings'][0])

    def test_engine_routes_similarity_to_the_speaker_python(self):
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            seen = []
            fake = types.SimpleNamespace(wait=lambda *a, **k: 0)
            settings = SimpleNamespace(speaker_python=sys.executable, asr_python='asr-missing', tts_python='tts-missing', ocr_python='ocr-missing')
            with patch.object(p.subprocess, 'Popen', side_effect=lambda cmd, **kw: seen.append(cmd) or fake), patch.object(p, 'wait_owned', return_value=0):
                p.engine('similarity', Path(d), settings, dict(tasks=[]))
            self.assertEqual(seen[0][0], sys.executable)
            self.assertEqual(seen[0][2], 'similarity')


class PickTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dubflow'))

    def test_text_match_applies_the_map_to_both_sides(self):
        import engine_cli
        task = dict(cue=dict(text='Anh KOC bán hàng'), params=dict(pronounce={'KOC': 'cây ô ci'}))
        self.assertEqual(engine_cli.text_match(task, 'Anh cây ô ci bán hàng.'), (True, False))
        self.assertEqual(engine_cli.text_match(task, 'Anh KOC bán hàng'), (True, False))
        self.assertEqual(engine_cli.text_match(task, 'Anh cây ô ky bán hàng')[0], False)
        plain = dict(cue=dict(text='Xin chào'), params={})
        self.assertEqual(engine_cli.text_match(plain, 'xin chào!'), (True, False))
        long = dict(cue=dict(text='Xin chào các bạn hôm nay'), params={})
        self.assertFalse(engine_cli.text_match(long, 'xin chao các bạn hôm nay')[0])

    def test_short_line_rule(self):
        import engine_cli
        short = dict(cue=dict(text='Xóa đi ư?'), params={})
        self.assertEqual(engine_cli.text_match(short, 'Xóa đi?'), (True, True))
        self.assertEqual(engine_cli.text_match(short, 'Xóa đi ư'), (True, False))
        self.assertFalse(engine_cli.text_match(short, 'Svá đưa')[0])
        six = dict(cue=dict(text='Hôm nay trời đẹp quá bạn ơi'), params={})
        self.assertEqual(len(p.tokens(six['cue']['text'])), 7)
        self.assertFalse(engine_cli.text_match(six, 'Hôm nay trời đẹp quá bạn ới')[0])
        six = dict(cue=dict(text='Hôm nay trời đẹp quá nhé'), params={})
        self.assertEqual(engine_cli.text_match(six, 'Hôm nay trời đẹp quá nhá'), (False, False))
        self.assertEqual(engine_cli.token_distance(['a', 'b'], ['a', 'c', 'b']), 1)
        self.assertEqual(engine_cli.token_distance([], ['a', 'b']), 2)

    def test_pick_records_the_engine_of_each_take(self):
        import engine_cli
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory = Path(d)
            (directory / 'lines').mkdir()
            params = dict(engine='omnivoice', text='Xin chào')
            task = dict(i=0, key='k', cue=dict(text='Xin chào'), params=params)
            name = p.cache_key(dict(params, seed=1000))
            (directory / 'lines' / f'{name}.wav').write_bytes(b'wav')
            asr = lambda audio, generate_kwargs=None: dict(text='Xin chào')
            fake_sf = types.SimpleNamespace(info=lambda path: SimpleNamespace(frames=24000, samplerate=48000))
            def fake_run(cmd, **kwargs):
                Path(cmd[-1]).write_bytes(b'trimmed')
            with patch.dict(sys.modules, soundfile=fake_sf), patch.object(engine_cli, 'load_asr', return_value=asr), \
                    patch.object(engine_cli, 'decode', return_value=b''), patch.object(engine_cli, 'run', side_effect=fake_run):
                engine_cli.pick(directory, dict(tasks=[task], count=1, ffmpeg='ffmpeg'))
            take = p.read(directory / 'state.json')['k']['takes']['1000']
            self.assertEqual((take['engine'], take['exact'], take['short_rule']), ('omnivoice', True, False))
            self.assertEqual((take['passed'], take['heard']), (True, 'Xin chào'))
            self.assertNotIn('accepted', p.read(directory / 'state.json')['k'])  # the pipeline chooses, not pick

    def test_main_dispatches_gen_omni_through_the_stage_map(self):
        import engine_cli
        self.assertIs(engine_cli.STAGES['gen_omni'], engine_cli.gen_omni)
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory = Path(d)
            p.write(directory / 'req.json', dict(tasks=[], count=4))
            seen = []
            stub = lambda folder, request: seen.append((folder, request))
            with patch.dict(engine_cli.STAGES, gen_omni=stub), patch.object(sys, 'argv', ['engine_cli.py', 'gen_omni', str(directory), str(directory / 'req.json')]):
                engine_cli.main()
            self.assertEqual(seen, [(directory, dict(tasks=[], count=4))])
            self.assertEqual(p.read(directory / 'runtime-metrics.json')[0]['stage'], 'gen_omni')


if __name__ == '__main__':
    unittest.main()
