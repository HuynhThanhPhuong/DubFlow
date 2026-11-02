"""Fixes for the independent review: delete race / failure, SSE route, stale regions, cancellable translate, process trees."""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from dubflow import analysis_regions, pipeline as p, procjob
from dubflow.app import create_app
from dubflow.config import Settings
from dubflow.media import atomic_json
from dubflow.translate_api import Reply, Usage
from dubflow.translate_job import Abandoned, call_cancellable
from dubflow.worker import run_task


class AppCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Settings(root=Path(self.tmp.name), data_dir=Path(self.tmp.name) / 'data', system_voices=Path(self.tmp.name) / 'voices')
        self.app = create_app(self.cfg, start_worker=False)
        self.client = TestClient(self.app)
        self.store = self.app.state.store

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def job(self, **over):
        j = self.store.create_job(dict(dict(title='fixture', mode='vietsub', status='done', duration=10, width=128, height=96), **over))
        d = self.cfg.jobs_dir / j['id']
        d.mkdir(parents=True, exist_ok=True)
        (d / 'owned.bin').write_bytes(b'x')
        return j, d


class DeleteRaceTests(AppCase):
    def test_a_task_that_starts_between_the_check_and_the_delete_blocks_the_delete(self):
        j, d = self.job()
        original = self.store.active_tasks
        claimed = []

        def race():
            before = original()  # DELETE reads the (empty) snapshot ...
            self.store.enqueue(j['id'], 'analyze')  # ... then another tab enqueues and the worker claims it
            claimed.append(self.store.claim_next())
            self.store.begin_processing(j['id'])
            return before

        with patch.object(self.store, 'active_tasks', side_effect=race):
            r = self.client.delete(f"/api/jobs/{j['id']}")
        self.assertEqual(r.status_code, 409, r.text)
        self.assertIn('Hãy dừng tác vụ trước khi xóa', r.json()['detail'])
        self.assertIsNotNone(claimed[0])
        self.assertTrue((d / 'owned.bin').exists())
        job = self.store.get_job(j['id'])
        self.assertEqual(job['status'], 'processing')
        self.assertFalse(job.get('deleting'))

    def test_begin_delete_is_one_transaction_that_marks_the_job_and_blocks_enqueue_and_claim(self):
        j, _ = self.job()
        self.store.begin_delete(j['id'])
        self.assertTrue(self.store.get_job(j['id'])['deleting'])
        with self.assertRaises(ValueError):
            self.store.begin_delete(j['id'])  # a second delete request
        with self.assertRaisesRegex(ValueError, 'đang được xóa'):
            self.store.enqueue(j['id'], 'render')
        r = self.client.post(f"/api/jobs/{j['id']}/analyze")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.client.put(f"/api/jobs/{j['id']}/analysis-regions", json=dict(no_hard_subs=True)).status_code, 409)
        self.assertEqual(self.store.active_tasks(), [])
        self.store.abort_delete(j['id'])
        self.assertFalse(self.store.get_job(j['id'])['deleting'])
        self.assertIsInstance(self.store.enqueue(j['id'], 'render'), int)

    def test_busy_check_and_mark_cannot_interleave_with_a_pending_task(self):
        j, _ = self.job()
        self.store.enqueue(j['id'], 'analyze')
        with self.assertRaisesRegex(ValueError, 'Hãy dừng tác vụ'):
            self.store.begin_delete(j['id'])
        self.assertFalse(self.store.get_job(j['id']).get('deleting'))
        with self.assertRaises(KeyError):
            self.store.begin_delete('missing')

    def test_workers_never_claim_or_start_a_job_marked_deleting(self):
        j, _ = self.job()
        self.store.enqueue(j['id'], 'analyze')
        self.store.update_job(j['id'], deleting=True)  # e.g. marked right after the task was queued
        self.assertIsNone(self.store.claim_next())
        self.assertEqual(self.store.active_tasks(), [])  # the orphan task was cancelled, not left blocking the queue
        self.assertFalse(self.store.begin_processing(j['id']))
        other, _ = self.job()
        task_id = self.store.enqueue(other['id'], 'analyze')
        self.assertEqual(self.store.claim_task(task_id)['job_id'], other['id'])


