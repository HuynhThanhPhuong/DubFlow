import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from dubflow import translate_run
from dubflow.app import create_app
from dubflow.config import Settings
from dubflow.media import atomic_json, read_json

CUES = [
    dict(id='a', start=1.0, end=3.0, original='你好吗朋友', text='Xin chào', speaker='s'),
    dict(id='b', start=3.2, end=4.0, original='KEIN', text='', speaker='s'),
    dict(id='c', start=9.0, end=11.0, original='谢谢大家', text='', speaker='s'),
]


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
        self.app.state.store.update_job(self.job['id'], duration=20.0)
        self.folder = settings.jobs_dir / self.job['id']
        self.folder.mkdir(exist_ok=True)
        atomic_json(self.folder / 'cues.json', [dict(c) for c in CUES])
        self.base = f"/api/jobs/{self.job['id']}"

    def errors(self):
        return self.client.get(self.base + '/errors').json()


class AuditErrorTests(Base):
    def test_audit_findings_become_items_flags_and_are_dismissable(self):
        data = self.errors()
        audit = [i for i in data['items'] if i['key'].startswith('audit:')]
        self.assertEqual([i['code'] for i in audit], ['NO_CJK'])
        item = audit[0]
        self.assertEqual((item['step'], item['severity'], item['cue_id']), ('Phân tích', 'error', 'b'))
        self.assertIn('jump', item['actions'])
        self.assertIn('delete_cues', item['actions'])
        self.assertEqual(item['delete_ids'], ['b'])
        self.assertEqual([f['code'] for f in data['cue_flags']['b']], ['NO_CJK'])
        self.client.post(self.base + '/errors/dismiss', json={'key': item['key']})
        data = self.errors()
        self.assertFalse([i for i in data['items'] if i['key'].startswith('audit:')])
        self.assertNotIn('b', data['cue_flags'])

    def test_delete_cues_keeps_history_and_removes(self):
        r = self.client.post(self.base + '/cues/delete', json={'cue_ids': ['b']})
        self.assertEqual(r.status_code, 200)
        self.assertEqual([c['id'] for c in read_json(self.folder / 'cues.json')], ['a', 'c'])
        files = list((self.folder / 'translation-history').glob('*.json'))
        self.assertGreaterEqual(len(files), 2)
        self.assertEqual(self.client.post(self.base + '/cues/delete', json={'cue_ids': ['zzz']}).status_code, 404)


class FailedBatchTests(Base):
    def outcome(self, **kw):
        base = dict(texts={'a': 'x'}, failed=[], error=None, paused=None, batches=[['a', 'b'], ['c']])
        base.update(kw)
        return SimpleNamespace(**base)

    def test_reasons(self):
        recs = translate_run.failed_batches(self.outcome(failed=['b']))
        self.assertEqual([(r['batch'], r['batches'], r['cue_ids'], r['reason']) for r in recs],
                         [(1, 2, ['b'], 'kết quả hỏng'), (2, 2, ['c'], 'kết quả hỏng')])
        recs = translate_run.failed_batches(self.outcome(texts={'a': 'x', 'b': 'y'}, error='Gemini lỗi 503. Đã thử 4 lần'))
        self.assertEqual([(r['batch'], r['reason']) for r in recs], [(2, '503 quá tải')])
        self.assertEqual(translate_run.failed_batches(self.outcome(paused='quota'))[0]['reason'], 'hết hạn mức')
        self.assertEqual(translate_run.failed_batches(self.outcome(paused='cancelled'))[0]['reason'], 'bị dừng')

    def test_record_and_show_in_errors_then_hide_when_translated(self):
        translate_run.record_failed_batches(self.folder, [SimpleNamespace(id=i) for i in 'abc'],
                                            self.outcome(texts={'a': 'x'}, error='503 quá tải'))
        items = [i for i in self.errors()['items'] if i['key'].startswith('trb:')]
        self.assertEqual(len(items), 2)
        self.assertIn('Lô 1/2', items[0]['message'])
        self.assertIn('503 quá tải', items[0]['message'])
        self.assertEqual((items[0]['cue_ids'], items[1]['cue_ids']), (['b'], ['c']))
        self.assertIn('retry_batch', items[0]['actions'])
        atomic_json(self.folder / 'cues.json', [dict(c, text='ok') for c in CUES])
        self.assertFalse([i for i in self.errors()['items'] if i['key'].startswith('trb:')])
