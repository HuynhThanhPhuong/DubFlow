import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from dubflow.app import create_app
from dubflow.config import Settings
from dubflow.media import atomic_json, read_json

CUES = [
    dict(id='a', start=1.0, end=3.0, original='你好', text='', speaker='speaker-1'),
    dict(id='song', start=3.0, end=5.0, original='[歌词] 我爱你', text='', speaker='speaker-1', kind='lyrics'),
    dict(id='b', start=6.0, end=8.0, original='再见', text='', speaker='speaker-1'),
    dict(id='c', start=9.0, end=11.0, original='谢谢', text='', speaker='speaker-1'),
]


def srt(*rows, nl='\n'):
    return nl.join(rows).encode('utf-8')


class ManualTranslationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        settings = Settings(data_dir=Path(self.tmp.name), system_voices=Path(self.tmp.name) / 'system')
        self.app = create_app(settings, start_worker=False)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.job = self.app.state.store.create_job({'title': 'm', 'mode': 'vietsub'})
        self.folder = settings.jobs_dir / self.job['id']
        self.folder.mkdir(exist_ok=True)
        atomic_json(self.folder / 'cues.json', [dict(c) for c in CUES])
        self.url = f"/api/jobs/{self.job['id']}/translation-srt"

    def post(self, data):
        return self.client.post(self.url, files={'file': ('vi.srt', data, 'application/x-subrip')})

    def stored(self):
        return {c['id']: c for c in read_json(self.folder / 'cues.json')}

    def test_prompt_mentions_rules_and_mode(self):
        base = f"/api/jobs/{self.job['id']}/translate-prompt"
        r = self.client.get(base + '?mode=vietsub')
        self.assertEqual(r.status_code, 200)
        self.assertIn('text/plain', r.headers['content-type'])
        for phrase in ('Giữ nguyên số thứ tự và dòng thời gian', 'Mỗi khối 1-2 dòng', 'Không gộp hay tách khối', 'đúng định dạng SRT'):
            self.assertIn(phrase, r.text)
        self.assertNotIn('ký tự trên mỗi giây', r.text)
        self.assertNotIn('KHÔNG chuyển thành lời kể', r.text)
        tm = self.client.get(base + '?mode=tm').text
        self.assertIn('KHÔNG chuyển thành lời kể', tm)
        self.assertIn('thời lượng', tm)
        self.assertEqual(self.client.get(base + '?mode=zzz').status_code, 422)

    def test_import_matches_by_index_ignores_times(self):
        r = self.post(srt('1', '00:00:06,000 --> 00:00:08,000', 'Xin chào', '',
                          '2', '00:00:11,000 --> 00:00:13,000', 'Tạm biệt', '',
                          '3', '00:00:14,000 --> 00:00:16,000', 'Cảm ơn'))
        self.assertEqual(r.status_code, 200, r.text)
        s = self.stored()
        self.assertEqual((s['a']['text'], s['b']['text'], s['c']['text']), ('Xin chào', 'Tạm biệt', 'Cảm ơn'))
        self.assertEqual((s['a']['start'], s['a']['end']), (1.0, 3.0))
        self.assertEqual(s['a']['status'], 'needs_review')
        self.assertEqual(len(r.json()['cues']), 4)
        self.assertEqual((r.json()['summary']['mode'], r.json()['summary']['matched'], r.json()['summary']['empty']), ('index', 3, []))

    def test_import_count_mismatch_matches_by_time_and_reports(self):
        r = self.post(srt('1', '00:00:01,100 --> 00:00:02,900', 'Một', '',
                          '2', '00:00:09,000 --> 00:00:11,000', 'Ba'))
        self.assertEqual(r.status_code, 200, r.text)
        sm = r.json()['summary']
        self.assertEqual((sm['mode'], sm['matched'], sm['total'], sm['skipped']), ('time', 2, 3, []))
        self.assertEqual([e['id'] for e in sm['empty']], ['b'])
        self.assertEqual(sm['empty'][0]['number'], 2)
        s = self.stored()
        self.assertEqual((s['a']['text'], s['b']['text'], s['c']['text']), ('Một', '', 'Ba'))

    def test_time_match_uses_largest_overlap_one_block_per_cue_and_skips_extras(self):
        r = self.post(srt('1', '00:00:01,000 --> 00:00:01,800', 'Mảnh', '',
                          '2', '00:00:01,500 --> 00:00:03,000', 'Dài hơn', '',
                          '3', '00:00:20,000 --> 00:00:21,000', 'Lạc', '',
                          '4', '00:00:06,000 --> 00:00:06,500', '', '',
                          '5', '00:00:06,100 --> 00:00:08,000', 'Hai'))
        self.assertEqual(r.status_code, 200, r.text)
        sm = r.json()['summary']
        s = self.stored()
        self.assertEqual(s['a']['text'], 'Dài hơn')
        self.assertEqual(s['b']['text'], 'Hai')
        self.assertEqual(sm['matched'], 2)
        self.assertEqual([b['number'] for b in sm['skipped']], [1, 3])
        self.assertEqual(sm['empty_blocks'], 1)
        self.assertEqual([e['id'] for e in sm['empty']], ['c'])

    def test_time_match_prefers_exact_timing_over_overlap(self):
        r = self.post(srt('1', '00:00:00,500 --> 00:00:03,200', 'Rộng', '',
                          '2', '00:00:01,000 --> 00:00:03,000', 'Đúng'))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.stored()['a']['text'], 'Đúng')

    def test_nothing_matches_422_writes_nothing(self):
        r = self.post(srt('1', '00:01:00,000 --> 00:01:02,000', 'Xa'))
        self.assertEqual(r.status_code, 422)
        self.assertIn('Không ghép được câu nào', r.json()['detail'])
        self.assertEqual(self.stored()['a']['text'], '')

    def test_not_srt_422(self):
        r = self.post('chỉ là một đoạn văn thường'.encode('utf-8'))
        self.assertEqual(r.status_code, 422)

    def test_import_missing_and_duplicate_numbers_fall_back_to_time(self):
        r = self.post(srt('1', '00:00:01,000 --> 00:00:03,000', 'Một', '',
                          '1', '00:00:06,000 --> 00:00:08,000', 'Hai', '',
                          '4', '00:00:09,000 --> 00:00:11,000', 'Ba'))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['summary']['mode'], 'time')
        self.assertEqual(self.stored()['c']['text'], 'Ba')

    def test_import_empty_block_counts_as_no_translation(self):
        r = self.post(srt('1', '00:00:01,000 --> 00:00:02,000', 'Một', '',
                          '2', '00:00:02,000 --> 00:00:03,000', '', '',
                          '3', '00:00:03,000 --> 00:00:04,000', 'Ba'))
        self.assertEqual(r.status_code, 200, r.text)
        sm = r.json()['summary']
        self.assertEqual((sm['mode'], sm['matched'], sm['empty_blocks']), ('index', 2, 1))
        self.assertEqual([e['id'] for e in sm['empty']], ['b'])
        self.assertEqual(self.stored()['b']['text'], '')

    def test_import_bom_crlf_and_multiline(self):
        data = '﻿1\r\n00:00:01,000 --> 00:00:02,000\r\nDòng một\r\nDòng hai\r\n\r\n2\r\n00:00:02,000 --> 00:00:03,000\r\nHai\r\n\r\n3\r\n00:00:03,000 --> 00:00:04,000\r\nBa\r\n'
        r = self.post(data.encode('utf-8'))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.stored()['a']['text'], 'Dòng một\nDòng hai')

    def test_blank_line_inside_block_is_joined_to_previous(self):
        r = self.post(srt('```srt', '1', '00:00:01,000 --> 00:00:02,000', 'Dòng một', '', 'Dòng hai', '',
                          '2', '00:00:02,000 --> 00:00:03,000', 'Hai', '',
                          '3', '00:00:03,000 --> 00:00:04,000', 'Ba', '```'))
        self.assertEqual(r.status_code, 200, r.text)
        s = self.stored()
        self.assertEqual(s['a']['text'], 'Dòng một\nDòng hai')
        self.assertEqual(s['c']['text'], 'Ba')

    def test_orphan_text_before_first_block_422(self):
        r = self.post(srt('Lời dẫn', '', '1', '00:00:01,000 --> 00:00:02,000', 'Một'))
        self.assertEqual(r.status_code, 422)
        self.assertIn('Lời dẫn', r.json()['detail'])

    def test_non_utf8_file_422_vietnamese(self):
        r = self.post('1\n00:00:01,000 --> 00:00:02,000\nXin chào\n'.encode('utf-16'))
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()['detail'], 'File phải mã hóa UTF-8.')
        r = self.post(b'\xff\xfe\x00bad\x80')
        self.assertEqual(r.json()['detail'], 'File phải mã hóa UTF-8.')

    def test_non_ascii_digit_index_422(self):
        r = self.post(srt('²', '00:00:01,000 --> 00:00:02,000', 'Một'))
        self.assertEqual(r.status_code, 422)
        self.assertIn('chữ số 0-9', r.json()['detail'])

    def test_import_skips_filtered_lyrics(self):
        r = self.post(srt('1', '00:00:01,000 --> 00:00:02,000', 'Một', '',
                          '2', '00:00:02,000 --> 00:00:03,000', 'Hai', '',
                          '3', '00:00:03,000 --> 00:00:04,000', 'Ba'))
        self.assertEqual(r.status_code, 200)
        s = self.stored()
        self.assertEqual(s['song']['text'], '')
        self.assertNotIn('status', s['song'])
        self.assertEqual(s['b']['text'], 'Hai')


if __name__ == '__main__':
    unittest.main()
