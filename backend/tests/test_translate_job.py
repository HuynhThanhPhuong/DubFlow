import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from dubflow.translate_api import QuotaExhausted, RateLimited, Reply, Usage
from dubflow.translate_job import Item, RateLimiter, plan_translation, run_translation

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

    def test_truncated_reply_retries_only_missing_ids(self):
        items = make_items(5)
        f = Fake(script=[reply([{'id': 'c0', 'vi': 'a'}, {'id': 'c1', 'vi': 'b'}], truncated=True)])
        out = run(self.d, items, fake=f)
        self.assertEqual([i['id'] for i in f.calls[1]['items']], ['c2', 'c3', 'c4'])
        self.assertEqual(len(out.texts), 5)

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
        self.assertEqual(waits, [37])
        self.assertEqual(len(out.texts), 3)

    def test_rate_limited_backoff_and_give_up(self):
        waits = []
        f = Fake(script=[RateLimited('429')] * 4)
        with self.assertRaises(RateLimited):
            run(self.d, make_items(3), fake=f, sleep=waits.append)
        self.assertEqual(waits, [10, 30, 60])

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
        self.assertEqual(json.loads(text)['prompt_version'], 'p3-1')

    def test_vietsub_items_carry_max_chars(self):
        f = Fake()
        run(self.d, make_items(3, dur=2.0), p=prefs(vietsub_cps=17), fake=f, mode='vietsub')
        for it in f.calls[0]['items']:
            self.assertEqual(it['max_chars'], round(2.0 * 17))
            self.assertNotIn('target_syllables', it)

    def test_tm_items_carry_target_syllables(self):
        f = Fake()
        run(self.d, make_items(3, dur=2.0), fake=f, mode='tm')
        for it in f.calls[0]['items']:
            self.assertEqual(it['target_syllables'], 9)
            self.assertNotIn('max_chars', it)


if __name__ == '__main__':
    unittest.main()
