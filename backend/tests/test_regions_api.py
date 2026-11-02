"""User-drawn analysis regions, frame preview, stop-all and idle shutdown."""
import json
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from dubflow import analysis_regions, lifecycle
from dubflow.app import create_app
from dubflow.config import Settings
from dubflow.media import atomic_json


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class RegionsApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = Settings(data_dir=Path(self.tmp.name), system_voices=Path(self.tmp.name) / 'system')
        self.app = create_app(self.settings, start_worker=False)
        self.client = TestClient(self.app)
        self.store = self.app.state.store

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def job(self, **values):
        j = self.store.create_job(dict(dict(title='r', mode='vietsub', duration=2, width=320, height=240, status='awaiting_regions'), **values))
        (self.settings.jobs_dir / j['id']).mkdir()
        return j

    def with_video(self, **values):
        j = self.job(**values)
        source = self.settings.jobs_dir / j['id'] / 'source.mp4'
        subprocess.run([self.settings.ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc=s=320x240:r=10:d=2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(source)], check=True)
        self.store.update_job(j['id'], source_path=str(source))
        return j

    def put(self, j, **body):
        return self.client.put(f"/api/jobs/{j['id']}/analysis-regions", json=body)

    # -- PUT /analysis-regions ------------------------------------------------------------------------------
    def test_valid_regions_are_stored_and_shown_in_the_job(self):
        j = self.job()
        self.assertIsNone(self.client.get(f"/api/jobs/{j['id']}").json()['analysis_regions'])
        r = self.put(j, no_hard_subs=False, subtitle=[10, 180, 300, 40], logos=[[5, 5, 40, 20]], screen_text=[[100, 50, 80, 30]])
        self.assertEqual(r.status_code, 200, r.text)
        want = dict(no_hard_subs=False, subtitle=[10, 180, 300, 40], logos=[[5, 5, 40, 20]], screen_text=[[100, 50, 80, 30]])
        self.assertEqual(r.json(), want)
        self.assertEqual(self.client.get(f"/api/jobs/{j['id']}").json()['analysis_regions'], want)
        self.assertEqual(json.loads((self.settings.jobs_dir / j['id'] / 'job.json').read_text(encoding='utf-8'))['analysis_regions'], want)

    def test_boxes_are_clamped_into_the_frame_and_rounded(self):
        j = self.job()
        r = self.put(j, subtitle=[-20, 200.4, 400, 100.2], logos=[[300, 220, 100, 100]])
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['subtitle'], [0, 200, 320, 40])  # x -20..380 -> 0..320, y 200.4..300.6 -> 200..240
        self.assertEqual(r.json()['logos'], [[300, 220, 20, 20]])

    def test_too_small_or_outside_boxes_are_refused_in_vietnamese(self):
        j = self.job()
        for body in (dict(subtitle=[10, 10, 5, 40]), dict(subtitle=[10, 10, 100, 40], logos=[[400, 10, 50, 50]]),
                     dict(subtitle=[10, 10, 100, 40], screen_text=[[10, 10, 100, 7]])):
            r = self.put(j, **body)
            self.assertEqual(r.status_code, 422, body)
            self.assertIn('tối thiểu 8 px', r.json()['detail'])
        self.assertIsNone(self.store.get_job(j['id']).get('analysis_regions'))

    def test_needs_a_subtitle_box_or_no_hard_subs(self):
        j = self.job()
        r = self.put(j, logos=[[5, 5, 40, 20]])
        self.assertEqual(r.status_code, 422)
        self.assertIn('vùng sub', r.json()['detail'])
        ok = self.put(j, no_hard_subs=True, subtitle=[10, 10, 100, 40], logos=[[5, 5, 40, 20]])
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json(), dict(no_hard_subs=True, subtitle=None, logos=[[5, 5, 40, 20]], screen_text=[]))
        self.assertEqual(self.put(j, subtitle=[1, 2]).status_code, 422)  # not a box

    def test_busy_job_cannot_change_regions(self):
        j = self.job(status='processing')
        r = self.put(j, subtitle=[10, 10, 100, 40])
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()['detail'], 'Tạm dừng tác vụ trước khi sửa dự án.')
        self.assertEqual(self.put(self.job(), subtitle=[10, 10, 100, 40]).status_code, 200)
        self.assertEqual(self.client.put('/api/jobs/missing/analysis-regions', json={'no_hard_subs': True}).status_code, 404)

    def test_changing_regions_of_an_exported_video_invalidates_it(self):
        j = self.job(status='done')
        self.put(j, subtitle=[10, 10, 100, 40])
        self.assertEqual(self.store.get_job(j['id'])['status'], 'awaiting_review')
        self.store.update_job(j['id'], status='awaiting_review', progress=45)
        self.put(j, subtitle=[10, 10, 100, 40])  # unchanged: nothing happens
        self.assertEqual(self.store.get_job(j['id'])['progress'], 45)

    def test_setting_regions_keeps_a_job_that_waits_for_them_waiting(self):
        j = self.job()
        self.put(j, subtitle=[10, 10, 100, 40])
        self.assertEqual(self.store.get_job(j['id'])['status'], 'awaiting_regions')

    # -- analyze needs regions ------------------------------------------------------------------------------
    def test_analyze_is_refused_until_regions_are_valid(self):
        j = self.job()
        r = self.client.post(f"/api/jobs/{j['id']}/analyze")
        self.assertEqual((r.status_code, r.json()['detail']), (409, 'Hãy chọn vùng sub trước khi phân tích.'))
        self.assertEqual(self.store.active_tasks(), [])
        old = self.job(status='awaiting_review')  # a job from before regions existed
        self.assertEqual(self.client.post(f"/api/jobs/{old['id']}/analyze?reset_source=1").status_code, 409)
        self.put(j, subtitle=[10, 10, 100, 40])
        r = self.client.post(f"/api/jobs/{j['id']}/analyze")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([t['action'] for t in self.store.active_tasks()], ['analyze'])
        self.assertEqual(r.json()['analysis_regions']['subtitle'], [10, 10, 100, 40])

    def test_analyze_accepts_no_hard_subs_without_a_box(self):
        j = self.job()
        self.put(j, no_hard_subs=True)
        self.assertEqual(self.client.post(f"/api/jobs/{j['id']}/analyze").status_code, 200)

    def test_automatic_logo_detection_is_off_once_regions_are_chosen(self):
        j = self.job()
        self.put(j, subtitle=[10, 10, 100, 40])
        self.store.update_job(j['id'], source_path=str(self.settings.jobs_dir / j['id'] / 'source.mp4'))
        r = self.client.post(f"/api/jobs/{j['id']}/detect-logos", json={})
        self.assertEqual(r.status_code, 409)

    def test_analysis_regions_helpers(self):
        self.assertIsNone(analysis_regions.usable(None))
        self.assertIsNone(analysis_regions.usable(dict(no_hard_subs=False, subtitle=None)))
        self.assertIsNotNone(analysis_regions.usable(dict(no_hard_subs=True)))
        a = analysis_regions.usable(dict(no_hard_subs=False, subtitle=[1, 2, 30, 40], logos=[[1, 1, 9, 9]], screen_text=[]))
        b = dict(a, logos=[[2, 2, 9, 9]])
        self.assertEqual(analysis_regions.source_key(a), analysis_regions.source_key(b))  # logos do not decide the source cues
        self.assertNotEqual(analysis_regions.source_key(a), analysis_regions.source_key(dict(a, subtitle=[1, 2, 30, 41])))
        self.assertNotEqual(analysis_regions.screen_key(a), analysis_regions.screen_key(dict(a, screen_text=[[1, 1, 9, 9]])))

    # -- GET /frame -----------------------------------------------------------------------------------------
    def test_frame_is_a_jpeg_cached_per_tenth_of_a_second(self):
        j = self.with_video()
        r = self.client.get(f"/api/jobs/{j['id']}/frame?t=1.04")
        self.assertEqual(r.status_code, 200, r.text[:200])
        self.assertEqual(r.headers['content-type'], 'image/jpeg')
        self.assertTrue(r.content.startswith(b'\xff\xd8'))
        folder = self.settings.jobs_dir / j['id'] / 'frames'
        self.assertEqual([p.name for p in folder.iterdir()], ['10.jpg'])
        stamp = (folder / '10.jpg').stat().st_mtime_ns
        again = self.client.get(f"/api/jobs/{j['id']}/frame?t=0.96")  # rounds to the same tenth
        self.assertEqual(again.content, r.content)
        self.assertEqual((folder / '10.jpg').stat().st_mtime_ns, stamp)
        other = self.client.get(f"/api/jobs/{j['id']}/frame?t=0.3")
        self.assertNotEqual(other.content, r.content)
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ['10.jpg', '3.jpg'])

    def test_frame_clamps_to_the_video_and_rejects_bad_times(self):
        j = self.with_video()
        self.assertEqual(self.client.get(f"/api/jobs/{j['id']}/frame?t=99").status_code, 200)
        self.assertEqual(self.client.get(f"/api/jobs/{j['id']}/frame").status_code, 200)  # default t=0
        self.assertEqual(self.client.get(f"/api/jobs/{j['id']}/frame?t=-1").status_code, 422)
        self.assertEqual(self.client.get(f"/api/jobs/{j['id']}/frame?t=nan").status_code, 422)
        self.assertEqual(self.client.get(f"/api/jobs/{j['id']}/frame?t=abc").status_code, 422)
        self.assertEqual(self.client.get('/api/jobs/missing/frame?t=1').status_code, 404)
        no_source = self.job()
        self.assertEqual(self.client.get(f"/api/jobs/{no_source['id']}/frame?t=1").status_code, 404)

    # -- stop-all -------------------------------------------------------------------------------------------
    def test_stop_all_cancels_queued_and_running_tasks_and_reports_counts(self):
        a, b, c = self.job(), self.job(), self.job()
        for j in (a, b, c):
            self.put(j, no_hard_subs=True)
        self.client.post(f"/api/jobs/{a['id']}/analyze")
        self.client.post(f"/api/jobs/{b['id']}/analyze")
        self.client.post(f"/api/jobs/{c['id']}/analyze")
        running = self.store.claim_next()  # the worker took the first one
        self.assertEqual(running['job_id'], a['id'])
        with patch('dubflow.pipeline.kill_children', return_value=2) as kill:
            r = self.client.post('/api/tasks/stop-all')
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), dict(cancelled=3, queued=2, running=1, jobs=3, processes_killed=2))
        kill.assert_called_once()
        for j in (a, b, c):
            self.assertEqual(self.store.get_job(j['id'])['status'], 'cancelled')
            self.assertTrue((self.settings.jobs_dir / j['id'] / 'cancel.request').exists())
        self.assertEqual([t for t in self.store.active_tasks() if t['state'] == 'pending'], [])
        self.assertEqual(self.client.post('/api/tasks/stop-all').json()['cancelled'], 1)  # the running one is only freed by its worker

    def test_stop_all_with_nothing_running(self):
        r = self.client.post('/api/tasks/stop-all')
        self.assertEqual((r.status_code, r.json()['cancelled'], r.json()['jobs']), (200, 0, 0))

    def test_per_video_cancel_still_works(self):
        j = self.job()
        self.put(j, no_hard_subs=True)
        self.client.post(f"/api/jobs/{j['id']}/analyze")
        r = self.client.post(f"/api/jobs/{j['id']}/cancel")
        self.assertEqual((r.status_code, r.json()['status']), (200, 'cancelled'))

    # -- heartbeat / bye --------------------------------------------------------------------------------------
    def test_heartbeat_and_bye_endpoints_feed_the_monitor(self):
        idle = self.app.state.idle
        clock = Clock()
        idle.clock = clock
        self.assertFalse(idle.expired())
        r = self.client.post('/api/client/heartbeat', json={'tab': 'a'})
        self.assertEqual((r.status_code, r.json()['ok']), (200, True))
        self.assertTrue(idle.seen)
        self.assertEqual(self.client.post('/api/client/heartbeat').status_code, 200)  # no body (anonymous tab)
        self.assertEqual(self.client.post('/api/client/bye', content=b'not json').status_code, 200)
        self.assertEqual(self.client.post('/api/client/bye', json={'tab': 'a'}).status_code, 200)


class IdleMonitorTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.idle = lifecycle.IdleMonitor(timeout=30, grace=30, clock=self.clock)

    def test_never_idle_before_a_first_heartbeat(self):
        self.clock.now += 3600
        self.assertFalse(self.idle.expired())
        self.idle.bye('x')
        self.assertFalse(self.idle.expired())

    def test_idle_after_30_seconds_without_heartbeat(self):
        self.idle.heartbeat('a')
        self.clock.now += 29.9
        self.assertFalse(self.idle.expired())
        self.idle.heartbeat('a')
        self.clock.now += 29.9
        self.assertFalse(self.idle.expired())
        self.clock.now += .2
        self.assertTrue(self.idle.expired())

    def test_one_live_tab_keeps_the_server_up(self):
        self.idle.heartbeat('a')
        self.idle.heartbeat('b')
        for _ in range(5):
            self.clock.now += 20
            self.idle.heartbeat('b')
        self.assertFalse(self.idle.expired())
        self.clock.now += 31
        self.assertTrue(self.idle.expired())

    def test_bye_of_the_last_tab_waits_the_grace_period_for_a_reload(self):
        self.idle.heartbeat('a')
        self.clock.now += 5
        self.idle.bye('a')
        self.clock.now += 29
        self.assertFalse(self.idle.expired())  # a reloaded page has 30 s to come back
        self.idle.heartbeat('a2')
        self.clock.now += 29
        self.assertFalse(self.idle.expired())
        self.clock.now += 2
        self.assertTrue(self.idle.expired())

    def test_bye_does_not_stop_the_server_while_another_tab_is_alive(self):
        self.idle.heartbeat('a')
        self.idle.heartbeat('b')
        self.idle.bye('a')
        self.clock.now += 31
        self.idle.heartbeat('b')
        self.assertFalse(self.idle.expired())

    def test_bye_without_a_tab_id_ends_every_tab_after_the_grace(self):
        self.idle.heartbeat('a')
        self.idle.heartbeat('b')
        self.idle.bye()
        self.clock.now += 30.1
        self.assertTrue(self.idle.expired())

    def test_an_open_stream_counts_as_a_live_tab_only_after_a_first_heartbeat(self):
        self.idle.touch('stream')
        self.assertFalse(self.idle.seen)
        self.idle.heartbeat('a')
        self.clock.now += 25
        self.idle.touch('stream')
        self.clock.now += 25
        self.assertFalse(self.idle.expired())

    def test_watch_calls_on_idle_once_with_an_injected_clock(self):
        calls = []
        self.idle.heartbeat('a')

        class Ticker:  # every wait() is one 2 s poll; here it moves the injected clock by 20 s instead of sleeping
            n = 0

            def wait(ticker, interval=None):
                ticker.n += 1
                self.clock.now += 20
                return ticker.n > 20

        ticker = Ticker()
        lifecycle.watch(self.idle, ticker, lambda: calls.append(self.clock.now))
        self.assertEqual((len(calls), ticker.n), (1, 2))  # 40 s after the heartbeat, not before

    def test_watch_ends_when_the_server_stops_first(self):
        calls, stop = [], threading.Event()
        stop.set()
        self.idle.heartbeat('a')
        lifecycle.watch(self.idle, stop, lambda: calls.append(1))
        self.assertEqual(calls, [])

    def test_shutdown_cancels_tasks_stops_the_worker_kills_the_tree_then_exits(self):
        order = []

        class Store:
            def active_tasks(self_):
                order.append('tasks')
                return []

        class Worker:
            def join(self_, timeout=None):
                order.append('join')

        stop = threading.Event()
        with patch('dubflow.pipeline.kill_children', side_effect=lambda: order.append('children') or 0):
            lifecycle.shutdown_server(Store(), Path('.'), stop, Worker(), kill_tree=lambda pid: order.append(('tree', pid)), exit_process=lambda code: order.append(('exit', code)))
        self.assertTrue(stop.is_set())
        self.assertEqual(order, ['tasks', 'children', 'join', 'children', ('tree', os.getpid()), ('exit', 0)])


class IdleShutdownWiringTests(unittest.TestCase):
    def test_the_watcher_starts_only_when_enabled_and_never_without_a_worker(self):
        saved = tempfile.tempdir  # create_app with a worker points tempfile at the data dir
        self.addCleanup(setattr, tempfile, 'tempdir', saved)
        for env, worker, expect in (({}, True, True), ({'DUBFLOW_NO_IDLE_SHUTDOWN': '1'}, True, False), ({}, False, False)):
            started = []
            with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=False):
                os.environ.pop('DUBFLOW_NO_IDLE_SHUTDOWN', None)
                os.environ.update(env, DUBFLOW_EMBEDDED_WORKER='0')
                with patch('dubflow.app.lifecycle.watch', side_effect=lambda *a, **k: started.append(1)):
                    app = create_app(Settings(data_dir=Path(tmp), system_voices=Path(tmp) / 's'), start_worker=worker)
                    with TestClient(app):
                        pass
                    tempfile.tempdir = saved
                    self.assertEqual(bool(started), expect, (env, worker))


if __name__ == '__main__':
    unittest.main()
