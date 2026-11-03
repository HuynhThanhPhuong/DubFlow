import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from dubflow.translate_api import QuotaExhausted, RateLimited, Reply, ServerBusy, Usage
from dubflow.translate_job import Cancelled, Item, RateLimiter, plan_translation, run_translation

KEY = 'SECRET-key-999'


def prefs(**kw):
    d = dict(tier='free', rate_rpm=10, rate_rpd=100, price_in_per_mtok=1.0, price_out_per_mtok=2.0,
             cost_cap_usd=1.0, vietsub_cps=15, max_output_tokens=60000, max_input_tokens=200000)
    d.update(kw)
    return SimpleNamespace(**d)


def make_items(n, step=3.2, dur=3.0, gaps=None):
    out, t = [], 0.0
    for i in range(n):
        t += (gaps or {}).get(i, step - dur)
        out.append(Item(f'c{i}', '你好，这是第%d句话。' % i, t, t + dur, 'A' if i % 2 else 'B', 'cue'))
        t += dur
    return out


class Fake:
    name = 'gemini'

    def __init__(self, model='m1', script=None, usage=None):
        self.model, self.calls, self.script = model, [], list(script or [])
        self.usage = usage or Usage(100, 50)

    def generate(self, system, user, schema, max_output_tokens):
        body = json.loads(user)
        self.calls.append(body)
        if self.script:
            step = self.script.pop(0)
            if isinstance(step, Exception):
                raise step
            if callable(step):
                return step(body)
        rows = [{'id': i['id'], 'vi': 'vi ' + i['id']} for i in body['items']]
        ctx = {'characters': [{'name': 'N%d' % len(self.calls), 'zh': '名', 'note': ''}]}
        return Reply({'context': ctx, 'items': rows}, '', False, self.usage)


def reply(rows, truncated=False, ctx=None):
    return lambda body: Reply({'context': ctx or {}, 'items': rows}, '', truncated, Usage(10, 5))


def run(d, items, p=None, fake=None, mode='dub', **kw):
    kw.setdefault('limiter', None)
    return run_translation(Path(d), items, mode, p or prefs(), fake or Fake(), **kw)


class TranslateJobTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_short_video_is_one_request(self):
        items = make_items(150, step=3.2)
        self.assertEqual(plan_translation(items, 'dub', prefs()).requests, 1)
        f = Fake()
        out = run(self.d, items, fake=f)
        self.assertEqual(len(f.calls), 1)
        self.assertEqual(len(out.texts), 150)
        self.assertEqual(out.failed, [])

    def test_long_video_splits_at_largest_gap(self):
        items = make_items(40, gaps={21: 5.0})
        p = prefs(max_output_tokens=1800)
        plan = plan_translation(items, 'dub', p)
        self.assertEqual(len(plan.chunks), 2)
        self.assertEqual(plan.chunks[1][0].id, 'c21')
        again = plan_translation(items, 'dub', p)
        self.assertEqual([[i.id for i in c] for c in plan.chunks], [[i.id for i in c] for c in again.chunks])

    def test_context_carried_to_next_chunk(self):
        f = Fake()
        run(self.d, make_items(40), p=prefs(max_output_tokens=1800), fake=f)
        self.assertEqual(len(f.calls), 2)
        self.assertEqual(f.calls[0]['context']['characters'], [])
        self.assertEqual(f.calls[1]['context']['characters'][0]['name'], 'N1')

    def test_missing_and_empty_ids_retried_once_in_one_request(self):
        items = make_items(10)
        rows = [{'id': i.id, 'vi': 'x'} for i in items[:6]] + [{'id': 'c6', 'vi': '  '}]
        f = Fake(script=[reply(rows), reply([{'id': 'c6', 'vi': 'y'}])])
        out = run(self.d, items, fake=f)
        self.assertEqual([i['id'] for i in f.calls[1]['items']], ['c6', 'c7', 'c8', 'c9'])
        self.assertEqual(out.requests, 2)
        self.assertEqual(out.failed, ['c7', 'c8', 'c9'])
        self.assertEqual(out.texts['c6'], 'y')

    def test_retry_still_failing_goes_to_failed(self):
        items = make_items(6)
        f = Fake(script=[reply([{'id': 'c0', 'vi': 'a'}, {'id': 'zzz', 'vi': 'b'}, {'id': 'c1', 'vi': 'c'},
                                {'id': 'c1', 'vi': 'd'}]), reply([])])
        out = run(self.d, items, fake=f)
        self.assertEqual(out.requests, 2)
        self.assertEqual(out.failed, ['c1', 'c2', 'c3', 'c4', 'c5'])
        self.assertEqual(out.texts, {'c0': 'a'})

    def test_truncated_reply_retries_missing_and_last_item(self):
        items = make_items(5)
        f = Fake(script=[reply([{'id': 'c0', 'vi': 'a'}, {'id': 'c1', 'vi': 'b'}, {'id': 'c2', 'vi': 'Anh đang nó'}],
                               truncated=True)])
        out = run(self.d, items, fake=f)
        self.assertEqual([i['id'] for i in f.calls[1]['items']], ['c2', 'c3', 'c4'])
        self.assertEqual(len(out.texts), 5)
        self.assertEqual(out.texts['c2'], 'vi c2')
        cache = json.loads((self.d / 'translation-cache-v2.json').read_text(encoding='utf-8'))
        self.assertNotIn('Anh đang nó', json.dumps(cache, ensure_ascii=False))

    def test_split_never_raises_with_huge_items(self):
        p = prefs(max_output_tokens=1000)
        huge = Item('h', '长' * 400, 0, 5, 'A', 'cue')
        normal = make_items(30, step=3.2)
        mixed = normal[:15] + [huge] + normal[15:]
        chunks = plan_translation(mixed, 'dub', p).chunks
        self.assertEqual([i.id for c in chunks for i in c], [i.id for i in mixed])
        self.assertIn(['h'], [[i.id for i in c] for c in chunks])
        every = [Item('h%d' % i, '长' * 400, i * 6, i * 6 + 5, 'A', 'cue') for i in range(5)]
        self.assertEqual([len(c) for c in plan_translation(every, 'dub', p).chunks], [1] * 5)
        self.assertEqual(len(plan_translation(every[:1], 'dub', p).chunks), 1)
        self.assertEqual([len(c) for c in plan_translation(every[:2], 'dub', p).chunks], [1, 1])
        out = run(self.d, mixed, p=p, fake=Fake())
        self.assertEqual(len(out.texts), len(mixed))

    def test_non_string_ids_are_ignored(self):
        items = make_items(3)
        rows = [{'id': ['c0'], 'vi': 'x'}, {'id': {'a': 1}, 'vi': 'y'}, {'id': 'c0', 'vi': 'a'},
                {'id': 'c1', 'vi': 'b'}, {'id': 'c2', 'vi': 'c'}]
        out = run(self.d, items, fake=Fake(script=[reply(rows)]), )
        self.assertEqual(out.texts, {'c0': 'a', 'c1': 'b', 'c2': 'c'})
        out2 = run(self.d, make_items(3), fake=Fake(script=[reply(rows)]), terminology='x')
        self.assertEqual(out2.failed, [])

    def test_unknown_mode_raises_vietnamese_error(self):
        with self.assertRaises(ValueError):
            plan_translation(make_items(2), 'xyz', prefs())
        with self.assertRaises(ValueError):
            run(self.d, make_items(2), mode='xyz')

    def test_cache_hit_makes_no_request(self):
        items = make_items(8)
        run(self.d, items, fake=Fake())
        f = Fake()
        out = run(self.d, items, fake=f)
        self.assertEqual(f.calls, [])
        self.assertEqual(len(out.texts), 8)
        self.assertEqual(out.requests, 0)

    def test_cache_key_changes_with_mode_model_terminology(self):
        items = make_items(4)
        run(self.d, items, fake=Fake())
        for kw, fk in ((dict(mode='tm'), {}), (dict(), dict(model='m2')), (dict(terminology='A=B'), {})):
            f = Fake(**fk)
            run(self.d, items, fake=f, **kw)
            self.assertEqual(len(f.calls), 1, (kw, fk))

    def test_quota_exhausted_mid_run_keeps_done_chunks(self):
        items = make_items(40)
        p = prefs(max_output_tokens=1800)
        f = Fake(script=[None, QuotaExhausted('het')])
        out = run(self.d, items, p=p, fake=f)
        self.assertEqual(out.paused, 'quota')
        self.assertTrue(0 < len(out.texts) < 40)
        cache = json.loads((self.d / 'translation-cache-v2.json').read_text(encoding='utf-8'))
        self.assertEqual(len(cache), 1)
        f2 = Fake()
        out2 = run(self.d, items, p=p, fake=f2)
        self.assertEqual(len(f2.calls), 1)
        self.assertIsNone(out2.paused)
        self.assertEqual(len(out2.texts), 40)

    def test_rate_limited_waits_retry_after(self):
        waits = []
        f = Fake(script=[RateLimited('429', 37)])
        out = run(self.d, make_items(3), fake=f, sleep=waits.append)
        self.assertEqual(sum(waits), 37)
        self.assertTrue(all(w <= 1 for w in waits))
        self.assertEqual(len(out.texts), 3)

    def test_rate_limited_backoff_and_give_up(self):
        waits = []
        f = Fake(script=[RateLimited('429')] * 4)
        out = run(self.d, make_items(3), fake=f, sleep=waits.append)
        self.assertEqual(out.error, '429')
        self.assertEqual(out.texts, {})
        self.assertEqual(sum(waits), 100)

    def test_server_busy_503_is_retried_and_reported(self):
        waits, events = [], []
        f = Fake(script=[ServerBusy('Gemini đang quá tải hoặc tạm lỗi (HTTP 503).', 503)] * 2)
        out = run(self.d, make_items(3), fake=f, sleep=waits.append, on_event=lambda m, d: events.append((m, d)))
        self.assertEqual(len(out.texts), 3)
        self.assertIsNone(out.error)
        self.assertEqual(sum(waits), 5 + 15)
        retries = [m for m, _ in events if 'lỗi 503' in m]
        self.assertEqual(len(retries), 2)
        self.assertIn('thử lại lần 2/4 sau 5 giây', retries[0])
        self.assertIn('thử lại lần 3/4 sau 15 giây', retries[1])
        self.assertTrue(all(d['note'] for _, d in events))

    def test_server_busy_gives_up_with_clear_message(self):
        waits = []
        f = Fake(script=[ServerBusy('Gemini đang quá tải hoặc tạm lỗi (HTTP 503).', 503)] * 5)
        out = run(self.d, make_items(3), fake=f, sleep=waits.append)
        self.assertEqual(out.texts, {})
        self.assertEqual(len(f.calls), 4)
        self.assertIn('HTTP 503', out.error)
        self.assertIn('Đã thử 4 lần', out.error)
        self.assertEqual(sum(waits), 5 + 15 + 30)

    def test_server_busy_wait_is_cancellable(self):
        f = Fake(script=[ServerBusy('503', 503)] * 5)
        out = run(self.d, make_items(3), fake=f, sleep=lambda s: None, should_stop=lambda: len(f.calls) >= 1)
        self.assertEqual(out.paused, 'cancelled')

    def test_events_report_each_batch_with_detail(self):
        events = []
        items = [Item(f'c{i}', '这是一句很长的中文台词用来测试分块' * 2, i * 3, i * 3 + 2, 'A', 'cue') for i in range(6)]
        out = run(self.d, items, p=prefs(max_output_tokens=256), on_event=lambda m, d: events.append((m, d)))
        self.assertEqual(len(out.texts), 6)
        batches = events[0][1]['batches']
        self.assertGreater(batches, 1)
        waiting = [(m, d) for m, d in events if 'chờ trả lời' in m]
        self.assertEqual([d['batch'] for _, d in waiting], list(range(1, batches + 1)))
        self.assertTrue(waiting[0][0].startswith(f'Lô 1/{batches} ('))
        self.assertEqual(waiting[0][1]['total'], 6)
        self.assertEqual(events[-1][1]['done'], 6)

    def test_failing_event_callback_never_breaks_translation(self):
        def boom(m, d):
            raise RuntimeError('ui')
        out = run(self.d, make_items(3), on_event=boom)
        self.assertEqual(len(out.texts), 3)

    def test_cost_cap_pauses_before_exceeding(self):
        p = prefs(tier='paid', cost_cap_usd=0.0001)
        f = Fake()
        out = run(self.d, make_items(5), p=p, fake=f)
        self.assertEqual(out.paused, 'cost_cap')
        self.assertEqual(f.calls, [])

    def test_allow_over_cap_continues(self):
        p = prefs(tier='paid', cost_cap_usd=0.0001, price_in_per_mtok=1.0, price_out_per_mtok=2.0)
        out = run(self.d, make_items(5), p=p, allow_over_cap=True, fake=Fake(usage=Usage(1000, 500)))
        self.assertIsNone(out.paused)
        self.assertAlmostEqual(out.cost_usd, 1000 * 1 / 1e6 + 500 * 2 / 1e6)

    def test_free_tier_has_no_cost(self):
        out = run(self.d, make_items(3), p=prefs(cost_cap_usd=0.0))
        self.assertIsNone(out.cost_usd)
        self.assertIsNone(out.paused)

    def test_cancel_stops_after_first_chunk(self):
        f = Fake()
        out = run(self.d, make_items(40), p=prefs(max_output_tokens=1800), fake=f, should_stop=lambda: len(f.calls) >= 1)
        self.assertEqual(len(f.calls), 1)
        self.assertEqual(out.requests, 1)
        self.assertEqual(out.paused, 'cancelled')
        self.assertTrue(0 < len(out.texts) < 40)

    def test_cancel_interrupts_backoff_in_slices(self):
        waits = []
        f = Fake(script=[RateLimited('429', 30)])
        out = run(self.d, make_items(3), fake=f, sleep=waits.append, should_stop=lambda: len(waits) >= 2)
        self.assertEqual(out.paused, 'cancelled')
        self.assertEqual(waits, [1, 1])
        self.assertEqual(len(f.calls), 1)

    def test_cancel_interrupts_rpm_wait(self):
        clock, waits = [1_000_000.0], []

        def sleep(sec):
            waits.append(sec)
            clock[0] += sec

        lim = RateLimiter(self.d / 'rate.json', 1, 100, now=lambda: clock[0], sleep=sleep)
        lim.acquire()
        with self.assertRaises(Cancelled):
            lim.acquire(lambda: len(waits) >= 3)
        self.assertEqual(waits, [1, 1, 1])

    def test_spent_before_counts_toward_cap(self):
        p = prefs(tier='paid', cost_cap_usd=0.5, price_in_per_mtok=1.0, price_out_per_mtok=2.0)
        f = Fake()
        out = run(self.d, make_items(3), p=p, fake=f, spent_before=0.4999999)
        self.assertEqual((out.paused, f.calls), ('cost_cap', []))
        out = run(self.d, make_items(3), p=p, fake=f, spent_before=0.4999999, allow_over_cap=True)
        self.assertIsNone(out.paused)
        self.assertLess(out.cost_usd, 0.01)  # chỉ tính phần của lần chạy này

    def test_thinking_tokens_in_estimate(self):
        items = make_items(5)
        base = dict(tier='paid', price_in_per_mtok=0.0, price_out_per_mtok=1000.0)
        low = plan_translation(items, 'dub', prefs(thinking='low', **base))
        high = plan_translation(items, 'dub', prefs(thinking='high', **base))
        self.assertAlmostEqual(low.cost_usd, low.output_tokens * 1000 / 1e6)
        self.assertAlmostEqual(high.cost_usd, 2 * low.cost_usd)

    def test_retry_is_split_to_fit_output_budget(self):
        items = make_items(40)
        p = prefs(max_output_tokens=1800)
        calls = []

        def bad_all(body):
            calls.append(len(body['items']))
            return Reply({'context': {}, 'items': []}, '', False, Usage(1, 1))

        f = Fake(script=[bad_all, bad_all])
        out = run(self.d, items, p=p, fake=f)
        parts = len(plan_translation(items, 'dub', p).chunks)
        self.assertEqual(out.requests, parts + parts)  # đợt đầu rỗng + gửi lại chia theo ngân sách
        self.assertTrue(all(len(c['items']) < 40 for c in f.calls))

    def test_bad_replies_are_failed_and_not_cached(self):
        items = [Item('a', '你好吗', 0, 2, 'A', 'cue'), Item('b', '好', 2, 4, 'A', 'cue'),
                 Item('c', '谢谢', 4, 6, 'A', 'cue'), Item('d', '再见', 6, 8, 'A', 'cue')]
        rows = [{'id': 'a', 'vi': 'Bạn khỏe 好 không'}, {'id': 'b', 'vi': '好'},
                {'id': 'c', 'vi': 'cảm ơn ' * 40}, {'id': 'd', 'vi': 'Tạm biệt'}]
        f = Fake(script=[reply(rows), reply([])])
        out = run(self.d, items, fake=f, mode='dub')
        self.assertEqual(out.texts, {'d': 'Tạm biệt'})
        self.assertEqual(out.failed, ['a', 'b', 'c'])
        cache = json.loads((self.d / 'translation-cache-v2.json').read_text(encoding='utf-8'))
        blob = json.dumps(cache, ensure_ascii=False)
        self.assertNotIn('好', blob)
        self.assertNotIn('cảm ơn', blob)
        out2 = run(self.d / 'v', items, fake=Fake(script=[reply([{'id': 'c', 'vi': 'cảm ơn bạn ' * 2}] + [{'id': 'a', 'vi': 'x'}])]), mode='vietsub')
        self.assertIn('a', out2.texts)

    def test_identical_allowed_when_zh_has_no_cjk(self):
        it = Item('a', 'OK', 0, 2, 'A', 'cue')
        out = run(self.d, [it], fake=Fake(script=[reply([{'id': 'a', 'vi': 'OK'}])]), mode='dub')
        self.assertEqual(out.texts, {'a': 'OK'})

    def test_mild_overrun_is_not_rejected(self):
        it = Item('a', '你好', 0, 2, 'A', 'cue')  # max_syllables = 9
        out = run(self.d, [it], fake=Fake(script=[reply([{'id': 'a', 'vi': ' '.join(['ừ'] * 12)}])]), mode='dub')
        self.assertEqual(out.failed, [])

    def test_prompt_per_mode(self):
        from dubflow.translate_job import SYSTEM_BY_MODE
        self.assertIn('"max_chars":24', SYSTEM_BY_MODE['vietsub'])
        self.assertNotIn('max_syllables":', SYSTEM_BY_MODE['vietsub'].split('VÍ DỤ')[1].split('\n')[0])
        for mode in ('tm', 'dub'):
            self.assertIn('"max_syllables":7', SYSTEM_BY_MODE[mode])
            self.assertNotIn('"max_chars":24', SYSTEM_BY_MODE[mode])
        self.assertIn('tối đa 2 dòng', SYSTEM_BY_MODE['vietsub'])

    def test_rate_limiter_rpm_and_rpd(self):
        clock, waits = [1_000_000.0], []

        def sleep(s):
            waits.append(s)
            clock[0] += s

        lim = RateLimiter(self.d / 'rate.json', 2, 3, now=lambda: clock[0], sleep=sleep)
        lim.acquire()
        clock[0] += 1
        lim.acquire()
        clock[0] += 1
        lim.acquire()
        self.assertEqual(len(waits), 1)
        self.assertAlmostEqual(waits[0], 58)
        with self.assertRaises(QuotaExhausted):
            lim.acquire()
        # file lưu đếm: bộ đếm mới đọc lại vẫn bị chặn
        with self.assertRaises(QuotaExhausted):
            RateLimiter(self.d / 'rate.json', 2, 3, now=lambda: clock[0], sleep=sleep).acquire()
        clock[0] += 86400 * 1.5
        lim.acquire()

    def test_run_log_has_no_key(self):
        class Keyed(Fake):
            key = KEY
        run(self.d, make_items(3), fake=Keyed())
        logs = list((self.d / 'translation-runs').glob('*.json'))
        self.assertEqual(len(logs), 1)
        text = logs[0].read_text(encoding='utf-8')
        self.assertNotIn(KEY, text)
        self.assertEqual(json.loads(text)['prompt_version'], 'p3-6-context-scan')

    def test_vietsub_items_carry_max_chars(self):
        f = Fake()
        run(self.d, make_items(3, dur=2.0), p=prefs(vietsub_cps=17), fake=f, mode='vietsub')
        for it in f.calls[0]['items']:
            self.assertEqual(it['max_chars'], round(2.0 * 17))
            self.assertNotIn('max_syllables', it)

    def test_tm_items_carry_max_syllables(self):
        f = Fake()
        run(self.d, make_items(3, dur=2.0), fake=f, mode='tm')
        for it in f.calls[0]['items']:
            self.assertEqual(it['max_syllables'], 9)
            self.assertNotIn('target_syllables', it)
            self.assertNotIn('max_chars', it)


if __name__ == '__main__':
    unittest.main()
