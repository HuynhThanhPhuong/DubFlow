"""Long sources must remain translatable without dropping dialogue or re-paying on resume."""
import json
import tempfile
import unittest
from pathlib import Path

from dubflow import translate_job as tj
from dubflow.manual_translation import prompt_text
from dubflow.translate_api import Reply, Usage
from tests.test_translate_job import Fake, prefs, run
from tests.test_translate_flow import Base


class ScanProvider(Fake):
    def generate(self, system, user, schema, max_output_tokens):
        body = json.loads(user)
        self.calls.append(body)
        # A decisive clue deliberately occurs only at the end of the full source.
        ancient = any('师尊' in row['zh'] for row in body.get('source_dialogue', []))
        era = 'ancient' if ancient or body['context'].get('setting', {}).get('era') == 'ancient' else 'modern'
        return Reply({'context': {'setting': {'era': era, 'note': 'full source'}},
                      'items': [{'id': row['id'], 'vi': era} for row in body['items']]}, '', False, Usage(10, 5))

    def close(self):
        pass


class LongContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)

    def test_long_source_is_scanned_completely_before_translation_with_bounded_requests(self):
        for count in (1500, 3000):
            with self.subTest(count=count):
                items = [tj.Item(f'c{i}', '这是一句需要翻译的台词', i*3, i*3+3, 'A', 'cue') for i in range(count)]
                source = [dict(id=i.id, zh=i.zh, speaker=i.speaker) for i in items]
                source[-1]['zh'] = '师尊在宗门等你'
                p = prefs(max_input_tokens=10000)
                plan = tj.plan_translation(items, 'dub', p, source_dialogue=source)
                fake = ScanProvider()
                out = run(self.folder/str(count), items, p=p, fake=fake, source_dialogue=source)
                self.assertIsNone(out.error)
                self.assertEqual(len(out.texts), count)
                self.assertEqual(set(out.texts.values()), {'ancient'})
                scans = [c for c in fake.calls if not c['items']]
                self.assertGreater(len(scans), 1)
                self.assertEqual([row for c in scans for row in c['source_dialogue']], source)
                self.assertEqual(len(fake.calls), plan.requests)
                first_translation = next(i for i, c in enumerate(fake.calls) if c['items'])
                self.assertEqual(first_translation, len(scans))
                for body in fake.calls:
                    # Independent estimate of serialized JSON plus generous system allowance.
                    self.assertLess(len(json.dumps(body, ensure_ascii=False))/1.5 + 2200, 10000)
                cached = ScanProvider()
                again = run(self.folder/str(count), items, p=p, fake=cached, source_dialogue=source)
                self.assertEqual(cached.calls, [])
                self.assertEqual(len(again.texts), count)

    def test_completed_context_can_resume_with_large_source_and_one_remaining_item(self):
        item = tj.Item('last', '你好', 0, 3, 'A', 'cue')
        source = [dict(zh='这是一句用于长视频的台词') for _ in range(1500)]
        initial = {'setting': {'era': 'ancient', 'note': 'complete'}}
        p = prefs(max_input_tokens=10000)
        plan = tj.plan_translation([item], 'dub', p, source_dialogue=source, initial_context=initial)
        self.assertEqual(plan.requests, 1)
        fake = ScanProvider()
        out = run(self.folder, [item], p=p, fake=fake, source_dialogue=source, initial_context=initial)
        self.assertIsNone(out.error)
        self.assertEqual(out.texts, {'last': 'ancient'})
        self.assertNotIn('source_dialogue', fake.calls[0])

    def test_cancelled_scan_resumes_cached_blocks_and_does_not_lock_provisional_era(self):
        items = [tj.Item(f'c{i}', '你好', i*3, i*3+3, 'A', 'cue') for i in range(1500)]
        source = [dict(id=i.id, zh=i.zh) for i in items]
        source[-1]['zh'] = '师尊'
        p = prefs(max_input_tokens=10000)
        stopped = []
        class Stop(ScanProvider):
            def generate(self, *args):
                result = super().generate(*args)
                stopped.append(True)
                return result
        first = run(self.folder, items, p=p, fake=Stop(), source_dialogue=source,
                    should_stop=lambda: bool(stopped))
        self.assertEqual(first.paused, 'cancelled')
        self.assertEqual(first.texts, {})
        fake = ScanProvider()
        second = run(self.folder, items, p=p, fake=fake, source_dialogue=source, initial_context=first.context)
        self.assertIsNone(second.error)
        self.assertEqual(set(second.texts.values()), {'ancient'})
        self.assertNotEqual(fake.calls[0].get('source_dialogue'), source[:len(source)//2])
        self.assertEqual(second.requests + first.requests,
                         tj.plan_translation(items, 'dub', p, source_dialogue=source).requests)

    def test_manual_auto_prompt_uses_plain_srt_instructions(self):
        for mode in ('vietsub', 'tm', 'dub'):
            prompt = prompt_text(mode, 17)
            self.assertNotIn('context.setting', prompt)
            self.assertIn('SRT', prompt)

    def test_failed_last_scan_does_not_cache_or_finalize_an_earlier_era(self):
        items = [tj.Item(f'c{i}', '你好', i*3, i*3+3, 'A', 'cue') for i in range(1500)]
        source = [dict(id=i.id, zh=i.zh) for i in items]
        source[-1]['zh'] = '师尊'
        p = prefs(max_input_tokens=10000)
        for data, truncated in [(None, True), ({'context': {}}, False),
                                ({'context': {'setting': {'era': 'ancient', 'note': ''}}}, True)]:
            with self.subTest(data=data, truncated=truncated), tempfile.TemporaryDirectory() as tmp:
                class BadLast(ScanProvider):
                    def generate(self, system, user, schema, max_output_tokens):
                        body = json.loads(user)
                        if not body['items'] and any(r['zh'] == '师尊' for r in body['source_dialogue']):
                            self.calls.append(body)
                            return Reply(data, '', truncated, Usage(10, 512))
                        return super().generate(system, user, schema, max_output_tokens)
                out = run(tmp, items, p=p, fake=BadLast(), source_dialogue=source)
                self.assertIsNotNone(out.error)
                self.assertEqual(out.texts, {})
                self.assertTrue(out.context.get('overview_pending'))
                resumed = ScanProvider()
                final = run(tmp, items, p=p, fake=resumed, source_dialogue=source, initial_context=out.context)
                self.assertIsNone(final.error)
                self.assertEqual(set(final.texts.values()), {'ancient'})
                self.assertEqual(resumed.calls[0]['source_dialogue'][-1]['zh'], '师尊')

    def test_scans_keep_configured_output_room_for_provider_thinking(self):
        items = [tj.Item(f'c{i}', '你好', i*3, i*3+3, 'A', 'cue') for i in range(1500)]
        source = [dict(id=i.id, zh=i.zh) for i in items]
        class Thinking(ScanProvider):
            def generate(self, system, user, schema, max_output_tokens):
                if not json.loads(user)['items'] and max_output_tokens < 2048:
                    return Reply(None, '', True, Usage(10, 0, 512))
                return super().generate(system, user, schema, max_output_tokens)
        out = run(self.folder, items, p=prefs(max_input_tokens=10000, max_output_tokens=4000),
                  fake=Thinking(), source_dialogue=source)
        self.assertIsNone(out.error)
        self.assertEqual(len(out.texts), 1500)


class LongContextAPITests(Base):
    def test_unfinished_scan_is_not_published_as_the_translation_era(self):
        self.make_job(regions=[])
        (self.folder/tj.CONTEXT_FILE).write_text(json.dumps({
            'overview_pending': True, 'setting': {'era': 'modern', 'note': 'provisional'}}), encoding='utf8')
        self.assertIsNone(self.client.get(self.base).json()['translation_context'])

    def test_default_estimate_accepts_3000_long_cues(self):
        self.configure()
        cues = [dict(id=f'c{i}', original='这是一句用于测试长视频的台词' * 6, text='',
                     start=i*8, end=i*8+8, speaker='A') for i in range(3000)]
        self.make_job(regions=[], cues=cues)
        response = self.client.get(self.base + '/translate/estimate')
        self.assertEqual(response.status_code, 200, response.text)
