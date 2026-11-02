"""Task cancellation for the whole server and idle shutdown (nothing keeps running once the web tabs are gone).

Idle-shutdown policy (what the user asked for: nothing is left running after the web is closed, but a task is never killed
just because a browser throttled a hidden tab):

* Tabs are tracked by id (heartbeat body `{"tab": id}`; a client without an id is the single tab "").
* EXPLICIT LEAVE. A tab that sent `bye` and did not send a heartbeat again within `grace` (30 s; a reload or a quick
  navigation comes straight back) is gone. When every known tab is gone, the server stops: running and queued tasks are
  cancelled, the engine processes are killed and the process exits. This is the user's intent, tasks or not.
* SILENCE. A tab that only stopped sending heartbeats (a throttled / frozen / sleeping hidden tab) is NOT gone. The server
  stops on silence only when every tab has been silent for `silence` (10 min) AND no task is running or queued; as long as
  there is work, heartbeat silence alone never cancels or kills anything.
* An open event stream (SSE) is a sign of life of its own: while one is open the server never stops by silence, and a
  stream that is still open after a `bye` cancels the pending shutdown (the page is evidently still there).
* Nothing happens before the first heartbeat ever seen (API scripts, tests), and DUBFLOW_NO_IDLE_SHUTDOWN=1 disables the
  watcher altogether.
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time

log = logging.getLogger(__name__)

STREAM_TTL = 5.0  # an event stream touches the monitor every second; this long without a touch means it is closed


class IdleMonitor:
    """Tracks the open web tabs (see the module docstring for the policy)."""

    def __init__(self, timeout=30.0, grace=30.0, silence=600.0, clock=time.monotonic):
        self.timeout = float(timeout)  # kept for the heartbeat response: how often a live tab is expected to report
        self.grace, self.silence, self.clock = float(grace), float(silence), clock
        self.tabs = {}  # tab id -> dict(last=time of the last sign of life, bye=time of its `bye` or None)
        self.streams = {}  # stream id -> time of the last touch
        self.seen = False
        self._lock = threading.Lock()

    def heartbeat(self, tab=''):
        with self._lock:
            self.seen = True
            self.tabs[str(tab or '')] = dict(last=self.clock(), bye=None)

    def touch(self, stream='stream'):
        """An open event stream is alive (counts only after a first heartbeat). Call `release` when it closes."""
        with self._lock:
            if self.seen:
                self.streams[str(stream or '')] = self.clock()

    def release(self, stream='stream'):
        with self._lock:
            self.streams.pop(str(stream or ''), None)

    def bye(self, tab=''):
        with self._lock:
            if not self.seen:
                return
            now = self.clock()
            for key in ([str(tab)] if tab else list(self.tabs)):
                entry = self.tabs.setdefault(key, dict(last=now, bye=None))
                entry['bye'] = now

    def open_streams(self):
        now = self.clock()
        return [k for k, t in self.streams.items() if now - t < STREAM_TTL]

    def verdict(self, busy=False):
        """None while the server should stay up, else why it should stop: 'bye' (every tab left on purpose) or
        'silence' (every tab silent for `silence` s and no task running or queued)."""
        with self._lock:
            if not self.seen:
                return None
            now = self.clock()
            if self.open_streams():
                return None
            leaving = [k for k, e in self.tabs.items() if e['bye'] is not None]
            for key in leaving:  # a stream or heartbeat that arrived after the bye has already reset it; the rest are gone
                if now - self.tabs[key]['bye'] >= self.grace:
                    del self.tabs[key]
            if not self.tabs:
                return 'bye'
            if any(e['bye'] is not None for e in self.tabs.values()):
                return None  # still inside the grace period of a leaving tab (others may be alive)
            if all(now - e['last'] >= self.silence for e in self.tabs.values()) and not busy:
                return 'silence'
            return None

    def expired(self, busy=False):
        return self.verdict(busy) is not None


def stop_all_tasks(store, jobs_dir):
    """Cancel every queued and running task (the same mechanism as the per-video cancel: a cancel.request file the
    worker polls and the job marked cancelled) and kill the engine processes at once. -> counts, including how many
    process trees could NOT be ended (`processes_failed`). A job whose task is running stays "stopping" (activity message
    and `stopping` in the API) until its worker confirms."""
    tasks = store.active_tasks()
    job_ids = list(dict.fromkeys(t['job_id'] for t in tasks))
    running = {t['job_id'] for t in tasks if t['state'] == 'running'}
    for jid in job_ids:
        folder = jobs_dir / jid
        if folder.is_dir():
            (folder / 'cancel.request').touch()
        try:
            store.cancel(jid)
            store.event(jid, 'cancelled', 'Đã dừng tất cả tác vụ.', 0)
            if jid in running:
                store.mark_stopping(jid)
        except KeyError:
            pass
    from . import pipeline
    report = pipeline.kill_children_report()
    return dict(cancelled=len(tasks), queued=sum(t['state'] == 'pending' for t in tasks),
                running=sum(t['state'] == 'running' for t in tasks), jobs=len(job_ids),
                processes_killed=report['killed'], processes_failed=report['failed'])


def kill_process_tree(pid, run=subprocess.run):
    """Kill pid and every process it started; -> True when the OS accepted it (failures are logged)."""
    if os.name == 'nt':
        done = run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True)
        if done.returncode:
            log.warning('taskkill pid %s trả mã %s', pid, done.returncode)
        return not done.returncode
    import signal
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except OSError:
        os.kill(pid, signal.SIGKILL)
    return True


def shutdown_server(store, jobs_dir, stop, worker=None, wait=6.0, kill_tree=kill_process_tree, exit_process=os._exit):
    """Cancel everything, stop the worker and end this process with all its children (uvicorn included)."""
    try:
        stop_all_tasks(store, jobs_dir)
    except Exception:  # noqa: BLE001 - shutting down regardless
        log.exception('stop_all_tasks failed during idle shutdown')
    stop.set()
    if worker is not None:
        worker.join(timeout=wait)
    from . import pipeline
    try:
        report = pipeline.kill_children_report()
        if report['failed']:
            log.error('Còn %d cây tiến trình chưa dừng được khi tắt máy chủ (pid %s).', report['failed'], report['failed_pids'])
    except Exception:  # noqa: BLE001
        log.exception('kill_children failed during idle shutdown')
    try:
        kill_tree(os.getpid())
    finally:
        exit_process(0)


def watch(idle, stop, on_idle, interval=2.0, busy=lambda: False):
    """Thread body: call on_idle() once when the monitor says the server should stop; returns when `stop` is set or after
    on_idle. `busy()` tells whether a task is running or queued (silence alone never stops a busy server); when it cannot
    be answered the server is treated as busy."""
    while not stop.wait(interval):
        try:
            working = bool(busy())
        except Exception as exc:  # noqa: BLE001
            log.warning('Không đọc được hàng đợi (%s); coi như đang bận.', exc)
            working = True
        reason = idle.verdict(working)
        if reason:
            if reason == 'bye':
                log.warning('Tab cuối cùng đã đóng (bye + %.0f s): dừng DubFlow.', idle.grace)
            else:
                log.warning('Không có tab nào báo hiệu trong %.0f s và không có tác vụ: dừng DubFlow.', idle.silence)
            on_idle()
            return
