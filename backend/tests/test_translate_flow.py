import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from dubflow import pipeline as p
from dubflow.app import create_app
from dubflow.config import Settings
from dubflow.translate_api import ProviderError, QuotaExhausted, Reply, Usage
from dubflow.worker import run_task

KEY = 'AIza-SECRET-KEY-123456'
LONG = '这是一句很长的中文台词用来测试分块' * 2


class Fake:
    name = 'gemini'
    model = 'gemini-x'

    def __init__(self, omit=(), fail_on_call=None, error=None):
        self.sent, self.closed, self.omit, self.fail_on_call, self.error = [], False, set(omit), fail_on_call, error

    def generate(self, system, user, schema, max_output_tokens):
        if self.error is not None and (self.fail_on_call is None or len(self.sent) + 1 == self.fail_on_call):
            self.sent.append([])
            raise self.error
        items = json.loads(user)['items']
        self.sent.append([i['id'] for i in items])
        rows = [{'id': i['id'], 'vi': 'VI ' + i['zh'][:6]} for i in items if i['id'] not in self.omit]
        return Reply({'context': {}, 'items': rows}, '', False, Usage(10, 5))

    def close(self):
        self.closed = True


class Base(unittest.TestCase):
    cues = None

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cfg = Settings(root=self.root, data_dir=self.root / 'data', system_voices=self.root / 'voices')
        self.app = create_app(self.cfg, start_worker=False)
        self.client = TestClient(self.app)
        self.store = self.app.state.store

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def configure(self, **extra):
        values = dict(gemini_api_key=KEY, gemini_model='gemini-x')
        values.update(extra)
        self.assertEqual(self.client.put('/api/settings', json=values).status_code, 200)

    def make_job(self, mode='vietsub', cues=None, regions=None):
        job = self.store.create_job(dict(title='t', mode=mode, status='awaiting_review', duration=100, width=1280, height=720))
        self.folder = self.cfg.jobs_dir / job['id']
        self.folder.mkdir()
        self.base = '/api/jobs/' + job['id']
        self.jid = job['id']
        cues = cues if cues is not None else [
            dict(id='c1', start=0, end=2, speaker='A', original='你好', text='Đã có sẵn'),
            dict(id='c2', start=2, end=4, speaker='A', original='谢谢你', text=''),
            dict(id='c3', start=4, end=6, speaker='B', original='再见', text=''),
        ]
        regions = regions if regions is not None else [
            dict(id='r1', kind='transient', enabled=True, text='第一天', translation='', x=0, y=0, width=10, height=10, start=0, end=3),
            dict(id='r2', kind='static', enabled=True, text='LOGO', translation='', x=0, y=0, width=10, height=10, start=0, end=100),
        ]
        p.write(self.folder / 'cues.json', cues)
        p.write(self.folder / 'regions.json', regions)
        return job

    def run_translate(self, fake, **body):
        with patch('dubflow.translate_run.make_provider', return_value=fake):
            r = self.client.post(self.base + '/translate', json=body)
            self.assertEqual(r.status_code, 200, r.text)
            run_task(self.store.claim_next(), self.cfg, self.store)
        return self.store.get_job(self.jid)

    def cue_texts(self):
        return {c['id']: c['text'] for c in p.read(self.folder / 'cues.json')}


