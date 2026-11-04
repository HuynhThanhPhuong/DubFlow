"""Mode changes must keep OCR evidence separate from speech recognition."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dubflow import analysis_regions, pipeline as p, review, source_audit


class SourceModesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        (self.folder/'source.mp4').write_bytes(b'video')
        self.cfg = dict(no_hard_subs=False, subtitle=[0, 100, 300, 50], logos=[], screen_text=[])
        self.calls = []

    def run_mode(self, mode, no_hard_subs=False):
        cfg = dict(self.cfg, no_hard_subs=no_hard_subs, subtitle=None if no_hard_subs else self.cfg['subtitle'])
        p.write(self.folder/'job.json', dict(source_path='source.mp4', mode=mode, analysis_regions=cfg))
        self.calls.clear()
        def engine(stage, folder, settings, payload, **kwargs):
            self.calls.append(stage)
            if stage == 'transcribe':
                p.write(folder/'source-asr-cues.json', [dict(id='asr-1', start=1, end=4, original='我家阿晋说得对', speaker='s', text='')])
            elif stage == 'subband':
                p.write(folder/'subtrack.json', dict(version=2, mode='band', box=payload['box'], segments=[
                    dict(s=1, e=4, text='我家阿音说得对', x0=20, y0=110, x1=280, y1=140)]))
        with patch.object(p, 'probe', return_value=dict(duration=8, width=320, height=240)), \
                patch.object(p, 'engine', side_effect=engine), patch.object(p, 'erase_subtitles'), \
                patch.object(p, 'audio_rms', return_value=([0]*400, .02)):
            try:
                p.prepare(self.folder, SimpleNamespace(), lambda *args: None)
            except p.NeedsReview:
                pass
        return p.read(self.folder/'cues.json', [])

    def test_vietsub_ignores_even_existing_asr_and_keeps_screen_timing(self):
        p.write(self.folder/'source-asr-cues.json', [dict(id='a', start=0, end=7, original='错误的声音', speaker='s')])
        cues = self.run_mode('vietsub')
        self.assertNotIn('transcribe', self.calls)
        self.assertEqual([(c['start'], c['end'], c['original'], c['source']) for c in cues], [(1, 4, '我家阿音说得对', 'ocr')])
        self.assertTrue(all('asr_text' not in c and 'source_mismatch' not in c for c in cues))

    def test_dub_lazily_adds_asr_and_reverse_switch_reuses_ocr(self):
        cues = self.run_mode('vietsub')
        cues[0]['text'] = 'A Âm nhà ta nói đúng'
        p.write(self.folder/'cues.json', cues)
        cues = self.run_mode('dub')
        self.assertIn('transcribe', self.calls)
        self.assertNotIn('subband', self.calls)
        self.assertTrue(cues[0]['source_mismatch'])
        self.assertEqual(cues[0]['text'], 'A Âm nhà ta nói đúng')
        cues = self.run_mode('vietsub')
        self.assertNotIn('subband', self.calls)
        self.assertNotIn('transcribe', self.calls)
        self.assertEqual(cues[0]['source'], 'ocr')
        self.assertNotIn('source_mismatch', cues[0])

    def test_no_hard_subs_vietsub_uses_asr(self):
        cues = self.run_mode('vietsub', no_hard_subs=True)
        self.assertIn('transcribe', self.calls)
        self.assertNotIn('subband', self.calls)
        self.assertEqual(cues[0]['source'], 'asr')

    def test_mode_staleness_follows_the_asr_policy(self):
        self.run_mode('vietsub')
        job = p.read(self.folder/'job.json')
        self.assertFalse(p.source_mode_stale(self.folder, job))
        self.assertTrue(p.source_mode_stale(self.folder, dict(job, mode='dub')))
        self.run_mode('tm')
        self.assertFalse(p.source_mode_stale(self.folder, dict(job, mode='dub')))

    def test_mode_switch_keeps_manual_cues_and_deleted_inventory(self):
        cues = self.run_mode('vietsub')
        cues[0].update(id='edited', text='Bản dịch đã sửa', original='我家阿音说得很好')
        manual = dict(id='manual', start=6, end=7, original='手动', text='Thêm tay', source_ids=[])
        p.write(self.folder/'cues.json', cues + [manual])
        result = self.run_mode('tm')
        self.assertEqual({c['id'] for c in result if c.get('source') != 'asr'}, {'edited', 'manual'})
        self.assertEqual(next(c for c in result if c['id'] == 'edited')['original'], '我家阿音说得很好')
        self.assertEqual(next(c for c in result if c['id'] == 'manual')['text'], 'Thêm tay')

    def test_failed_asr_is_retried_on_the_next_prepare(self):
        self.run_mode('tm')
        p.write(self.folder/'asr-failed.json', dict(failed=True))
        self.run_mode('tm')
        self.assertIn('transcribe', self.calls)
        self.assertFalse((self.folder/'asr-failed.json').exists())

    def test_source_cache_cannot_cross_asr_modes(self):
        self.assertNotEqual(analysis_regions.source_key(self.cfg, use_asr=False), analysis_regions.source_key(self.cfg, use_asr=True))
        self.assertFalse(analysis_regions.source_matches(self.cfg, analysis_regions.source_key(self.cfg, use_asr=True), use_asr=False))

    def test_proper_name_disagreement_is_red_even_with_high_sentence_agreement(self):
        c = dict(id='o1', start=1, end=4, original='我家阿音说得对', text='A Âm nhà ta nói đúng', source='ocr+asr',
                 asr_text='我家阿晋说得对', source_agreement=.85)
        findings = source_audit.audit_cues([c], 8, mode='dub')
        mismatch = [f for f in findings if f['code'] == 'OCR_ASR_MISMATCH']
        self.assertEqual(len(mismatch), 1)
        self.assertEqual(mismatch[0]['severity'], 'error')
        self.assertFalse(any(f['code'] == 'OCR_ASR_MISMATCH' for f in source_audit.audit_cues([c], 8, mode='vietsub')))
        p.write(self.folder/'cues.json', [dict(c, source_mismatch=True)])
        for mode in ('dub', 'tm', 'vietsub'):
            report = review.quality_report(self.folder, dict(mode=mode, duration=8))
            flags = [f for f in report['flags'] if f['code'] == 'SOURCE_MISMATCH']
            self.assertEqual([f['severity'] for f in flags], [] if mode == 'vietsub' else ['error'])

    def test_repeated_surname_name_also_detects_a_changed_character(self):
        cues = [dict(id='a', start=0, end=2, original='阿晋你来了', text='A Tấn đến rồi'),
                dict(id='b', start=2, end=4, original='在下大泽山古晋', text='Ta là Cổ Tấn'),
                dict(id='c', start=4, end=7, original='古晋永远不会忘记你', text='Cổ Tấn luôn nhớ nàng',
                     asr_text='古普永远不会忘记你', source_agreement=.9)]
        findings = source_audit.audit_cues(cues, 8, mode='tm')
        mismatch = [f for f in findings if f['code'] == 'OCR_ASR_MISMATCH']
        self.assertEqual([(f['cue_ids'], f['severity']) for f in mismatch], [(['c'], 'error')])
        # A normal changed word outside the supported name is not a name mismatch.
        cues[2].update(asr_text='古晋永远不会记得你', source_agreement=.8)
        self.assertFalse(any(f['code'] == 'OCR_ASR_MISMATCH' for f in source_audit.audit_cues(cues, 8, mode='tm')))

    def test_manual_source_fix_is_not_flagged_by_a_stale_agreement_score(self):
        c = dict(id='fixed', start=0, end=3, original='我家阿音说得对', asr_text='我家阿音说得对', source_agreement=.1)
        self.assertFalse(source_audit.speech_mismatch(c))
