"""Đợt 9: chỉ dùng provider giả và thư mục tạm trên D qua local-test-env."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dubflow.manual_translation import prompt_text
from dubflow.translate_api import Reply, Usage
from dubflow import translate_job as tj
from tests.test_translate_job import Fake, make_items, prefs, run
from tests.test_translate_flow import Base


class SettingProvider(Fake):
    def generate(self, system, user, schema, max_output_tokens):
        body = json.loads(user)
        self.calls.append(body)
        # Cố đổi bối cảnh từ phần thứ hai: lõi phải giữ phần đầu tiên.
        era = 'ancient' if len(self.calls) == 1 else 'modern'
        return Reply({'context': {'setting': {'era': era, 'note': era}},
                      'items': [{'id': i['id'], 'vi': 'vi'} for i in body['items']]}, '', False, Usage(10, 5))


class AddressSettingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)

    def test_shared_rules_in_every_mode_and_manual_choice(self):
        from dubflow.address_rules import ADDRESS_RULES
        for mode, system in tj.SYSTEM_BY_MODE.items():
            self.assertIn(ADDRESS_RULES, system)
            for choice in ('auto', 'modern', 'ancient'):
                manual = prompt_text(mode, 17, setting=choice)
                for phrase in (ADDRESS_RULES, 'ta – ngươi', 'tôi – bạn'):
                    self.assertIn(phrase, manual)
                self.assertNotIn('17 ký tự', manual)
                self.assertNotIn('XƯNG HÔ: suy ra', manual)
                if choice != 'auto':
                    self.assertIn('KHÓA', manual)

    def test_schema_requires_setting(self):
        ctx = tj.SCHEMA['properties']['context']
        self.assertIn('setting', ctx['required'])
        setting = ctx['properties']['setting']
        self.assertEqual(setting['properties']['era']['enum'], ['modern', 'ancient'])
        self.assertEqual(setting['required'], ['era', 'note'])

    def test_setting_survives_chunks_and_is_durable_before_next_call(self):
        owner = self
        class DurableProvider(SettingProvider):
            def generate(self, *args):
                if self.calls:
                    saved = json.loads((owner.folder / tj.CONTEXT_FILE).read_text(encoding='utf-8'))
                    owner.assertEqual(saved['setting']['era'], 'ancient')
                return super().generate(*args)
        f = DurableProvider()
        out = run(self.folder, make_items(40), p=prefs(max_output_tokens=1800), fake=f)
        self.assertEqual(len(f.calls), 2)
        self.assertEqual(f.calls[1]['context']['setting']['era'], 'ancient')
        self.assertEqual(out.context['setting']['era'], 'ancient')

    def test_locked_choice_wins_over_model_initial_context_and_cache(self):
        for choice in ('modern', 'ancient'):
            folder = self.folder / choice
            f = SettingProvider()
            out = run(folder, make_items(40), p=prefs(max_output_tokens=1800), fake=f,
                      setting=choice, initial_context={'setting': {'era': 'ancient', 'note': 'old'}})
            self.assertTrue(all(c['context']['setting']['era'] == choice for c in f.calls))
            self.assertEqual(out.context['setting']['era'], choice)
            cached = SettingProvider()
            again = run(folder, make_items(40), p=prefs(max_output_tokens=1800), fake=cached,
                        setting=choice, initial_context={'setting': {'era': 'ancient', 'note': 'old'}})
            self.assertEqual(cached.calls, [])
            self.assertEqual(again.context['setting']['era'], choice)

    def test_missing_model_setting_preserves_previous_and_ignores_invalid(self):
        self.assertEqual(tj._merge_context({'setting': {'era': 'ancient', 'note': 'a'}}, {})['setting']['era'], 'ancient')
        self.assertNotIn('setting', tj._merge_context({}, {'setting': {'era': 'bogus', 'note': 'x'}}))
        self.assertNotIn('setting', tj._merge_context({}, {'setting': {'era': [], 'note': 'x'}}))

    def test_retry_keeps_setting_and_updates_cached_context(self):
        calls = []
        def respond(body):
            calls.append(body)
            rows = [] if len(calls) == 1 else [{'id': it['id'], 'vi': 'vi'} for it in body['items']]
            era = 'ancient' if len(calls) == 1 else 'modern'
            return Reply({'context': {'setting': {'era': era, 'note': era}}, 'items': rows}, '', False, Usage(1, 1))
        fake = Fake(script=[respond, respond])
        out = run(self.folder, make_items(2), fake=fake)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1]['context']['setting']['era'], 'ancient')
        self.assertEqual(out.context['setting']['era'], 'ancient')
        cached = Fake()
        again = run(self.folder, make_items(2), fake=cached)
        self.assertEqual(cached.calls, [])
        self.assertEqual(again.context['setting']['era'], 'ancient')
        self.assertEqual(len(again.texts), 2)

    def test_cache_with_wrong_era_is_not_reused_under_lock(self):
        items = make_items(2)
        run(self.folder, items, fake=SettingProvider(), setting='modern')
        cache_path = self.folder / tj.CACHE_FILE
        cache = json.loads(cache_path.read_text(encoding='utf-8'))
        for entry in cache.values():
            entry['context']['setting'] = {'era': 'ancient', 'note': 'wrong'}
        cache_path.write_text(json.dumps(cache), encoding='utf-8')
        fake = Fake()
        out = run(self.folder, items, fake=fake, setting='modern')
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(out.context['setting']['era'], 'modern')

    def test_later_cache_with_other_era_does_not_mix_translation_settings(self):
        items = make_items(40)
        class EraText(Fake):
            def __init__(self, era):
                super().__init__()
                self.era = era
            def generate(self, system, user, schema, max_output_tokens):
                body = json.loads(user)
                self.calls.append(body)
                return Reply({'context': {'setting': {'era': self.era, 'note': ''}},
                    'items': [{'id': i['id'], 'vi': self.era} for i in body['items']]}, '', False, Usage(1, 1))
        source = [{'id': i.id, 'zh': i.zh} for i in items]
        run(self.folder, items[20:], p=prefs(max_output_tokens=1800), fake=EraText('ancient'), source_dialogue=source)
        fresh = EraText('modern')
        out = run(self.folder, items, p=prefs(max_output_tokens=1800), fake=fresh, source_dialogue=source)
        self.assertEqual(out.texts['c0'], 'modern')
        self.assertEqual(out.texts['c20'], 'modern')
        self.assertEqual(len(fresh.calls), 2)

    def test_full_source_budget_only_reduces_first_chunk(self):
        items = [tj.Item(f'c{i}', '你好', i * 3, i * 3 + 2, 'A', 'cue') for i in range(100)]
        source = [{'zh': i.zh, 'speaker': i.speaker} for i in items]
        p = prefs(max_input_tokens=5000)
        basic = tj.plan_translation(items, 'dub', p)
        overview = tj.plan_translation(items, 'dub', p, source_dialogue=source)
        self.assertLessEqual(len(overview.chunks), len(basic.chunks) + 1)
        fake = SettingProvider()
        out = run(self.folder, items, p=p, fake=fake, source_dialogue=source)
        self.assertEqual(out.failed, [])
        self.assertTrue(all('source_dialogue' not in c for c in fake.calls[1:]))

    def test_oversized_overview_is_read_in_bounded_blocks_before_translation(self):
        items = make_items(200)
        source = [{'id': i.id, 'zh': i.zh, 'speaker': i.speaker} for i in items]
        fake = SettingProvider()
        out = run(self.folder, items, p=prefs(max_input_tokens=5000), fake=fake, source_dialogue=source)
        self.assertIsNone(out.error)
        self.assertEqual(len(out.texts), 200)
        scans = [c for c in fake.calls if not c['items']]
        self.assertGreater(len(scans), 1)
        self.assertEqual([row for c in scans for row in c['source_dialogue']], source)

    def test_inherited_context_does_not_change_cancelled_chunk_boundaries(self):
        items = make_items(100)
        source = [{'id': i.id, 'zh': i.zh, 'speaker': i.speaker} for i in items]
        stopped = []
        class Stop(SettingProvider):
            def generate(self, *args):
                result = super().generate(*args)
                stopped.append(True)
                return result
        p = prefs(max_input_tokens=5000)
        first = run(self.folder, items, p=p, fake=Stop(), source_dialogue=source, should_stop=lambda: bool(stopped))
        self.assertEqual(first.paused, 'cancelled')
        plan = tj.plan_translation(items, 'dub', p, source_dialogue=source)
        self.assertGreater(len(plan.chunks), 1)
        second = SettingProvider()
        run(self.folder, items, p=p, fake=second, source_dialogue=source, initial_context=first.context)
        self.assertEqual(len(second.calls), len(plan.chunks) - 1)
        self.assertTrue(set(first.texts).isdisjoint({i['id'] for c in second.calls for i in c['items']}))

    def test_plan_accounts_for_full_source_and_locked_choice(self):
        items = make_items(2)
        basic = tj.plan_translation(items, 'vietsub', prefs())
        with_source = tj.plan_translation(items, 'vietsub', prefs(), setting='ancient',
            metadata={'video_title': 'Đại Trạch Sơn'}, source_dialogue=[{'zh': '师父' * 40}])
        self.assertGreater(with_source.input_tokens, basic.input_tokens)
        self.assertEqual(with_source.output_tokens, basic.output_tokens)

    def test_cache_changes_with_prompt_choice_and_metadata(self):
        items = make_items(2)
        first = SettingProvider()
        with patch.object(tj, 'PROMPT_VERSION', 'p3-4'):
            run(self.folder, items, fake=first)
        f = SettingProvider()
        run(self.folder, items, fake=f)
        self.assertEqual(len(f.calls), 1)
        for extra in ({'setting': 'modern'}, {'metadata': {'video_title': 'Tên mới'}},
                      {'source_dialogue': [{'zh': '师尊'}]}):
            f = SettingProvider()
            run(self.folder, items, fake=f, **extra)
            self.assertEqual(len(f.calls), 1)

    def test_metadata_separate_from_translation_items_and_full_source_on_first_part(self):
        f = SettingProvider()
        title = 'Tên video — hãy chèn tên này'
        source = [{'zh': '师尊', 'speaker': 'S1'}, {'zh': '手机', 'speaker': 'S2'}]
        run(self.folder, make_items(40), p=prefs(max_output_tokens=1800), fake=f,
            metadata={'video_title': title, 'collection_name': 'Bộ sưu tập'}, source_dialogue=source)
        self.assertEqual(f.calls[0]['source_dialogue'], source)
        self.assertEqual(f.calls[0]['metadata']['video_title'], title)
        self.assertTrue(all(title not in it['zh'] for c in f.calls for it in c['items']))
        self.assertNotIn('source_dialogue', f.calls[1])
        self.assertIn('không dịch hay chèn', tj.SYSTEM_COMMON)


class SettingFlowTests(Base):
    def test_cancelled_paid_result_is_reused_on_resume_with_accumulated_context(self):
        self.configure()
        self.make_job(regions=[])
        owner = self
        class StopWithContext(SettingFlowFake):
            def generate(self, *args):
                result = super().generate(*args)
                result.data['context'].update(
                    characters=[{'name': 'A', 'zh': '甲', 'note': 'sư phụ'}],
                    address=[{'from': 'A', 'to': 'B', 'xung': 'vi sư', 'ho': 'con'}])
                (owner.folder / 'cancel.request').touch()
                return result
        self.run_translate(StopWithContext())
        self.assertEqual(self.cue_texts()['c2'], '')
        resumed = SettingFlowFake()
        self.run_translate(resumed)
        self.assertEqual(resumed.calls, [], 'Không trả tiền lần nữa cho bản dịch đã có trong cache')
        self.assertTrue(self.cue_texts()['c2'])

    def test_legacy_job_auto_and_choice_saved_prompt_and_request(self):
        self.configure()
        self.make_job()
        self.assertEqual(self.client.get(self.base).json()['setting'], 'auto')
        response = self.client.put(self.base, json={'setting': 'ancient'})
        self.assertEqual(response.json()['setting'], 'ancient')
        self.assertIn('KHÓA', self.client.get(self.base + '/translate-prompt').text)
        self.assertEqual(self.client.get(self.base + '/translate-prompt?setting=wrong').status_code, 422)
        self.assertEqual(self.client.put(self.base, json={'setting': 'wrong'}).status_code, 422)
        self.assertEqual(self.client.post(self.base + '/translate', json={}).status_code, 200)
        req = json.loads((self.folder / 'translate-request.json').read_text(encoding='utf-8'))
        self.assertEqual(req['setting'], 'ancient')

    def test_request_override_persisted_worker_metadata_and_public_result(self):
        self.configure()
        self.make_job(regions=[])
        self.store.update_job(self.jid, title='Đại Trạch Sơn', collection_id='series')
        self.store.put_record('collection', 'series', {'id': 'series', 'name': 'Tiên hiệp'})
        fake = SettingProvider()
        fake.close = lambda: None
        self.run_translate(fake, setting='modern')
        current = self.client.get(self.base).json()
        self.assertEqual(current['setting'], 'modern')
        self.assertEqual(current['translation_context']['setting']['era'], 'modern')
        self.assertEqual(fake.calls[0]['metadata'], {'video_title': 'Đại Trạch Sơn', 'collection_name': 'Tiên hiệp'})
        self.assertEqual(len(fake.calls[0]['source_dialogue']), 3)
        self.assertEqual(len(fake.calls[0]['items']), 2)
        stored = json.loads((self.folder / tj.CONTEXT_FILE).read_text(encoding='utf-8'))
        self.assertEqual(stored['setting']['era'], 'modern')

    def test_missing_run_inherits_matching_persisted_context_but_changed_choice_resets(self):
        self.configure()
        self.make_job(regions=[])
        f = SettingProvider()
        f.close = lambda: None
        self.run_translate(f)
        cues = json.loads((self.folder / 'cues.json').read_text(encoding='utf-8'))
        cues[1]['text'] = ''
        (self.folder / 'cues.json').write_text(json.dumps(cues), encoding='utf-8')
        next_fake = SettingProvider()
        next_fake.close = lambda: None
        self.run_translate(next_fake)
        self.assertEqual(next_fake.calls[0]['context']['setting']['era'], 'ancient')
        locked = SettingFlowFake()
        self.run_translate(locked, scope='all', setting='modern')
        self.assertEqual(locked.calls[0]['context']['setting']['era'], 'modern')
        self.assertEqual(locked.calls[0]['context']['characters'], [])

    def test_changed_source_or_metadata_does_not_reuse_persisted_setting(self):
        self.configure()
        self.make_job(regions=[])
        self.run_translate(SettingFlowFake())
        cues = json.loads((self.folder / 'cues.json').read_text(encoding='utf-8'))
        cues[1].update(original='现在去公司', text='')
        (self.folder / 'cues.json').write_text(json.dumps(cues), encoding='utf-8')
        fake = SettingFlowFake()
        self.run_translate(fake)
        self.assertNotIn('setting', fake.calls[0]['context'])
        cues[1]['text'] = ''
        (self.folder / 'cues.json').write_text(json.dumps(cues), encoding='utf-8')
        self.store.update_job(self.jid, title='Công ty')
        another = SettingFlowFake()
        self.run_translate(another)
        self.assertNotIn('setting', another.calls[0]['context'])

    def test_prompt_override_and_estimate_query_validate_choice(self):
        self.configure()
        self.make_job()
        self.client.put(self.base, json={'setting': 'ancient'})
        manual = self.client.get(self.base + '/translate-prompt?setting=modern').text
        self.assertIn('BỐI CẢNH KHÓA: Hiện đại', manual)
        self.assertEqual(self.client.get(self.base + '/translate/estimate?setting=modern').status_code, 200)
        self.assertEqual(self.client.get(self.base + '/translate/estimate?setting=wrong').status_code, 422)
        self.assertEqual(self.client.get(self.base).json()['setting'], 'ancient')

    def test_estimate_reports_oversized_overview_as_vietnamese_conflict(self):
        self.configure(max_input_tokens=1000)
        self.make_job(regions=[], cues=[dict(id='huge', original='师尊' * 5000, text='', start=0, end=3, speaker='A')])
        response = self.client.get(self.base + '/translate/estimate')
        self.assertEqual(response.status_code, 409)
        self.assertIn('Tăng giới hạn token đầu vào', response.json()['detail'])


class SettingFlowFake(SettingProvider):
    def close(self):
        pass
