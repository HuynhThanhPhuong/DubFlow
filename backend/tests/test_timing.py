import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from dubflow import timing
from dubflow.worker import run_task
from test_translate_flow import Base, Fake as FlowFake
from test_translate_job import Fake, make_items, prefs, run


def iso(seconds_ago):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


class ChunkProgressTest(unittest.TestCase):
    def test_progress_reported_per_chunk(self):
        with tempfile.TemporaryDirectory() as d:
            calls = []
            items = make_items(40, gaps={21: 5.0})
            run(d, items, p=prefs(max_output_tokens=1800), on_progress=lambda a, b: calls.append((a, b)))
        self.assertEqual(calls, [(0, 40), (21, 40), (40, 40)])


class EstimateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        self.job = dict(mode='tm', duration=100, cue_count=10, status='processing')

    def test_defaults_without_history(self):
        est = timing.estimates(self.d, self.job)
        self.assertEqual(list(est), ['analyze', 'translate', 'synthesize', 'render'])
        self.assertEqual(est['synthesize'], dict(seconds=80, source='default'))
        self.assertEqual(set(timing.estimates(self.d, dict(self.job, mode='vietsub'))), {'analyze', 'translate', 'render'})

    def test_median_of_history_same_mode_only(self):
        for secs in (10, 20, 1000):  # per cue: 1, 2, 100 -> median 2
            timing.record(self.d, 'translate', 'tm', iso(secs), iso(0), video_seconds=50, cue_count=10)
        timing.record(self.d, 'translate', 'dub', iso(500), iso(0), video_seconds=50, cue_count=10)
        self.assertEqual(timing.estimate_stage(self.d, 'translate', self.job), dict(seconds=20, source='history'))

    def test_only_last_20_used(self):
        for _ in range(30):
            timing.record(self.d, 'render', 'tm', iso(1000), iso(0), video_seconds=100, cue_count=1)
        for _ in range(20):
            timing.record(self.d, 'render', 'tm', iso(200), iso(0), video_seconds=100, cue_count=1)
        self.assertEqual(timing.estimate_stage(self.d, 'render', self.job)['seconds'], 200)

    def test_eta_never_negative_and_uses_detail(self):
        est = timing.estimates(self.d, self.job)
        job = dict(self.job, stage_step='translate', stage_started_at=iso(10_000))
        self.assertEqual(timing.eta_seconds(job, est), 0)
        job = dict(self.job, stage_step='translate', stage_started_at=iso(10), stage_detail=dict(done=5, total=10, unit='câu'))
        self.assertAlmostEqual(timing.eta_seconds(job, est), 10, delta=1)
        self.assertIsNone(timing.eta_seconds(dict(self.job, status='done', stage_step='translate', stage_started_at=iso(1)), est))
        self.assertIsNone(timing.eta_seconds(self.job, est))


class WorkerTimingTest(Base):
    def test_translate_records_timing_and_progress_fields(self):
        self.configure()
        self.make_job()
        self.store.update_job(self.jid, cue_count=3)
        seen = []
        orig = self.store.update_active_job

        def spy(job_id, **values):
            if values.get('stage_detail'):
                seen.append((values['progress'], values['stage_detail']))
            return orig(job_id, **values)

        with patch.object(self.store, 'update_active_job', spy):
            job = self.run_translate(FlowFake())
        self.assertEqual([d for _, d in seen][-1], dict(done=3, total=3, unit='câu'))
        self.assertTrue(all(45 <= p <= 49 for p, _ in seen))
        lines = [json.loads(x) for x in timing.stats_file(self.cfg.data_dir).read_text(encoding='utf-8').splitlines()]
        self.assertEqual([r['stage'] for r in lines], ['translate'])
        self.assertEqual(lines[0]['mode'], 'vietsub')
        self.assertIsNone(job['stage_step'])
        public = self.client.get(self.base).json()
        for key in ('stage_estimates', 'stage_started_at', 'stage_detail', 'eta_seconds', 'stage_step'):
            self.assertIn(key, public)
        self.assertEqual(public['stage_estimates']['translate']['source'], 'history')
        self.assertIn(public['id'], [j['id'] for j in self.client.get('/api/jobs').json()])
        self.assertIn('stage_estimates', self.client.get('/api/jobs').json()[0])


if __name__ == '__main__':
    unittest.main()
