"""Review of dot12: Japanese/Korean/English sources, fragments across clusters, audit robustness, stable dismiss keys,
stale SRT preview."""
import os
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from dubflow import manual_translation
from dubflow.app import create_app
from dubflow.config import Settings
from dubflow.media import atomic_json, read_json
from dubflow.source_audit import audit_cues
from dubflow.subtitle_lines import clean_ocr_segments, is_chinese_text


def seg(s, e, text, region=0, cluster=0, box=(300, 665, 1000, 700), **extra):
    return dict(s=s, e=e, text=text, region=region, cluster=cluster, box=list(box), orientation='h', **extra)


class ScriptDetectionTest(unittest.TestCase):
    def test_is_chinese_text(self):
        self.assertTrue(is_chinese_text(['你好吗朋友', 'KEIN', '再见了朋友']))
        self.assertFalse(is_chinese_text(['Hello there', 'See you soon', '谢', 'Good night', 'Thanks']))
        self.assertFalse(is_chinese_text(['そうですね', '今日は雨が降るでしょう', 'ありがとうございます', 'はい']))
        self.assertFalse(is_chinese_text([]))

    def test_japanese_kana_only_lines_survive(self):
        segs = [seg(1, 3, '今日は雨が降るでしょう'), seg(4, 6, 'そうですね'), seg(7, 9, 'ありがとうございます')]
        stats = {}
        out = clean_ocr_segments(segs, [], stats)
        self.assertEqual([s['text'] for s in out], [s['text'] for s in segs])
        self.assertNotIn('dropped_ocr', stats)

    def test_english_video_with_one_stray_han_character_keeps_its_lines(self):
        segs = [seg(1, 3, 'Where are you going'), seg(4, 6, '你'), seg(7, 9, 'I am coming with you'), seg(10, 12, 'Wait for me')]
        out = clean_ocr_segments(segs, [], {})
        self.assertEqual(len(out), 4)


class FragmentClusterTest(unittest.TestCase):
    def test_a_fragment_of_one_cluster_is_not_folded_into_a_line_of_another_cluster(self):
        left = seg(10.0, 10.2, '我睁', cluster=0, box=(100, 600, 200, 640))
        right = seg(10.4, 12.0, '我睁开眼睛看见了你', cluster=1, box=(700, 600, 1100, 640))
        out = clean_ocr_segments([left, right], [], {})
        self.assertEqual(len(out), 2)
        self.assertTrue(out[0].get('source_uncertain'))

    def test_the_same_cluster_still_folds(self):
        left = seg(10.0, 10.2, '我睁', cluster=0)
        line = seg(10.4, 12.0, '我睁开眼睛看见了你', cluster=0)
        out = clean_ocr_segments([left, line], [], {})
        self.assertEqual([s['text'] for s in out], ['我睁开眼睛看见了你'])


class AuditRobustnessTest(unittest.TestCase):
    def test_missing_and_null_fields_do_not_crash(self):
        cues = [dict(id='a', start=1, end=2, original=None), dict(id='b', start=None, end=3, original='你好'),
                dict(id='c', start=3, end=4), dict(id='d', start=5, end=7, original='你好吗朋友们')]
        found = audit_cues(cues, None)
        self.assertEqual([f['code'] for f in found if f['severity'] == 'error'], [])

    def test_music_note_and_empty_original_are_not_junk(self):
        cues = [dict(id='a', start=1, end=3, original='你好吗朋友们'), dict(id='n', start=4, end=6, original='♪♪', kind='music'),
                dict(id='m', start=7, end=9, original='ABC'), dict(id='e', start=10, end=12, original=''),
                dict(id='k', start=13, end=15, original='再见了朋友们')]
        codes = [(f['code'], f['cue_ids']) for f in audit_cues(cues, 20)]
        self.assertEqual([c for c in codes if c[0] == 'NO_CJK'], [('NO_CJK', ['m'])])

    def test_japanese_video_has_no_no_cjk_findings(self):
        cues = [dict(id='a', start=1, end=3, original='今日は雨が降るでしょう'), dict(id='b', start=4, end=6, original='そうですね')]
        self.assertFalse([f for f in audit_cues(cues, 20) if f['code'] == 'NO_CJK'])


