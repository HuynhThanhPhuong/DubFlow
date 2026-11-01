"""SQLite persistence and a transactional, single-consumer local job queue."""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


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

    def claim_next(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM tasks WHERE state='running' LIMIT 1").fetchone():
                return None
            row = db.execute("SELECT * FROM tasks WHERE state='pending' ORDER BY id LIMIT 1").fetchone()
            if not row:
                return None
            db.execute("UPDATE tasks SET state='running',updated_at=? WHERE id=?", (now(), row['id']))
            return dict(row)

    def claim_task(self, task_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM tasks WHERE state='running'").fetchone():
                return None
            row = db.execute("SELECT * FROM tasks WHERE id=? AND state='pending'", (task_id,)).fetchone()
            if row:
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
            if not job or job['status'] == 'cancelled':
                return False
            job.update(status='processing', stage='processing', progress=0, error=None, updated_at=now())
            db.execute('UPDATE jobs SET body=? WHERE id=?', (json.dumps(job, ensure_ascii=False), job_id))
        return True

    def cancel(self, job_id):
        with self.connect() as db:
            # A running subprocess still owns the GPU until its worker confirms exit.
            db.execute("UPDATE tasks SET state='cancelled',updated_at=? WHERE job_id=? AND state='pending'", (now(), job_id))
        return self.update_job(job_id, status='cancelled', stage='cancelled', error=None)

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
