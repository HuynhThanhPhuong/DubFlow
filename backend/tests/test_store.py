import tempfile
import unittest
from pathlib import Path

from dubflow.store import ACTIVITY_LIMIT, Store, push_activity


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'app.sqlite')

    def tearDown(self):
        self.tmp.cleanup()

    def test_job_survives_reopening_database(self):
        job = self.store.create_job({'title': 'Video thử', 'mode': 'vietsub', 'filename': 'a.mp4'})
        reopened = Store(self.store.path)
        self.assertEqual(reopened.get_job(job['id'])['title'], 'Video thử')
        self.assertEqual(reopened.get_job(job['id'])['status'], 'created')

    def test_cannot_enqueue_same_job_twice(self):
        job = self.store.create_job({'title': 'x', 'mode': 'dub'})
        self.store.enqueue(job['id'], 'analyze')
        with self.assertRaises(ValueError):
            self.store.enqueue(job['id'], 'analyze')

    def test_claim_queue_serializes_work(self):
        a = self.store.create_job({'title': 'a', 'mode': 'dub'})
        b = self.store.create_job({'title': 'b', 'mode': 'tm'})
        self.store.enqueue(a['id'], 'analyze')
        self.store.enqueue(b['id'], 'analyze')
        first = self.store.claim_next()
        self.assertEqual(first['job_id'], a['id'])
        self.assertIsNone(self.store.claim_next())
        self.store.finish_task(first['id'])
        self.assertEqual(self.store.claim_next()['job_id'], b['id'])

    def test_events_persist_and_increase(self):
        j = self.store.create_job({'title': 'a', 'mode': 'vietsub'})
        self.store.event(j['id'], 'transcribing', 'Nhận dạng', 15)
        self.store.event(j['id'], 'awaiting_review', 'Duyệt lời', 45)
        events = self.store.events(j['id'])
        self.assertEqual(events[-1]['message'], 'Duyệt lời')
        self.assertLess(events[-2]['id'], events[-1]['id'])

    def test_cancelled_running_job_keeps_gpu_slot_until_exit(self):
        a = self.store.create_job({'title': 'a', 'mode': 'dub'})
        b = self.store.create_job({'title': 'b', 'mode': 'tm'})
        self.store.enqueue(a['id'], 'render')
        task = self.store.claim_next()
        self.store.cancel(a['id'])
        self.store.enqueue(b['id'], 'render')
        self.assertIsNone(self.store.claim_next())
        self.store.finish_task(task['id'], 'cancelled')
        self.assertEqual(self.store.claim_next()['job_id'], b['id'])

    def test_recovery_does_not_restart_a_cancelled_running_job(self):
        job = self.store.create_job({'title': 'a', 'mode': 'dub'})
        self.store.enqueue(job['id'], 'render')
        self.store.claim_next()
        self.store.cancel(job['id'])
        reopened = Store(self.store.path)
        reopened.recover()
        self.assertEqual(reopened.get_job(job['id'])['status'], 'cancelled')
        self.assertIsNone(reopened.claim_next())

    def test_start_cannot_overwrite_a_concurrent_cancellation(self):
        job = self.store.create_job({'title':'a','mode':'dub'})
        self.store.enqueue(job['id'],'render')
        self.store.claim_next()
        self.store.cancel(job['id'])
        self.assertFalse(self.store.begin_processing(job['id']))
        self.assertEqual(self.store.get_job(job['id'])['status'],'cancelled')

    def test_activity_is_a_capped_ring_without_consecutive_duplicates(self):
        job = {}
        for n in range(ACTIVITY_LIMIT + 7):
            job['activity'] = push_activity(job, f'bước {n}')
            job['activity'] = push_activity(job, f'bước {n}')
        rows = job['activity']
        self.assertEqual(len(rows), ACTIVITY_LIMIT)
        self.assertEqual(rows[-1]['msg'], f'bước {ACTIVITY_LIMIT + 6}')
        self.assertEqual(rows[0]['msg'], 'bước 7')
        self.assertTrue(rows[0]['t'])
        self.assertEqual(push_activity({}, '   '), [])

    def test_begin_processing_records_activity_and_keeps_history(self):
        job = self.store.create_job({'title': 'x', 'mode': 'dub', 'activity': [{'t': 'a', 'msg': 'cũ'}]})
        self.store.enqueue(job['id'], 'translate')
        self.store.claim_next()
        self.assertTrue(self.store.begin_processing(job['id']))
        msgs = [r['msg'] for r in self.store.get_job(job['id'])['activity']]
        self.assertEqual(msgs, ['cũ', 'Máy xử lý đã nhận tác vụ.'])

    def test_queue_info_positions(self):
        a, b, c = (self.store.create_job({'title': t, 'mode': 'dub'}) for t in 'abc')
        for j in (a, b, c):
            self.store.enqueue(j['id'], 'analyze')
        self.assertEqual(self.store.queue_info(a['id']), {'position': 1, 'running_ahead': False})
        self.assertEqual(self.store.queue_info(c['id']), {'position': 3, 'running_ahead': False})
        self.store.claim_next()
        self.assertIsNone(self.store.queue_info(a['id']))
        self.assertEqual(self.store.queue_info(b['id']), {'position': 1, 'running_ahead': True})
        self.assertEqual(self.store.queue_info(c['id']), {'position': 2, 'running_ahead': True})


if __name__ == '__main__':
    unittest.main()
