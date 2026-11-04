import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from dubflow import translate_run
from dubflow.app import create_app
from dubflow.config import Settings
from dubflow.media import atomic_json, read_json

CUES = [
    dict(id='a', start=1.0, end=3.0, original='你好', text='', speaker='s'),
    dict(id='b', start=6.0, end=8.0, original='再见', text='', speaker='s'),
    dict(id='c', start=9.0, end=11.0, original='谢谢', text='', speaker='s'),
]


def srt(*rows):
    return '\n'.join(rows).encode('utf-8')


class Base(unittest.TestCase):
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
        self.base = f"/api/jobs/{self.job['id']}"

    def upload(self, path, data):
        return self.client.post(self.base + path, files={'file': ('vi.srt', data, 'application/x-subrip')})

    def stored(self):
        return {c['id']: c for c in read_json(self.folder / 'cues.json')}


class PreviewCommitTests(Base):
    def test_preview_writes_nothing_and_labels_problems(self):
        r = self.upload('/translation-srt/preview', srt(
            '1', '00:00:01,000 --> 00:00:03,000', 'Một', '',
            '2', '00:00:01,000 --> 00:00:03,000', 'Một lần nữa', '',
            '3', '00:00:50,000 --> 00:00:51,000', 'Lạc', '',
            '4', '00:00:09,000 --> 00:00:11,000', ''))
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual((body['mode'], body['matched']), ('time', 1))
        rows = {x['block']: x for x in body['rows']}
        self.assertIn('dup_time', rows[0]['issues'])
        self.assertIn('no_match', rows[1]['issues'])
        self.assertIn('no_match', rows[2]['issues'])
        self.assertIn('empty_block', rows[3]['issues'])
        self.assertEqual([e['id'] for e in body['empty_cues']], ['b', 'c'])
        self.assertEqual(rows[0]['original'], '你好')
        self.assertEqual(self.stored()['a']['text'], '')

    def test_preview_clean_file_has_no_problems(self):
        r = self.upload('/translation-srt/preview', srt(
            '1', '00:00:01,000 --> 00:00:03,000', 'Một', '',
            '2', '00:00:06,000 --> 00:00:08,000', 'Hai', '',
            '3', '00:00:09,000 --> 00:00:11,000', 'Ba'))
        self.assertEqual(r.json()['problems'], 0)

    def test_preview_rejects_nothing_matching_and_non_srt(self):
        self.assertEqual(self.upload('/translation-srt/preview', srt('1', '00:09:00,000 --> 00:09:01,000', 'Xa')).status_code, 422)
        self.assertEqual(self.upload('/translation-srt/preview', 'không phải srt'.encode()).status_code, 422)

    def test_commit_applies_user_edited_mapping(self):
        r = self.client.post(self.base + '/translation-srt/commit', json={'assignments': {'a': ' Một ', 'c': 'Ba', 'zzz': 'x', 'b': '  '}})
        self.assertEqual(r.status_code, 200, r.text)
        s = self.stored()
        self.assertEqual((s['a']['text'], s['b']['text'], s['c']['text']), ('Một', '', 'Ba'))
        self.assertEqual([e['id'] for e in r.json()['summary']['empty']], ['b'])
        self.assertEqual(self.client.post(self.base + '/translation-srt/commit', json={'assignments': {}}).status_code, 422)


class TranslateIdsTests(Base):
    def test_ids_scope_collects_only_listed_cues_even_when_translated(self):
        cues = [dict(c) for c in CUES]
        cues[0]['text'] = 'Đã có'
        atomic_json(self.folder / 'cues.json', cues)
        items = translate_run.collect_items(self.folder, 'ids', ['a', 'c'])
        self.assertEqual([i.id for i in items], ['a', 'c'])
        self.assertEqual([i.id for i in translate_run.collect_items(self.folder, 'missing')], ['b', 'c'])

    def test_ids_scope_requires_ids(self):
        r = self.client.post(self.base + '/translate', json={'scope': 'ids'})
        self.assertIn(r.status_code, (409, 422))


class ErrorsTests(Base):
    def test_lists_failed_cues_and_import_problems_and_dismiss(self):
        atomic_json(self.folder / 'translation-failed.json', ['a', 'b'])
        r = self.upload('/translation-srt', srt('1', '00:00:09,000 --> 00:00:11,000', 'Ba', '',
                                                '2', '00:00:50,000 --> 00:00:51,000', 'Lạc'))
        self.assertEqual(r.status_code, 200, r.text)
        data = self.client.get(self.base + '/errors').json()
        keys = {i['key']: i for i in data['items']}
        self.assertEqual(data['count'], len(data['items']))
        self.assertIn('tr:a', keys)
        self.assertEqual((keys['tr:a']['step'], keys['tr:a']['cue_number']), ('Dịch', 1))
        self.assertIn('retry', keys['tr:a']['actions'])
        self.assertIn('srt-empty:a', keys)
        self.assertNotIn('srt-empty:c', keys)
        skipped = [k for k in keys if k.startswith('srt-skip:')]
        self.assertEqual(len(skipped), 1)
        self.assertIn('delete_block', keys[skipped[0]]['actions'])
        before = data['count']
        self.assertEqual(self.client.post(self.base + '/errors/dismiss', json={'key': 'tr:a'}).status_code, 200)
        after = self.client.get(self.base + '/errors').json()
        self.assertEqual(after['count'], before - 1)
        self.assertNotIn('tr:a', {i['key'] for i in after['items']})

    def test_translated_cue_drops_out_and_empty_state(self):
        atomic_json(self.folder / 'translation-failed.json', ['a'])
        cues = [dict(c) for c in CUES]
        cues[0]['text'] = 'Đã sửa tay'
        atomic_json(self.folder / 'cues.json', cues)
        data = self.client.get(self.base + '/errors').json()
        self.assertNotIn('tr:a', {i['key'] for i in data['items']})

    def test_task_error_log_step(self):
        (self.folder / 'last-error.log').write_text('Traceback…', encoding='utf-8')
        self.app.state.store.update_job(self.job['id'], status='error', stage='rendering', error='Xuất video lỗi.')
        data = self.client.get(self.base + '/errors').json()
        task = [i for i in data['items'] if i['kind'] == 'task']
        self.assertEqual((len(task), task[0]['step']), (1, 'Xuất'))


if __name__ == '__main__':
    unittest.main()
