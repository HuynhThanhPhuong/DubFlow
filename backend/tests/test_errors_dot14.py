import tempfile
import unittest
from pathlib import Path

from dubflow import errors_store, review, translation_history
from dubflow.pipeline import read, write


class ActionableErrorsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.cues = [dict(id='a', start=1, end=3, original='你好朋友', text='Xin chào')]
        write(self.folder/'cues.json', self.cues)

    def test_information_moves_to_activity_and_counts_only_actionable_items(self):
        report = dict(reasons=[dict(code='MISSING_SOURCE', cue_ids=[], message='Thiếu tệp nguồn.')],
                      flags=[dict(id='long', code='LINES_OVERFLOW', cue_ids=['a'], severity='review', resolved=False,
                                  message='Câu quá dài. Hãy rút gọn lời Việt.')])
        errors_store.save_import_issues(self.folder, [], [dict(number=9, text='Lạc')])
        data = errors_store.collect(self.folder, dict(warnings=['Đã gộp 3 lời gốc.']), report)
        self.assertEqual(data['count'], 2)
        self.assertEqual(len(data['activity']), 2)
        self.assertTrue(any(i['cue_id']=='a' and 'jump' in i['actions'] for i in data['items']))
        self.assertTrue(any('Thiếu tệp' in i['message'] and 'Hãy' in i['message'] for i in data['items']))
        self.assertFalse(any(i['kind']=='warning' or i['key'].startswith('srt-skip:') for i in data['items']))

    def test_task_failure_without_a_log_remains_visible_with_recovery_instruction(self):
        data = errors_store.collect(self.folder, dict(status='error', stage='rendering', error='Thiếu tệp video.'))
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['items'][0]['kind'], 'task')
        self.assertIn('Hãy', data['items'][0]['message'])

    def test_untranslated_cue_has_a_link_even_without_failed_translation_file(self):
        write(self.folder/'cues.json', [dict(self.cues[0], text='')])
        data = errors_store.collect(self.folder, {})
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['items'][0]['cue_id'], 'a')
        self.assertIn('edit', data['items'][0]['actions'])

    def test_awaiting_review_task_failure_stays_visible(self):
        data=errors_store.collect(self.folder,dict(status='awaiting_review',stage='awaiting_review',
            error='Không tìm thấy file logo đã gắn vào video.'))
        task=[i for i in data['items'] if i['kind']=='task']
        self.assertEqual(len(task),1)
        self.assertIn('Hãy',task[0]['message'])


class DeletedSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.cues = [dict(id='a', start=1, end=3, original='你好朋友', text='Xin chào'),
                     dict(id='b', start=4, end=4.2, original='我就想把', text='Ta muốn')]
        write(self.folder/'cues.json', self.cues)
        self.state = review.load_state(self.folder)

    def test_explicit_deletion_records_source_omission_and_invalidates_approval(self):
        review.record_deleted_sources(self.folder, [self.cues[1]])
        write(self.folder/'cues.json', self.cues[:1])
        report = review.quality_report(self.folder, dict(duration=10, mode='vietsub'))
        self.assertNotIn('SOURCE_MISSING', [f['code'] for f in report['flags']])
        self.assertIn('người dùng', read(self.folder/'review-state.json')['omissions']['b'])

    def test_legacy_before_delete_and_manual_snapshots_repair_only_proven_deletions(self):
        translation_history.save_snapshot(self.folder, self.cues, source='before-delete')
        translation_history.save_snapshot(self.folder, self.cues[:1], source='manual')
        write(self.folder/'cues.json', self.cues[:1])
        report = review.quality_report(self.folder, dict(duration=10, mode='vietsub'))
        self.assertNotIn('SOURCE_MISSING', [f['code'] for f in report['flags']])
        self.assertNotIn('b', read(self.folder/'review-state.json')['omissions'])
        self.assertIn('b', review.load_state(self.folder)['omissions'])

    def test_missing_source_without_deletion_evidence_still_blocks(self):
        write(self.folder/'cues.json', self.cues[:1])
        report = review.quality_report(self.folder, dict(duration=10, mode='vietsub'))
        missing = [f for f in report['flags'] if f['code']=='SOURCE_MISSING']
        self.assertEqual(len(missing), 1)
        self.assertFalse(report['draft_allowed'])
        self.assertIn('Phân tích lại', missing[0]['message'])

    def test_partial_or_edited_manual_snapshot_does_not_authorize_omission(self):
        translation_history.save_snapshot(self.folder, self.cues, source='before-delete')
        translation_history.save_snapshot(self.folder, [dict(self.cues[0], original='Khác')], source='manual')
        write(self.folder/'cues.json', self.cues[:1])
        report = review.quality_report(self.folder, dict(duration=10, mode='vietsub'))
        self.assertIn('SOURCE_MISSING', [f['code'] for f in report['flags']])

    def test_deleting_one_split_cue_keeps_source_covered_by_the_other(self):
        split=[dict(self.cues[0],id='a1',source_ids=['a']),
               dict(self.cues[0],id='a2',source_ids=['a'],start=3,end=4),self.cues[1]]
        write(self.folder/'cues.json',split)
        review.record_deleted_sources(self.folder,[split[0]])
        state=read(self.folder/'review-state.json')
        self.assertNotIn('a',state['omissions'])

    def test_repair_does_not_swallow_a_second_missing_source(self):
        translation_history.save_snapshot(self.folder,self.cues,source='before-delete')
        translation_history.save_snapshot(self.folder,self.cues[:1],source='manual')
        write(self.folder/'cues.json',[])
        report=review.quality_report(self.folder,dict(duration=10,mode='vietsub'))
        self.assertEqual([f['cue_ids'] for f in report['flags'] if f['code']=='SOURCE_MISSING'],[['a']])

    def test_same_clock_tick_deletion_pair_uses_logical_order_not_random_ids(self):
        from unittest.mock import patch
        from datetime import datetime,timezone
        fixed=datetime(2026,11,4,tzinfo=timezone.utc)
        with patch('dubflow.translation_history.datetime') as clock:
            clock.now.return_value=fixed
            translation_history.save_snapshot(self.folder,self.cues,source='before-delete',snapshot_id='f'*32)
            translation_history.save_snapshot(self.folder,self.cues[:1],source='manual',snapshot_id='0'*32)
        write(self.folder/'cues.json',self.cues[:1])
        report=review.quality_report(self.folder,dict(duration=10,mode='vietsub'))
        self.assertNotIn('SOURCE_MISSING',[f['code'] for f in report['flags']])

    def test_three_snapshots_on_one_tick_are_ambiguous_and_keep_blocker(self):
        from unittest.mock import patch
        from datetime import datetime,timezone
        fixed=datetime(2026,11,4,tzinfo=timezone.utc)
        with patch('dubflow.translation_history.datetime') as clock:
            clock.now.return_value=fixed
            translation_history.save_snapshot(self.folder,self.cues,source='before-delete')
            translation_history.save_snapshot(self.folder,self.cues[:1],source='manual')
            translation_history.save_snapshot(self.folder,self.cues,source='manual')
        write(self.folder/'cues.json',self.cues[:1])
        report=review.quality_report(self.folder,dict(duration=10,mode='vietsub'))
        self.assertIn('SOURCE_MISSING',[f['code'] for f in report['flags']])


    def test_reading_proven_deletion_does_not_write_review_state(self):
        translation_history.save_snapshot(self.folder,self.cues,source='before-delete')
        translation_history.save_snapshot(self.folder,self.cues[:1],source='manual')
        write(self.folder/'cues.json',self.cues[:1])
        before=(self.folder/'review-state.json').read_bytes()
        review.public_state(self.folder,dict(mode='vietsub',duration=10))
        review.quality_report(self.folder,dict(mode='vietsub',duration=10))
        self.assertEqual((self.folder/'review-state.json').read_bytes(),before)
        self.assertFalse((self.folder/'review-history').exists())
