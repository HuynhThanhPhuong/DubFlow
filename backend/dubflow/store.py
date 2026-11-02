"""SQLite persistence and a transactional, single-consumer local job queue."""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


BUSY_STATUSES = ('queued', 'processing', 'separating', 'transcribing', 'synthesizing', 'rendering')
ACTIVITY_LIMIT = 20


def push_activity(job, message):
    """Return the job's recent worker messages with `message` appended (ring buffer, newest last).
    A message identical to the previous one is not repeated (stages re-emit the same text every tick)."""
    rows = [r for r in ((job or {}).get('activity') or []) if isinstance(r, dict)]
    text = str(message or '').strip()[:240]
    if text and (not rows or rows[-1].get('msg') != text):
        rows.append(dict(t=now(), msg=text))
    return rows[-ACTIVITY_LIMIT:]


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS studio_records (kind TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(kind,id));
                CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, stage TEXT, message TEXT, progress INTEGER, created_at TEXT);
                CREATE INDEX IF NOT EXISTS events_job ON events(job_id,id);
                CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, action TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending', created_at TEXT, updated_at TEXT);
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_job ON tasks(job_id) WHERE state IN ('pending','running');
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(str(self.path), timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def create_job(self, values):
        job = dict(id=uuid.uuid4().hex, status='created', stage='created', progress=0, error=None,
                   duration=0, width=0, height=0, voice_id=None, source_url='', warnings=[],
                   cue_count=0, ready_count=0, collection_id=None, episode='', exported_paths=[], export_dir=None, created_at=now(), updated_at=now())
        job.update(values)
        with self.connect() as db:
            db.execute('INSERT INTO jobs VALUES (?,?)', (job['id'], json.dumps(job, ensure_ascii=False)))
        return job

    def get_job(self, job_id):
        with self.connect() as db:
            row = db.execute('SELECT body FROM jobs WHERE id=?', (job_id,)).fetchone()
        return json.loads(row['body']) if row else None

    def list_jobs(self):
        with self.connect() as db:
            rows = db.execute('SELECT body FROM jobs ORDER BY rowid DESC').fetchall()
        return [json.loads(r['body']) for r in rows]

    def update_job(self, job_id, **values):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT body FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not row:
                raise KeyError(job_id)
            job = json.loads(row['body'])
            job.update(values, updated_at=now())
            db.execute('UPDATE jobs SET body=? WHERE id=?', (json.dumps(job, ensure_ascii=False), job_id))
        return job

    def begin_delete(self, job_id):
        """Atomically (one BEGIN IMMEDIATE transaction) check that the job is idle, has no pending/running task and mark
        it `deleting`. From then on enqueue/claim/begin_processing refuse it, so nothing can start between the check and the
        removal. KeyError: no such job. ValueError: busy, or already being deleted (Vietnamese message)."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT body FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not row:
                raise KeyError(job_id)
            job = json.loads(row['body'])
            if job.get('deleting'):
                raise ValueError('Dự án đang được xóa.')
            busy = job.get('status') in BUSY_STATUSES or db.execute(
                "SELECT 1 FROM tasks WHERE job_id=? AND state IN ('pending','running') LIMIT 1", (job_id,)).fetchone()
            if busy:
                raise ValueError('Video đang được xử lý. Hãy dừng tác vụ trước khi xóa.')
            job.update(deleting=True, updated_at=now())
            db.execute('UPDATE jobs SET body=? WHERE id=?', (json.dumps(job, ensure_ascii=False), job_id))
        return job

    def abort_delete(self, job_id):
        """The deletion could not be carried out: the job is a normal, visible job again."""
        try:
            job = self.get_job(job_id)
            if job and job.get('deleting'):
                self.update_job(job_id, deleting=False)
        except KeyError:
            pass

    def remove_job(self, job_id):
        with self.connect() as db:
            db.execute('DELETE FROM events WHERE job_id=?', (job_id,))
            db.execute('DELETE FROM tasks WHERE job_id=?', (job_id,))
            db.execute('DELETE FROM jobs WHERE id=?', (job_id,))

    def event(self, job_id, stage, message, progress):
        with self.connect() as db:
            db.execute('INSERT INTO events(job_id,stage,message,progress,created_at) VALUES (?,?,?,?,?)',
                       (job_id, stage, message, int(progress), now()))

    def events(self, job_id, after=0):
        with self.connect() as db:
            rows = db.execute('SELECT * FROM events WHERE job_id=? AND id>? ORDER BY id', (job_id, after)).fetchall()
        return [dict(r) for r in rows]

    def enqueue(self, job_id, action, before_commit=None):
        if action not in ('analyze', 'render', 'translate', 'detect_logos'):
            raise ValueError('Tác vụ không hợp lệ.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT body FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not row:
                raise KeyError(job_id)
            if json.loads(row['body']).get('deleting'):
                raise ValueError('Dự án đang được xóa.')
            try:
                cursor = db.execute('INSERT INTO tasks(job_id,action,state,created_at,updated_at) VALUES (?,?,?,?,?)',
                                    (job_id, action, 'pending', now(), now()))
            except sqlite3.IntegrityError:
                raise ValueError('Dự án đang có tác vụ trong hàng đợi.') from None
            task_id = cursor.lastrowid
            job = json.loads(row['body'])
            job.update(status='queued', stage='queued', error=None, action=action, updated_at=now())
            db.execute('UPDATE jobs SET body=? WHERE id=?', (json.dumps(job, ensure_ascii=False), job_id))
            if before_commit:  # runs only after the insert succeeded; an exception rolls the task back
                before_commit()
        return task_id

    def active_tasks(self):
        with self.connect() as db:
            rows = db.execute("SELECT job_id,action,state FROM tasks WHERE state IN ('pending','running')").fetchall()
        return [dict(r) for r in rows]

    def queue_info(self, job_id):
        """Place of the job's pending task in the queue (1 = next), and whether another task is running now."""
        with self.connect() as db:
            mine = db.execute("SELECT id FROM tasks WHERE job_id=? AND state='pending' ORDER BY id LIMIT 1", (job_id,)).fetchone()
            if not mine:
                return None
            ahead = db.execute("SELECT COUNT(*) FROM tasks WHERE state='pending' AND id<?", (mine['id'],)).fetchone()[0]
            running = db.execute("SELECT 1 FROM tasks WHERE state='running' LIMIT 1").fetchone() is not None
        return dict(position=ahead + 1, running_ahead=running)

    def _claimable(self, db, row):
        """A pending task whose job is gone or being deleted is cancelled instead of started."""
        record = db.execute('SELECT body FROM jobs WHERE id=?', (row['job_id'],)).fetchone()
        if record and not json.loads(record['body']).get('deleting'):
            return True
        db.execute("UPDATE tasks SET state='cancelled',updated_at=? WHERE id=?", (now(), row['id']))
        return False

    def claim_next(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM tasks WHERE state='running' LIMIT 1").fetchone():
                return None
            for row in db.execute("SELECT * FROM tasks WHERE state='pending' ORDER BY id").fetchall():
                if self._claimable(db, row):
                    db.execute("UPDATE tasks SET state='running',updated_at=? WHERE id=?", (now(), row['id']))
                    return dict(row)
        return None

    def claim_task(self, task_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM tasks WHERE state='running'").fetchone():
                return None
            row = db.execute("SELECT * FROM tasks WHERE id=? AND state='pending'", (task_id,)).fetchone()
            if row and self._claimable(db, row):
                db.execute("UPDATE tasks SET state='running',updated_at=? WHERE id=?", (now(), task_id))
                return dict(row)
        return None

    def finish_task(self, task_id, state='done'):
        with self.connect() as db:
            db.execute('UPDATE tasks SET state=?,updated_at=? WHERE id=?', (state, now(), task_id))

    def begin_processing(self, job_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT body FROM jobs WHERE id=?', (job_id,)).fetchone()
            job = json.loads(row['body']) if row else None
            if not job or job['status'] == 'cancelled' or job.get('deleting'):
                return False
            job.update(status='processing', stage='processing', progress=0, error=None, stage_step=None, stage_started_at=None, stage_detail=None,
                       activity=push_activity(job, 'Máy xử lý đã nhận tác vụ.'), updated_at=now())
            db.execute('UPDATE jobs SET body=? WHERE id=?', (json.dumps(job, ensure_ascii=False), job_id))
        return True

    def cancel(self, job_id):
        with self.connect() as db:
            # A running subprocess still owns the GPU until its worker confirms exit.
            db.execute("UPDATE tasks SET state='cancelled',updated_at=? WHERE job_id=? AND state='pending'", (now(), job_id))
        return self.update_job(job_id, status='cancelled', stage='cancelled', error=None)

    def running_job_ids(self):
        """Jobs whose task is still running (a cancelled one among them is not stopped until its worker confirms)."""
        with self.connect() as db:
            return {r['job_id'] for r in db.execute("SELECT job_id FROM tasks WHERE state='running'").fetchall()}

    def mark_stopping(self, job_id):
        """Tell the user the stop was requested but the running task has not ended yet."""
        try:
            job = self.get_job(job_id)
            if job:
                self.update_job(job_id, activity=push_activity(job, 'Đang dừng… chờ tác vụ đang chạy kết thúc.'))
        except KeyError:
            pass

    def recover(self):
        """Called once by the single worker after acquiring its process lock."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            rows = db.execute("SELECT id,job_id FROM tasks WHERE state='running'").fetchall()
            for row in rows:
                record = db.execute('SELECT body FROM jobs WHERE id=?', (row['job_id'],)).fetchone()
                job = json.loads(record['body']) if record else None
                cancelled = not job or job['status'] == 'cancelled'
                db.execute('UPDATE tasks SET state=?,updated_at=? WHERE id=?', ('cancelled' if cancelled else 'pending', now(), row['id']))
                if not cancelled:
                    job.update(status='queued', stage='queued', error=None, updated_at=now())
                    db.execute('UPDATE jobs SET body=? WHERE id=?', (json.dumps(job, ensure_ascii=False), row['job_id']))

    def get_record(self, kind, record_id):
        with self.connect() as db:
            row = db.execute('SELECT body FROM studio_records WHERE kind=? AND id=?', (kind,record_id)).fetchone()
        return json.loads(row['body']) if row else None

    def list_records(self, kind):
        with self.connect() as db:
            rows=db.execute('SELECT body FROM studio_records WHERE kind=? ORDER BY rowid', (kind,)).fetchall()
        return [json.loads(r['body']) for r in rows]

    def put_record(self, kind, record_id, value):
        with self.connect() as db:
            db.execute('INSERT INTO studio_records VALUES (?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body', (kind, record_id, json.dumps(value, ensure_ascii=False)))
        return value

    def delete_record(self, kind, record_id):
        with self.connect() as db:
            db.execute('DELETE FROM studio_records WHERE kind=? AND id=?', (kind, record_id))

    def unlink_collection(self, collection_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for row in db.execute('SELECT id,body FROM jobs').fetchall():
                job=json.loads(row['body'])
                if job.get('collection_id')==collection_id:
                    job.update(collection_id=None, updated_at=now())
                    db.execute('UPDATE jobs SET body=? WHERE id=?',(json.dumps(job,ensure_ascii=False),row['id']))
            db.execute('DELETE FROM studio_records WHERE kind=? AND id=?',('collection',collection_id))

    def update_active_job(self, job_id, **values):
        """Worker updates must never resurrect an acknowledged cancellation."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT body FROM jobs WHERE id=?',(job_id,)).fetchone()
            job=json.loads(row['body']) if row else None
            if not job or job['status']=='cancelled':
                return None
            job.update(values,updated_at=now())
            db.execute('UPDATE jobs SET body=? WHERE id=?',(json.dumps(job,ensure_ascii=False),job_id))
        return job