class SettingsTests(Base):
    def test_settings_redacts_all_provider_keys(self):
        keys = {'gemini': 'g-key-111', 'openai': 'o-key-222', 'anthropic': 'a-key-333'}
        r = self.client.put('/api/settings', json={f'{k}_api_key': v for k, v in keys.items()})
        self.assertEqual(r.status_code, 200)
        for text in (r.text, self.client.get('/api/settings').text):
            for v in keys.values():
                self.assertNotIn(v, text)
        got = self.client.get('/api/settings').json()
        for k in keys:
            self.assertTrue(got[f'has_{k}_key'])
            self.assertEqual(got[f'{k}_api_key'], '')

    def test_settings_empty_key_keeps_old(self):
        self.client.put('/api/settings', json={'openai_api_key': 'o-key-222'})
        self.client.put('/api/settings', json={'openai_api_key': '', 'openai_model': 'gpt-x'})
        got = self.client.get('/api/settings').json()
        self.assertTrue(got['has_openai_key'])
        self.assertEqual(got['openai_model'], 'gpt-x')

    def test_settings_clear_key(self):
        self.client.put('/api/settings', json={'anthropic_api_key': 'a-key-333', 'gemini_api_key': 'g-key-111'})
        self.client.put('/api/settings', json={'clear_anthropic_key': True})
        got = self.client.get('/api/settings').json()
        self.assertFalse(got['has_anthropic_key'])
        self.assertTrue(got['has_gemini_key'])

    def test_legacy_ollama_record_loads(self):
        self.store.put_record('settings', 'main', dict(output_dir=str(self.root / 'out'), translation_mode='ollama',
                              translation_model='qwen', translation_api_key='legacy-secret', auto_translate=True,
                              translation_num_ctx=4096, translation_api_url='', translation_api_model=''))
        r = self.client.get('/api/settings')
        self.assertEqual(r.status_code, 200)
        got = r.json()
        for old in ('translation_mode', 'translation_model', 'auto_translate', 'translation_api_key'):
            self.assertNotIn(old, got)
        self.assertFalse(got['has_gemini_key'])
        self.assertNotIn('legacy-secret', r.text)
        self.assertFalse(self.client.get('/api/health').json()['capabilities']['automatic_translation'])

    def test_models_endpoint_needs_key(self):
        with patch('dubflow.studio.make_provider') as make:
            r = self.client.get('/api/settings/models', params={'provider': 'gemini'})
        self.assertEqual(r.status_code, 409)
        make.assert_not_called()

    def test_models_endpoint_uses_provider(self):
        self.configure()
        with patch('dubflow.studio.make_provider') as make:
            make.return_value.__enter__.return_value.list_models.return_value = ['m1', 'm2']
            r = self.client.get('/api/settings/models', params={'provider': 'gemini'})
        self.assertEqual(r.json(), {'models': ['m1', 'm2']})
        self.assertEqual(make.call_args.args[:2], ('gemini', KEY))
        with patch('dubflow.studio.make_provider') as make:
            make.return_value.__enter__.return_value.list_models.side_effect = ProviderError(f'Lỗi {KEY}')
            r = self.client.get('/api/settings/models', params={'provider': 'gemini'})
        self.assertEqual(r.status_code, 502)
        self.assertNotIn(KEY, r.text)

    def test_ready_flips_capability(self):
        self.client.put('/api/settings', json={'gemini_api_key': KEY})
        self.assertFalse(self.client.get('/api/health').json()['capabilities']['automatic_translation'])
        self.client.put('/api/settings', json={'gemini_model': 'gemini-x'})
        self.assertTrue(self.client.get('/api/health').json()['capabilities']['automatic_translation'])


class EstimateTests(Base):
    def test_estimate_free_tier(self):
        self.configure()
        self.make_job()
        r = self.client.get(self.base + '/translate/estimate', params={'scope': 'missing'})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertIsNone(body['cost_usd'])
        self.assertIsNone(body['cap_usd'])
        self.assertFalse(body['over_cap'])
        self.assertEqual((body['cue_count'], body['tier'], body['requests']), (3, 'free', 1))
        self.assertEqual(self.client.get(self.base + '/translate/estimate', params={'scope': 'all'}).json()['cue_count'], 4)

    def test_estimate_paid_over_cap(self):
        self.configure(translation_tier='paid', price_in_per_mtok=1000, price_out_per_mtok=1000, cost_cap_usd=.0001)
        self.make_job()
        body = self.client.get(self.base + '/translate/estimate').json()
        self.assertGreater(body['cost_usd'], .0001)
        self.assertEqual(body['cap_usd'], .0001)
        self.assertTrue(body['over_cap'])

    def test_estimate_409_when_unconfigured_or_nothing_to_do(self):
        self.make_job()
        self.assertEqual(self.client.get(self.base + '/translate/estimate').status_code, 409)
        self.configure()
        self.make_job(cues=[dict(id='c1', start=0, end=2, speaker='A', original='你好', text='Có')], regions=[])
        self.assertEqual(self.client.get(self.base + '/translate/estimate').status_code, 409)