class DeleteFailureTests(AppCase):
    def test_a_folder_that_cannot_be_moved_keeps_the_job_visible_and_retryable(self):
        j, d = self.job()
        with patch('dubflow.studio.os.rename', side_effect=PermissionError('locked')):
            r = self.client.delete(f"/api/jobs/{j['id']}")
        self.assertEqual(r.status_code, 409, r.text)
        self.assertIn('Dự án vẫn còn nguyên', r.json()['detail'])
        job = self.store.get_job(j['id'])
        self.assertIsNotNone(job)
        self.assertFalse(job.get('deleting'))
        self.assertTrue((d / 'owned.bin').exists())
        self.assertEqual(self.client.get(f"/api/jobs/{j['id']}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/jobs/{j['id']}").status_code, 204)  # retry works
        self.assertIsNone(self.store.get_job(j['id']))
        self.assertFalse(d.exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows refuses to rename a folder that holds an open file')
    def test_a_file_held_open_by_another_program_blocks_the_delete_without_losing_anything(self):
        j, d = self.job()
        with (d / 'owned.bin').open('rb'):
            r = self.client.delete(f"/api/jobs/{j['id']}")
            self.assertEqual(r.status_code, 409, r.text)
            self.assertIsNotNone(self.store.get_job(j['id']))
            self.assertTrue((d / 'owned.bin').exists())
        self.assertEqual(self.client.delete(f"/api/jobs/{j['id']}").status_code, 204)

    def test_a_failed_final_removal_leaves_only_a_quarantined_folder_that_the_next_start_sweeps(self):
        j, d = self.job()
        with patch('dubflow.studio.safe_rmtree', side_effect=PermissionError('locked')):
            r = self.client.delete(f"/api/jobs/{j['id']}")
        self.assertEqual(r.status_code, 204)
        self.assertIsNone(self.store.get_job(j['id']))
        self.assertFalse(d.exists())
        held = list((self.cfg.jobs_dir / '.trash').iterdir())
        self.assertEqual(len(held), 1)
        create_app(self.cfg, start_worker=False)  # a new server start finishes the job
        self.assertEqual(list((self.cfg.jobs_dir / '.trash').iterdir()), [])

    def test_a_failure_removing_the_rows_restores_the_folder_and_the_job(self):
        j, d = self.job()
        with patch.object(self.store, 'remove_job', side_effect=RuntimeError('db')):
            with self.assertRaises(RuntimeError):
                self.client.delete(f"/api/jobs/{j['id']}")
        self.assertTrue((d / 'owned.bin').exists())
        self.assertFalse(self.store.get_job(j['id']).get('deleting'))

    def test_a_crash_after_marking_does_not_leave_an_undeletable_ghost(self):
        j, d = self.job()
        self.store.begin_delete(j['id'])  # the server died here
        create_app(self.cfg, start_worker=False)
        self.assertFalse(self.store.get_job(j['id'])['deleting'])
        self.assertEqual(self.client.delete(f"/api/jobs/{j['id']}").status_code, 204)
        # died after the folder was quarantined but before the rows were removed
        k, folder = self.job()
        self.store.begin_delete(k['id'])
        trash = self.cfg.jobs_dir / '.trash'
        trash.mkdir(exist_ok=True)
        os.rename(folder, trash / f"{k['id']}.deadbeef")
        create_app(self.cfg, start_worker=False)
        self.assertIsNone(self.store.get_job(k['id']))
        self.assertEqual(list(trash.iterdir()), [])

    def test_collection_delete_reports_partial_failures_and_keeps_the_collection(self):
        c = self.client.post('/api/collections', json={'name': 'Bộ'}).json()
        a, da = self.job(collection_id=c['id'], title='Tập 1')
        b, db = self.job(collection_id=c['id'], title='Tập 2')
        real = os.rename

        def rename(src, dst, *args, **kw):
            if Path(src).name == b['id']:
                raise PermissionError('locked')
            return real(src, dst, *args, **kw)

        with patch('dubflow.studio.os.rename', side_effect=rename):
            r = self.client.delete(f"/api/collections/{c['id']}?videos=true")
        self.assertEqual(r.status_code, 409, r.text)
        detail = r.json()['detail']
        self.assertIn('Đã xóa 1/2 video', detail)
        self.assertIn('Tập 2', detail)
        self.assertIsNone(self.store.get_job(a['id']))
        self.assertTrue((db / 'owned.bin').exists())
        self.assertIsNotNone(self.store.get_job(b['id']))
        self.assertIsNotNone(self.store.get_record('collection', c['id']))
        self.assertEqual(self.client.delete(f"/api/collections/{c['id']}?videos=true").status_code, 204)
        self.assertIsNone(self.store.get_job(b['id']))
        self.assertIsNone(self.store.get_record('collection', c['id']))


class EventsRouteTests(AppCase):
    def test_the_real_events_route_streams_the_first_event_and_a_keepalive_and_tracks_the_stream(self):
        j, _ = self.job()
        route = next(r for r in self.app.routes if getattr(r, 'path', '') == '/api/jobs/{job_id}/events')
        idle = self.app.state.idle
        idle.heartbeat('tab')

        class Request:
            async def is_disconnected(self):
                return False

        real_sleep = asyncio.sleep

        async def quick(_):
            await real_sleep(0)

        async def consume():
            response = await route.endpoint(j['id'], Request())
            it = response.body_iterator
            first = await anext(it)
            self.assertTrue(first.startswith('data: '))
            self.assertEqual(json.loads(first[6:])['id'], j['id'])
            self.assertEqual(len(idle.open_streams()), 1)
            chunks = [await anext(it) for _ in range(1)]
            await it.aclose()
            return chunks

        with patch('dubflow.app.asyncio.sleep', quick):
            chunks = asyncio.run(consume())
        self.assertEqual(chunks, [': keepalive\n\n'])
        self.assertEqual(idle.open_streams(), [])  # released when the stream ended

    def test_events_end_quietly_when_the_job_is_deleted(self):
        j, _ = self.job()
        route = next(r for r in self.app.routes if getattr(r, 'path', '') == '/api/jobs/{job_id}/events')

        class Request:
            async def is_disconnected(self):
                return False

        async def consume():
            response = await route.endpoint(j['id'], Request())
            await anext(response.body_iterator)
            self.store.remove_job(j['id'])
            with self.assertRaises(StopAsyncIteration):
                await anext(response.body_iterator)

        real_sleep = asyncio.sleep

        async def quick(_):
            await real_sleep(0)

        with patch('dubflow.app.asyncio.sleep', quick):
            asyncio.run(consume())


class StaleRegionsTests(AppCase):
    OLD = dict(no_hard_subs=False, subtitle=[0, 60, 128, 30], logos=[], screen_text=[])

    def analysed_job(self):
        j, d = self.job(analysis_regions=self.OLD)
        src = d / 'source.mp4'
        src.write_bytes(b'fixture')
        self.store.update_job(j['id'], source_path=str(src))
        atomic_json(d / 'subtrack.json', dict(version=2, box=self.OLD['subtitle'], segments=[dict(s=1, e=2, text='old')]))
        atomic_json(d / 'regions.json', [])
        atomic_json(d / 'cues.json', [])
        atomic_json(d / p.REGIONS_APPLIED, dict(key=p.regions_key(analysis_regions.usable(self.OLD))))
        (d / 'clean.mp4').write_bytes(b'old-clean-video')
        st = src.stat()
        atomic_json(d / 'erase.json', dict(version=p.ERASE_VERSION, source_size=st.st_size, source_mtime_ns=st.st_mtime_ns, subtrack_hash=p.subtrack_hash(d)))
        return j, d, src

    def test_saved_regions_make_the_old_clean_video_and_the_export_stale_until_reanalysis(self):
        j, d, src = self.analysed_job()
        shown = self.client.get(f"/api/jobs/{j['id']}").json()
        self.assertFalse(shown['regions_stale'])
        self.assertIsNotNone(shown['clean_url'])
        new = dict(self.OLD, subtitle=[0, 40, 128, 30])
        self.assertEqual(self.client.put(f"/api/jobs/{j['id']}/analysis-regions", json=new).status_code, 200)
        self.assertTrue(p.erase_current(d, src, full=False))  # the clean video still matches its own inputs ...
        shown = self.client.get(f"/api/jobs/{j['id']}").json()
        self.assertTrue(shown['regions_stale'])  # ... but not the regions the user saved
        self.assertIsNone(shown['clean_url'])
        self.assertEqual(self.client.get(f"/api/jobs/{j['id']}/clean").status_code, 404)
        r = self.client.post(f"/api/jobs/{j['id']}/render")
        self.assertEqual((r.status_code, r.json()['detail']), (409, 'Vùng phân tích đã đổi, hãy phân tích lại trước khi xuất.'))
        self.assertEqual(self.store.active_tasks(), [])
        # the analysis re-stamps the regions it used: everything is current again
        atomic_json(d / p.REGIONS_APPLIED, dict(key=p.regions_key(analysis_regions.usable(new))))
        shown = self.client.get(f"/api/jobs/{j['id']}").json()
        self.assertFalse(shown['regions_stale'])
        self.assertIsNotNone(shown['clean_url'])
        self.assertNotEqual(self.client.post(f"/api/jobs/{j['id']}/render").json().get('detail'), p.REGIONS_STALE)

    def test_changing_only_a_logo_or_screen_text_box_is_stale_too(self):
        j, d, _ = self.analysed_job()
        for field, box in (('logos', [[5, 5, 40, 20]]), ('screen_text', [[10, 10, 50, 30]])):
            job = self.store.update_job(j['id'], analysis_regions=dict(self.OLD, **{field: box}))
            self.assertTrue(p.regions_stale(d, job), field)
        self.assertFalse(p.regions_stale(d, self.store.update_job(j['id'], analysis_regions=self.OLD)))

    def test_jobs_without_regions_or_not_analysed_yet_are_never_stale(self):
        j, d = self.job()
        self.assertFalse(p.regions_stale(d, j))
        j = self.store.update_job(j['id'], analysis_regions=self.OLD)
        self.assertFalse(p.regions_stale(d, j))  # no regions.json: nothing was built from other regions

    def test_artefacts_from_before_the_stamp_are_compared_by_their_own_keys(self):
        j, d, _ = self.analysed_job()
        (d / p.REGIONS_APPLIED).unlink()
        cfg = analysis_regions.usable(self.OLD)
        atomic_json(d / 'ocr-complete.json', dict(region_mode=True, screen_key=analysis_regions.screen_key(cfg)))
        atomic_json(d / 'source-build.json', dict(source_key=analysis_regions.source_key(cfg)))
        self.assertFalse(p.regions_stale(d, j))
        moved = dict(self.OLD, subtitle=[0, 40, 128, 30])
        self.assertTrue(p.regions_stale(d, self.store.update_job(j['id'], analysis_regions=moved)))
        self.assertTrue(p.regions_stale(d, self.store.update_job(j['id'], analysis_regions=dict(self.OLD, logos=[[1, 1, 20, 20]]))))
        (d / 'ocr-complete.json').unlink()  # built by the old automatic search
        self.assertTrue(p.regions_stale(d, self.store.update_job(j['id'], analysis_regions=self.OLD)))

    def test_analysis_stamps_regions_json_and_the_render_key_follows_the_stamp(self):
        _, d = self.job()
        cfg = analysis_regions.usable(dict(no_hard_subs=True, subtitle=None, logos=[[2, 2, 30, 20]], screen_text=[]))
        p.region_rows(d, d / 'source.mp4', dict(duration=10), SimpleNamespace(ocr_python=None), lambda *a: None, [], cfg)
        self.assertEqual(p.read(d / p.REGIONS_APPLIED), dict(key=p.regions_key(cfg)))
        self.assertEqual(len(p.read(d / 'regions.json')), 1)
        command = ['ffmpeg', '-i', 'x.mp4', 'out.mp4']
        with_stamp = p.render_key(d, command, 'g', dict(width=1, height=1))
        (d / p.REGIONS_APPLIED).unlink()
        self.assertNotEqual(with_stamp, p.render_key(d, command, 'g', dict(width=1, height=1)))
        atomic_json(d / p.REGIONS_APPLIED, dict(key='other'))
        self.assertNotEqual(with_stamp, p.render_key(d, command, 'g', dict(width=1, height=1)))

    def test_the_pipeline_itself_refuses_a_stale_render_in_the_worker(self):
        j, d, src = self.analysed_job()
        self.store.update_job(j['id'], analysis_regions=dict(self.OLD, subtitle=[0, 40, 128, 30]), status='awaiting_review')
        atomic_json(d / 'cues.json', [dict(id='c1', start=0, end=2, speaker='A', original='你好', text='Xin chào')])
        task_id = self.store.enqueue(j['id'], 'render')
        task = self.store.claim_task(task_id)
        run_task(task, self.cfg, self.store)
        job = self.store.get_job(j['id'])
        self.assertEqual(job['status'], 'awaiting_review')
        self.assertIn('Vùng phân tích đã đổi', job['error'])


class BlockingProvider:
    name = 'gemini'
    model = 'gemini-x'

    def __init__(self):
        self.started, self.release, self.closed = threading.Event(), threading.Event(), False

    def generate(self, system, user, schema, max_output_tokens):
        self.started.set()
        self.release.wait(30)
        raise RuntimeError('too late')

    def close(self):
        self.closed = True


class TranslateCancelTests(AppCase):
    def test_call_cancellable_returns_raises_and_abandons(self):
        self.assertEqual(call_cancellable(lambda: 41 + 1, lambda: False), 42)
        with self.assertRaises(ZeroDivisionError):
            call_cancellable(lambda: 1 / 0, lambda: False)
        gate, abandoned = threading.Event(), []
        started = time.monotonic()
        with self.assertRaises(Abandoned):
            call_cancellable(lambda: gate.wait(30), lambda: time.monotonic() - started > .3, lambda: abandoned.append(1), poll=.05)
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(abandoned, [1])
        gate.set()

    def test_stop_during_an_in_flight_request_cancels_the_job_within_seconds_and_shows_stopping(self):
        values = dict(gemini_api_key='AIza-SECRET-KEY-123456', gemini_model='gemini-x')
        self.assertEqual(self.client.put('/api/settings', json=values).status_code, 200)
        j, d = self.job(status='awaiting_review')
        base = f"/api/jobs/{j['id']}"
        atomic_json(d / 'cues.json', [dict(id='c1', start=0, end=2, speaker='A', original='你好', text='')])
        atomic_json(d / 'regions.json', [])
        provider = BlockingProvider()
        with patch('dubflow.translate_run.make_provider', return_value=provider):
            self.assertEqual(self.client.post(base + '/translate', json={}).status_code, 200)
            task = self.store.claim_next()
            runner = threading.Thread(target=run_task, args=(task, self.cfg, self.store))
            runner.start()
            try:
                self.assertTrue(provider.started.wait(10))  # the HTTP call is now blocked
                started = time.monotonic()
                shown = self.client.post(base + '/cancel').json()
                self.assertEqual(shown['status'], 'cancelled')
                self.assertTrue(shown['stopping'])  # the worker has not confirmed yet
                self.assertIn('Đang dừng', shown['activity'][-1]['msg'])
                runner.join(10)
                self.assertFalse(runner.is_alive(), 'the worker is still blocked in the HTTP request')
                self.assertLess(time.monotonic() - started, 5)
            finally:
                provider.release.set()
                runner.join(5)
        job = self.store.get_job(j['id'])
        self.assertEqual(job['status'], 'cancelled')
        self.assertEqual(job['activity'][-1]['msg'], 'Đã dừng.')
        self.assertFalse(self.client.get(base).json()['stopping'])
        self.assertEqual(self.store.active_tasks(), [])
        self.assertTrue(provider.closed)
        self.assertEqual(json.loads((d / 'cues.json').read_text(encoding='utf-8'))[0]['text'], '')  # nothing half-applied


@unittest.skipUnless(os.name == 'nt', 'Windows process tree handling')
class ProcessTreeTests(unittest.TestCase):
    PARENT = ("import pathlib,subprocess,sys,time\n"
              "c=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\n"
              "pathlib.Path(sys.argv[1]).write_text(str(c.pid))\n"
              "time.sleep(60)\n")

    def start_tree(self, tmp):
        pidfile = Path(tmp) / 'child.pid'
        script = Path(tmp) / 'parent.py'
        script.write_text(self.PARENT, encoding='utf-8')
        parent = subprocess.Popen([sys._base_executable, str(script), str(pidfile)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: parent.poll() is None and parent.kill())
        deadline = time.monotonic() + 15
        while not pidfile.exists() and time.monotonic() < deadline:
            time.sleep(.05)
        self.assertTrue(pidfile.exists(), 'fixture child did not start')
        time.sleep(.2)
        child = int(pidfile.read_text())
        self.addCleanup(lambda: procjob.pid_alive(child) and subprocess.run(['taskkill', '/PID', str(child), '/F'], capture_output=True))
        return parent, child

    def test_job_object_ends_the_whole_tree_and_the_report_counts_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            pidfile = Path(tmp) / 'child.pid'
            script = Path(tmp) / 'parent.py'
            script.write_text(self.PARENT, encoding='utf-8')
            parent = subprocess.Popen([sys._base_executable, str(script), str(pidfile)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            result = {}
            thread = threading.Thread(target=lambda: result.update(code=_wait_cancelled(parent, tmp)))
            thread.start()
            deadline = time.monotonic() + 15
            while not pidfile.exists() and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertTrue(pidfile.exists())
            child = int(pidfile.read_text())
            self.addCleanup(lambda: procjob.pid_alive(child) and subprocess.run(['taskkill', '/PID', str(child), '/F'], capture_output=True))
            self.assertTrue(procjob.pid_alive(child))
            report = p.kill_children_report()
            thread.join(10)
            self.assertEqual((report['killed'], report['failed'], report['failed_pids']), (1, 0, []))
            self.assertIsNotNone(parent.poll())
            deadline = time.monotonic() + 5
            while procjob.pid_alive(child) and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertFalse(procjob.pid_alive(child), 'the child survived the stop')

    def test_a_refused_taskkill_is_reported_as_failed_and_not_counted_as_killed(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent, child = self.start_tree(tmp)
            self.assertIn(child, procjob.descendants(parent.pid))

            def refused(cmd, *a, **kw):  # taskkill answers "Access denied"; the parent ends some other way
                if parent.poll() is None and str(parent.pid) in cmd:
                    parent.kill()
                return subprocess.CompletedProcess(cmd, 1, b'', b'ERROR: Access denied')

            with patch.object(p, 'adopt'), patch.object(p.subprocess, 'run', side_effect=refused):
                p.LIVE_PROCESSES.add(parent)
                try:
                    report = p.kill_children_report()
                finally:
                    p.LIVE_PROCESSES.discard(parent)
            self.assertEqual((report['killed'], report['failed'], report['failed_pids']), (0, 1, [parent.pid]))
            self.assertTrue(procjob.pid_alive(child))  # truthfully reported: it is still running

    def test_taskkill_fallback_counts_success_when_every_descendant_is_gone(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent, child = self.start_tree(tmp)
            with patch.object(p, 'adopt'):
                p.LIVE_PROCESSES.add(parent)
                try:
                    report = p.kill_children_report()
                finally:
                    p.LIVE_PROCESSES.discard(parent)
            # whatever the OS allows here, the report must match what is really left running
            self.assertEqual(report['killed'] + report['failed'], 1)
            self.assertEqual(report['killed'] == 1, not procjob.pid_alive(child))

    def test_a_process_that_exited_normally_is_not_counted(self):
        done = subprocess.Popen([sys.executable, '-c', 'pass'])
        done.wait()
        p.LIVE_PROCESSES.add(done)
        try:
            self.assertEqual(p.kill_children_report(), dict(killed=0, failed=0, failed_pids=[]))
        finally:
            p.LIVE_PROCESSES.discard(done)


def _wait_cancelled(process, directory):
    try:
        return p.wait_owned(process, directory)
    except p.Cancelled:
        return 'cancelled'


if __name__ == '__main__':
    unittest.main()
