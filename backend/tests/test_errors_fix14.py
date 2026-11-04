import tempfile
import unittest
from pathlib import Path

from dubflow import errors_store, review, translation_history
from dubflow.pipeline import read, write


class Fix14Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.cues = [dict(id='a', start=1, end=3, original='你好朋友', text='Xin chào'),
                     dict(id='b', start=4, end=4.2, original='我就想把', text='Ta muốn')]
        write(self.folder/'cues.json', self.cues)
        self.state = review.load_state(self.folder)
        self.job = dict(mode='vietsub', duration=10)

    def test_quality_warnings_stay_in_chips_only(self):
        codes = ['TRANSLATION_STALE', 'SOURCE_MISMATCH', 'READ_TOO_FAST', 'ADDRESS_UNCONFIRMED',
                 'READABILITY', 'OCR_ASR_MISMATCH', 'ASR_OCR_CONFLICT', 'ASR_PARTIAL',
                 'TOO_SHORT_FOR_TEXT', 'FRAGMENT', 'UNCONFIRMED_SHORT']
        write(self.folder/'cues.json', self.cues[:1])
        report = dict(flags=[dict(id=code, code=code, cue_ids=['a'], severity='warn', message=code)
                             for code in codes], reasons=[])
        data = errors_store.collect(self.folder, self.job, report)
        self.assertEqual(data['items'], [])
        self.assertEqual({f['code'] for f in data['cue_flags']['a']}, set(codes))

    def test_keeps_overflow_source_errors_and_every_export_blocker(self):
        write(self.folder/'cues.json', self.cues[:1])
        report = dict(flags=[dict(id='long', code='LINES_OVERFLOW', cue_ids=['a'], severity='review', message='long'),
                             dict(id='bad', code='INVALID_TIME', cue_ids=['a'], severity='error', message='bad'),
                             dict(id='gone', code='SOURCE_MISSING', cue_ids=['gone'], severity='error', message='gone')],
                      reasons=[dict(code='INVALID_TIME', cue_ids=['a'], message='bad'),
                               dict(code='SOURCE_MISSING', cue_ids=['gone'], message='gone'),
                               dict(code='MISSING_SOURCE', cue_ids=[], message='file missing')])
        data = errors_store.collect(self.folder, self.job, report)
        self.assertEqual(data['count'], 4)
        self.assertEqual(len([i for i in data['items'] if i['kind']=='blocking']), 3)

    def test_proven_deletion_does_not_stale_unchanged_translations(self):
        self._translated_then_deleted(legacy=True)
        before = (self.folder/'review-state.json').read_bytes()
        self.assertEqual(self._stale(), [])
        self.assertEqual((self.folder/'review-state.json').read_bytes(), before)

    def test_explicit_deletion_does_not_stale_unchanged_translations(self):
        self._translated_then_deleted(legacy=False)
        self.assertEqual(self._stale(), [])

    def test_deletion_does_not_hide_real_source_role_context_or_terms_changes(self):
        self._translated_then_deleted(legacy=True)
        for field, value in [('original', '真正改了'), ('speaker', 'new'), ('start', 1.2)]:
            with self.subTest(field=field):
                write(self.folder/'cues.json', [dict(self.cues[0], **{field: value})])
                self.assertEqual(self._stale(), ['a'])
        write(self.folder/'cues.json', self.cues[:1])
        self.assertEqual(self._stale(dict(self.job, review_terms='new term')), ['a'])
        state=read(self.folder/'review-state.json')
        write(self.folder/'review-state.json', dict(state, scene_context='new context'))
        self.assertEqual(self._stale(), ['a'])

    def test_retranslation_between_two_deletions_does_not_stale_survivors(self):
        self.cues.append(dict(id='c', start=6, end=8, original='谢谢朋友', text='Cảm ơn'))
        write(self.folder/'cues.json', self.cues)
        self.state=review.replace_source(self.folder, self.cues)
        self._stamp()
        review.record_deleted_sources(self.folder, [self.cues[1]])
        surviving=[self.cues[0], self.cues[2]]
        write(self.folder/'cues.json', surviving)
        state=review.load_state(self.folder)
        surviving[0]['translation_dependency']=review.translation_dependency(surviving[0], state, surviving)
        write(self.folder/'cues.json', surviving)
        review.record_deleted_sources(self.folder, [self.cues[2]])
        write(self.folder/'cues.json', surviving[:1])
        self.assertEqual(self._stale(), [])

    def test_unproven_missing_cue_still_stales_and_blocks(self):
        self._stamp()
        write(self.folder/'cues.json', self.cues[:1])
        self.assertEqual(self._stale(), ['a'])
        report = review.quality_report(self.folder, self.job)
        self.assertFalse(report['draft_allowed'])
        self.assertIn('SOURCE_MISSING', [f['code'] for f in report['flags']])

    def test_source_audit_warn_stays_in_chip_but_error_stays_in_tab(self):
        cue=dict(self.cues[0], end=1.2, original='我', source_uncertain=True)
        write(self.folder/'cues.json', [cue])
        data=errors_store.collect(self.folder, self.job)
        self.assertEqual(data['items'], [])
        self.assertIn('FRAGMENT', [f['code'] for f in data['cue_flags']['a']])
        cue.pop('source_uncertain')
        write(self.folder/'cues.json', [cue])
        data=errors_store.collect(self.folder, self.job)
        self.assertEqual([(i['code'], i['severity']) for i in data['items']], [('FRAGMENT', 'error')])

    def test_latest_skipped_srt_block_is_an_error(self):
        write(self.folder/'cues.json', self.cues[:1])
        errors_store.save_import_issues(self.folder, [], [dict(number=9, text='unmatched')])
        data=errors_store.collect(self.folder, self.job)
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['items'][0]['kind'], 'srt')
        errors_store.save_import_issues(self.folder, [], [])
        self.assertEqual(errors_store.collect(self.folder, self.job)['count'], 0)

    def _stamp(self):
        for c in self.cues:
            c['translation_dependency']=review.translation_dependency(c, self.state, self.cues)
        write(self.folder/'cues.json', self.cues)

    def _translated_then_deleted(self, legacy):
        self._stamp()
        if legacy:
            translation_history.save_snapshot(self.folder, self.cues, source='before-delete')
            translation_history.save_snapshot(self.folder, self.cues[:1], source='manual')
        else:
            review.record_deleted_sources(self.folder, self.cues[1:])
        write(self.folder/'cues.json', self.cues[:1])

    def _stale(self, job=None):
        return [cid for f in review.quality_report(self.folder, job or self.job)['flags']
                if f['code']=='TRANSLATION_STALE' for cid in f['cue_ids']]
