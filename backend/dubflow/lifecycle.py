"""Task cancellation for the whole server and idle shutdown (nothing keeps running once the web tabs are gone)."""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time

log = logging.getLogger(__name__)


class IdleMonitor:
    """Tracks the open web tabs through their heartbeats.

    A tab is alive for `timeout` s after its last heartbeat. A `bye` (the tab is closing) leaves it `grace` s from the
    bye (a reload or a quick navigation sends a heartbeat again within that time; the last tab really leaving does not).
    The server is idle once at least one heartbeat was ever seen and every tab has expired; with none ever seen
    (API scripts, tests) it never is."""

    def __init__(self, timeout=30.0, grace=30.0, clock=time.monotonic):
        self.timeout, self.grace, self.clock = float(timeout), float(grace), clock
        self.tabs = {}  # tab id -> deadline
        self.seen = False
        self._lock = threading.Lock()

    def heartbeat(self, tab=''):
        with self._lock:
            self.seen = True
            self.tabs[str(tab or '')] = self.clock() + self.timeout

    def touch(self, tab='stream'):
        """A sign of life that is not a heartbeat (an open event stream); counts only after a first heartbeat."""
        with self._lock:
            if self.seen:
                self.tabs[str(tab or '')] = self.clock() + self.timeout

    def bye(self, tab=''):
        with self._lock:
            if not self.seen:
                return
            now = self.clock()
            for key in ([str(tab)] if tab else list(self.tabs)):
                self.tabs[key] = now + self.grace

    def expired(self):
        with self._lock:
            if not self.seen:
                return False
            now = self.clock()
            self.tabs = {k: d for k, d in self.tabs.items() if d > now}
            return not self.tabs


def stop_all_tasks(store, jobs_dir):
    """Cancel every queued and running task (the same mechanism as the per-video cancel: a cancel.request file the
    worker polls and the job marked cancelled) and kill the engine processes at once. -> counts."""
    tasks = store.active_tasks()
    job_ids = list(dict.fromkeys(t['job_id'] for t in tasks))
    for jid in job_ids:
        folder = jobs_dir / jid
        if folder.is_dir():
            (folder / 'cancel.request').touch()
        try:
            store.cancel(jid)
            store.event(jid, 'cancelled', 'Đã dừng tất cả tác vụ.', 0)
        except KeyError:
            pass
    from . import pipeline
    killed = pipeline.kill_children()
    return dict(cancelled=len(tasks), queued=sum(t['state'] == 'pending' for t in tasks),
                running=sum(t['state'] == 'running' for t in tasks), jobs=len(job_ids), processes_killed=killed)


def kill_process_tree(pid, run=subprocess.run):
    """Kill pid and every process it started."""
    if os.name == 'nt':
        run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True)
    else:
        import signal
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except OSError:
            os.kill(pid, signal.SIGKILL)


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
    pipeline.kill_children()
    try:
        kill_tree(os.getpid())
    finally:
        exit_process(0)


def watch(idle, stop, on_idle, interval=2.0):
    """Thread body: call on_idle() once when the monitor says idle; returns when `stop` is set or after on_idle."""
    while not stop.wait(interval):
        if idle.expired():
            log.warning('No web tab for %.0f s: stopping DubFlow.', idle.timeout)
            on_idle()
            return