class Base(unittest.TestCase):
    CUES = [
        dict(id='a', start=1.0, end=3.0, original='你好吗朋友', text='', speaker='s'),
        dict(id='b', start=6.0, end=8.0, original='再见了朋友', text='', speaker='s'),
        dict(id='c', start=9.0, end=11.0, original='谢谢大家', text='', speaker='s'),
    ]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        settings = Settings(data_dir=Path(self.tmp.name), system_voices=Path(self.tmp.name) / 'system')
        self.app = create_app(settings, start_worker=False)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.job = self.app.state.store.create_job({'title': 'm', 'mode': 'vietsub'})
        self.app.state.store.update_job(self.job['id'], duration=20.0)
        self.folder = settings.jobs_dir / self.job['id']
        self.folder.mkdir(exist_ok=True)
        atomic_json(self.folder / 'cues.json', [dict(c) for c in self.CUES])
        self.base = f"/api/jobs/{self.job['id']}"

    def upload(self, path, text):
        return self.client.post(self.base + path, files={'file': ('vi.srt', text.encode('utf-8'), 'application/x-subrip')})

    def errors(self):
        return self.client.get(self.base + '/errors').json()['items']


class DismissStabilityTest(Base):
    def test_dismissed_translation_error_returns_when_the_cue_fails_again(self):
        atomic_json(self.folder / 'translation-failed.json', ['a'])
        first = [i for i in self.errors() if i['key'].startswith('tr:a:')]
        self.assertEqual(len(first), 1)
        self.client.post(self.base + '/errors/dismiss', json={'key': first[0]['key']})
        self.assertFalse([i for i in self.errors() if i['key'].startswith('tr:a:')])
        path = self.folder / 'translation-failed.json'  # a later run fails the same cue again
        later = time.time() + 5
        atomic_json(path, ['a'])
        os.utime(path, (later, later))
        again = [i for i in self.errors() if i['key'].startswith('tr:a:')]
        self.assertEqual(len(again), 1)
        self.assertNotEqual(again[0]['key'], first[0]['key'])

    def test_dismissed_audit_finding_does_not_hide_other_content_with_the_same_ids(self):
        cues = [dict(c) for c in self.CUES] + [dict(id='x', start=12.0, end=13.0, original='KEIN', text='')]
        atomic_json(self.folder / 'cues.json', cues)
        audit = lambda: [i for i in self.errors() if i['kind'] == 'audit' and i['code'] == 'NO_CJK']
        first = audit()
        self.assertEqual(len(first), 1)
        self.client.post(self.base + '/errors/dismiss', json={'key': first[0]['key']})
        self.assertFalse(audit())
        cues[-1]['original'] = 'ABCD'  # a new analysis reuses the id for different junk
        atomic_json(self.folder / 'cues.json', cues)
        self.assertEqual(len(audit()), 1)


class StalePreviewTest(Base):
    SRT = '1\n00:00:01,000 --> 00:00:03,000\nMột\n\n2\n00:00:06,000 --> 00:00:08,000\nHai\n\n3\n00:00:50,000 --> 00:00:51,000\nLạc\n'

    def test_commit_with_fingerprint_of_the_preview_works(self):
        p = self.upload('/translation-srt/preview', self.SRT).json()
        self.assertTrue(p['fingerprint'])
        r = self.client.post(self.base + '/translation-srt/commit', json={'assignments': {'a': 'Một'}, 'fingerprint': p['fingerprint']})
        self.assertEqual(r.status_code, 200, r.text)

    def test_commit_after_the_cues_changed_is_refused_and_writes_nothing(self):
        p = self.upload('/translation-srt/preview', self.SRT).json()
        cues = [dict(c) for c in self.CUES]
        cues[0]['original'] = '完全不同的话'  # re-analysis reuses the id 'a' for another line
        atomic_json(self.folder / 'cues.json', cues)
        r = self.client.post(self.base + '/translation-srt/commit', json={'assignments': {'a': 'Một'}, 'fingerprint': p['fingerprint']})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(read_json(self.folder / 'cues.json')[0]['text'], '')

    def test_fingerprint_ignores_vietnamese_edits(self):
        a = manual_translation.dialogue_fingerprint(self.CUES)
        b = manual_translation.dialogue_fingerprint([dict(c, text='Đã sửa') for c in self.CUES])
        self.assertEqual(a, b)

    def test_numbering_that_points_to_a_far_away_cue_is_flagged(self):
        srt = '1\n00:00:30,000 --> 00:00:31,000\nMột\n\n2\n00:00:40,000 --> 00:00:41,000\nHai\n\n3\n00:00:50,000 --> 00:00:51,000\nBa\n'
        p = self.upload('/translation-srt/preview', srt).json()
        self.assertEqual(p['mode'], 'index')
        self.assertTrue(all('big_shift' in r['issues'] for r in p['rows']))

    def test_clean_index_import_has_no_problem(self):
        srt = '1\n00:00:01,000 --> 00:00:03,000\nMột\n\n2\n00:00:06,100 --> 00:00:08,000\nHai\n\n3\n00:00:09,000 --> 00:00:11,000\nBa\n'
        p = self.upload('/translation-srt/preview', srt).json()
        self.assertEqual((p['mode'], p['problems']), ('index', 0))


if __name__ == '__main__':
    unittest.main()