class RunTests(Base):
    def test_translate_missing_keeps_user_edits(self):
        self.configure()
        self.make_job()
        fake = Fake()
        job = self.run_translate(fake)
        self.assertEqual(sorted(i for ids in fake.sent for i in ids), ['c2', 'c3', 'region:r1'])
        texts = self.cue_texts()
        self.assertEqual(texts['c1'], 'Đã có sẵn')
        self.assertTrue(texts['c2'].startswith('VI '))
        cues = {c['id']: c for c in p.read(self.folder / 'cues.json')}
        self.assertEqual(cues['c2']['status'], 'needs_review')
        self.assertIn('translation_dependency', cues['c2'])
        self.assertNotIn('translation_dependency', cues['c1'])
        regions = {r['id']: r for r in p.read(self.folder / 'regions.json')}
        self.assertTrue(regions['r1']['translation'].startswith('VI '))
        self.assertEqual(regions['r2']['translation'], '')
        self.assertEqual(job['status'], 'awaiting_review')
        self.assertTrue(fake.closed)
        usage = self.client.get(self.base).json()['translation_usage']
        self.assertEqual((usage['requests'], usage['provider'], usage['model'], usage['mode']), (1, 'gemini', 'gemini-x', 'vietsub'))
        self.assertIsNone(usage['cost_usd'])

    def test_translate_all_resends_everything(self):
        self.configure()
        self.make_job()
        fake = Fake()
        self.run_translate(fake, scope='all')
        self.assertEqual(sorted(i for ids in fake.sent for i in ids), ['c1', 'c2', 'c3', 'region:r1'])
        self.assertTrue(self.cue_texts()['c1'].startswith('VI '))
        self.run_translate(Fake(), scope='all')
        self.assertEqual(self.client.get(self.base).json()['translation_usage']['requests'], 1)  # second run served from cache

    def test_noise_region_not_sent_cjk_region_sent(self):
        self.configure()
        regions = [dict(id=i, kind='transient', enabled=True, text=t, translation='', x=0, y=0, width=10, height=10, start=0, end=3)
                   for i, t in (('n1', '50'), ('n2', 'V'), ('k1', '小心'))]
        self.make_job(regions=regions)
        fake = Fake()
        self.run_translate(fake)
        sent = sorted(i for ids in fake.sent for i in ids)
        self.assertIn('region:k1', sent)
        self.assertNotIn('region:n1', sent)
        self.assertNotIn('region:n2', sent)

    def test_zero_request_run_keeps_usage_file(self):
        self.configure()
        self.make_job()
        self.run_translate(Fake())
        before = (self.folder / 'translation-usage.json').read_text(encoding='utf-8')
        self.make_job(mode='dub')  # new job; reuse folder state below instead
        self.folder = self.cfg.jobs_dir / self.jid
        (self.folder / 'translation-usage.json').write_text(before, encoding='utf-8')
        self.run_translate(Fake(error=ProviderError('hỏng')), scope='all')
        self.assertEqual((self.folder / 'translation-usage.json').read_text(encoding='utf-8'), before)

    def test_no_key_never_calls_api(self):
        self.make_job()
        with patch('dubflow.translate_run.make_provider') as make:
            r = self.client.post(self.base + '/translate')
        self.assertEqual(r.status_code, 409)
        make.assert_not_called()

    def test_quota_pause_sets_warning_and_resume_sends_rest(self):
        self.configure(max_output_tokens=256)
        cues = [dict(id=f'c{i}', start=i * 3, end=i * 3 + 2, speaker='A', original=LONG, text='') for i in range(6)]
        self.make_job(cues=cues, regions=[])
        fake = Fake(error=QuotaExhausted('x'), fail_on_call=2)
        job = self.run_translate(fake)
        self.assertEqual(job['status'], 'awaiting_review')
        done = [i for i, t in self.cue_texts().items() if t]
        self.assertTrue(0 < len(done) < 6, done)
        self.assertIn(f'Tạm dừng – hết hạn mức ngày của Gemini. Đã dịch {len(done)}/6 câu; bấm "Dịch tiếp" khi hạn mức được làm mới.', job['warnings'])
        again = Fake()
        self.run_translate(again)
        self.assertEqual(sorted(i for ids in again.sent for i in ids), sorted(set(self.cue_texts()) - set(done)))
        self.assertTrue(all(self.cue_texts().values()))
        self.assertEqual(self.client.get(self.base).json()['translation_usage']['requests'], 1 + len(again.sent))

    def test_cost_cap_pause_warning_and_override(self):
        self.configure(translation_tier='paid', price_in_per_mtok=1000, price_out_per_mtok=1000, cost_cap_usd=.0001)
        self.make_job()
        fake = Fake()
        job = self.run_translate(fake)
        self.assertEqual(fake.sent, [])
        self.assertIn('Tạm dừng – sắp vượt mức trần chi phí 0.0001 USD cho video này. Bấm "Dịch tiếp, cho phép vượt trần" nếu muốn chạy tiếp.', job['warnings'])
        fake = Fake()
        self.run_translate(fake, allow_over_cap=True)
        self.assertEqual(len(fake.sent), 1)
        self.assertGreater(self.client.get(self.base).json()['translation_usage']['cost_usd'], 0)

    def test_provider_error_does_not_fail_job_and_hides_key(self):
        self.configure()
        self.make_job()
        fake = Fake(error=ProviderError('Key Gemini không hợp lệ hoặc không có quyền dùng model gemini-x.'))
        job = self.run_translate(fake)
        self.assertEqual(job['status'], 'awaiting_review')
        self.assertIsNone(job['error'])
        self.assertTrue(any('Key Gemini không hợp lệ' in w for w in job['warnings']))
        self.assertTrue(fake.closed)
        blobs = [json.dumps(job), json.dumps(self.store.events(self.jid)), json.dumps(self.client.get(self.base).json())]
        blobs += [f.read_bytes().decode('utf-8', 'ignore') for f in self.folder.rglob('*') if f.is_file()]
        blobs += [f.read_bytes().decode('utf-8', 'ignore') for f in (self.cfg.data_dir).glob('*.json') if f.is_file()]
        self.assertFalse([b for b in blobs if KEY in b])

    def test_unexpected_error_leaves_job_not_running_and_closes_provider(self):
        self.configure()
        self.make_job()
        fake = Fake(error=RuntimeError('boom'))
        job = self.run_translate(fake)
        self.assertEqual(job['status'], 'failed')
        self.assertTrue(fake.closed)

    def test_failed_ids_flagged(self):
        self.configure()
        self.make_job()
        self.run_translate(Fake(omit={'c3'}))
        flags = self.client.get(self.base + '/quality').json()['flags']
        failed = [f for f in flags if f['code'] == 'TRANSLATE_FAILED']
        self.assertEqual([f['cue_ids'] for f in failed], [['c3']])
        self.assertEqual(failed[0]['message'], 'Chưa dịch được câu này; hãy dịch tay hoặc bấm Dịch tiếp.')
        self.assertEqual(self.cue_texts()['c3'], '')
        self.run_translate(Fake())
        flags = self.client.get(self.base + '/quality').json()['flags']
        self.assertFalse([f for f in flags if f['code'] == 'TRANSLATE_FAILED'])

    def test_vietsub_read_too_fast_flag(self):
        self.configure()
        long_text = 'x' * 25
        cues = [dict(id='c1', start=0, end=1, speaker='A', original='你好', text=long_text)]
        self.make_job(mode='vietsub', cues=cues, regions=[])
        codes = [f['code'] for f in self.client.get(self.base + '/quality').json()['flags']]
        self.assertIn('READ_TOO_FAST', codes)
        self.client.put('/api/settings', json={'vietsub_cps': 30})
        codes = [f['code'] for f in self.client.get(self.base + '/quality').json()['flags']]
        self.assertNotIn('READ_TOO_FAST', codes)
        self.make_job(mode='dub', cues=cues, regions=[])
        self.client.put('/api/settings', json={'vietsub_cps': 8})
        codes = [f['code'] for f in self.client.get(self.base + '/quality').json()['flags']]
        self.assertNotIn('READ_TOO_FAST', codes)

    def test_provider_error_midrun_keeps_paid_chunks(self):
        self.configure(max_output_tokens=256)
        cues = [dict(id=f'c{i}', start=i * 3, end=i * 3 + 2, speaker='A', original=LONG, text='') for i in range(6)]
        self.make_job(cues=cues, regions=[])
        fake = Fake(error=ProviderError('Key Gemini không hợp lệ hoặc không có quyền dùng model gemini-x.'), fail_on_call=2)
        job = self.run_translate(fake)
        done = [i for i, t in self.cue_texts().items() if t]
        self.assertTrue(0 < len(done) < 6, done)
        self.assertEqual(job['status'], 'awaiting_review')
        self.assertTrue(any('Key Gemini không hợp lệ' in w for w in job['warnings']))
        self.assertEqual(self.client.get(self.base).json()['translation_usage']['requests'], 1)
        self.assertNotIn(KEY, json.dumps(job))

    def test_second_translate_while_queued_is_409_and_keeps_request(self):
        self.configure()
        self.make_job()
        self.assertEqual(self.client.post(self.base + '/translate', json={'scope': 'all'}).status_code, 200)
        r = self.client.post(self.base + '/translate', json={'scope': 'missing'})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(p.read(self.folder / 'translate-request.json')['scope'], 'all')

    def test_refused_dispatch_keeps_request_file(self):
        self.configure()
        self.make_job()
        self.assertEqual(self.client.post(self.base + '/translate', json={'scope': 'missing', 'allow_over_cap': True}).status_code, 200)
        before = (self.folder / 'translate-request.json').read_bytes()
        # bypass the status/active-task pre-checks to hit the store's own refusal
        self.store.update_job(self.jid, status='awaiting_review')
        r = self.client.post(self.base + '/translate', json={'scope': 'all'})
        self.assertEqual(r.status_code, 409)
        self.assertEqual((self.folder / 'translate-request.json').read_bytes(), before)

    def test_refused_dispatch_during_render_keeps_request_file(self):
        self.configure()
        self.make_job()
        (self.folder / 'translate-request.json').write_text('{"scope": "missing"}', encoding='utf-8')
        self.store.enqueue(self.jid, 'render')
        self.store.update_job(self.jid, status='awaiting_review')
        r = self.client.post(self.base + '/translate', json={'scope': 'all'})
        self.assertEqual(r.status_code, 409)
        self.assertEqual((self.folder / 'translate-request.json').read_text(encoding='utf-8'), '{"scope": "missing"}')

    def test_legacy_key_purged_on_first_load(self):
        self.store.put_record('settings', 'main', dict(output_dir=str(self.root / 'out'), translation_api_key='legacy-secret', translation_mode='api'))
        self.client.get('/api/settings')
        self.assertNotIn('legacy-secret', json.dumps(self.store.get_record('settings', 'main')))

    def test_prepare_never_calls_api(self):
        with tempfile.TemporaryDirectory(dir=p.ROOT) as d:
            directory = Path(d)
            p.write(directory / 'job.json', dict(source_path='source.mp4', mode='vietsub'))
            p.write(directory / 'regions.json', [])
            p.write(directory / 'ocr-complete.json', {})
            stages = []

            def stage(name, directory, settings, payload, **kwargs):
                stages.append(name)
                if name == 'transcribe':
                    p.write(directory / 'source-asr-cues.json', [dict(id='1', start=0, end=1, speaker='s', original='原文', text='')])
                else:
                    p.write(directory / 'subtrack.json', dict(version=1, segments=[]))
            boom = MagicMock(side_effect=AssertionError('API must not be called'))
            with patch('dubflow.translate_run.make_provider', boom), patch('dubflow.studio.make_provider', boom), \
                    patch.object(p, 'probe', return_value=dict(duration=3, width=320, height=240)), \
                    patch.object(p, 'engine', side_effect=stage), patch.object(p, 'audio_rms', return_value=([0.0] * 150, .02)):
                with self.assertRaisesRegex(p.NeedsReview, 'tiếng Việt'):
                    p.prepare(directory, SimpleNamespace(), lambda *a: None)
            boom.assert_not_called()
            self.assertNotIn('translate', stages)


if __name__ == '__main__':
    unittest.main()
