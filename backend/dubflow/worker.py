"""One persistent local worker, with optional RQ transport for deployments."""
import argparse
import os
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from pathlib import Path

from .messages import translate_message
from .config import Settings
from .media import atomic_json, read_json
from .store import Store


class JobCancelled(Exception):
    pass


@contextmanager
def worker_lock(settings):
    path = settings.data_dir / 'worker.lock'
    lock = path.open('a+b')
    acquired = False
    try:
        lock.seek(0)
        if os.name == 'nt':
            import msvcrt
            if path.stat().st_size == 0:
                lock.write(b'0')
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        acquired = True
        yield True
    except (OSError, BlockingIOError):
        if acquired:
            raise
        yield False
    finally:
        if acquired:
            if os.name == 'nt':
                import msvcrt
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def run_task(task, settings, store):
    from . import pipeline
    from .preferences import effective_settings
    from .publisher import publish
    settings = effective_settings(store, settings)
    jid = task['job_id']
    job = store.get_job(jid)
    collection = store.get_record('collection',job.get('collection_id')) if job and job.get('collection_id') else None
    settings.translation_context = (collection or {}).get('terminology','')
    if job:job['review_terms']=settings.translation_context
    folder = settings.jobs_dir / jid
    if not job or job['status'] == 'cancelled' or (folder / 'cancel.request').exists():
        store.finish_task(task['id'], 'cancelled')
        return
    atomic_json(folder / 'job.json', job)
    if not store.begin_processing(jid):
        store.finish_task(task['id'], 'cancelled')
        return

    def update_active(**values):
        if (folder / 'cancel.request').exists() or not store.update_active_job(jid,**values):
            raise JobCancelled('Đã dừng tác vụ.')

    def emit(stage, message, progress):
        if store.get_job(jid)['status'] == 'cancelled':
            raise JobCancelled('Đã dừng tác vụ.')
        update_active(status='processing', stage=stage, progress=max(0, min(99, int(progress))))
        store.event(jid, stage, message, progress)

    try:
        current=read_json(folder/'cues.json',[])
        ordered=sorted(current,key=lambda c:(c['start'],c['end']))
        if current!=ordered:
            # Normalize legacy ASR order without deleting or renumbering source IDs.
            history=folder/'cue-order-history';history.mkdir(exist_ok=True)
            import uuid
            atomic_json(history/(uuid.uuid4().hex+'.json'),current)
            atomic_json(folder/'cues.json',ordered)
        if task['action'] in ('analyze','translate'):
            result = (pipeline.translate_only if task['action']=='translate' else pipeline.prepare)(folder, settings, emit) or {}
            cues = read_json(folder / 'cues.json')
            from .review import quality_report
            report=quality_report(folder,job)
            atomic_json(folder/'quality-report.json',report)
            summaries=list(dict.fromkeys(f['message'] for f in report['flags']))
            speaker_result=read_json(folder/'speaker-candidates.json',{})
            if speaker_result:
                summaries.append('Chưa tự chia giọng đáng tin cậy; giữ nhãn chưa rõ thay vì tạo nhầm nhân vật.' if speaker_result.get('status') in ('unreliable','unavailable') else 'Phân nhóm giọng hiện là ứng viên từ đoạn ASR, chưa phải nhận diện nhân vật.')
            auto=read_json(folder/'auto-context.json',{})
            if auto.get('status')=='automatic_candidate':summaries.append('Ngữ cảnh và xưng hô do máy suy luận; sửa trực tiếp ở Lời dịch nếu chưa đúng.')
            if auto.get('status')=='failed':summaries.append('Bước suy luận ngữ cảnh tự động chưa đạt; bản dịch vẫn cần xem lại.')
            update_active(status='awaiting_review', stage='awaiting_review', progress=45, cue_count=len(cues),
                             warnings=[translate_message(w) for w in result.get('warnings', job.get('warnings', []))]+summaries)
            store.event(jid, 'awaiting_review', 'Nội dung đã sẵn sàng để duyệt.', 45)
        else:
            from .review import require_export
            try:
                require_export(folder,job,job.get('export_kind','draft'))
            except ValueError as exc:
                raise pipeline.NeedsReview(str(exc)) from None
            if not (folder / 'regions.json').exists():
                pipeline.prepare(folder, settings, emit)
            if job['mode'] != 'vietsub':
                if job['mode'] == 'dub' and (not (folder / 'vocals.wav').exists() or not (folder / 'background.wav').exists()):
                    pipeline.prepare(folder, settings, emit)
                pipeline.synthesize(folder, settings, emit)
            result = pipeline.render(folder, settings, emit) or {}
            if not (folder / 'output.mp4').is_file():
                raise RuntimeError('Worker chưa tạo được file output.mp4.')
            if store.get_job(jid)['status'] == 'cancelled' or (folder / 'cancel.request').exists():
                raise JobCancelled()
            publish(store, settings, jid, rendering=True, render_values={k:getattr(settings,k) for k in ('resolution','blur_original','original_gain')})
            cues = read_json(folder / 'cues.json')
            passed = sum(c.get('asr_edits') == 0 for c in cues) if job['mode'] != 'vietsub' else 0
            update_active(status='done', stage='done', progress=100, error=None, cue_count=len(cues), ready_count=passed,
                             warnings=[translate_message(w) for w in result.get('warnings', job.get('warnings', []))])
            if settings.open_after_export:
                from .native import open_folder
                try:
                    open_folder(store.get_job(jid)['export_dir'])
                except ValueError as exc:
                    store.update_job(jid,warnings=store.get_job(jid).get('warnings',[])+[str(exc)])
            store.event(jid, 'done', 'Đã xuất bản nháp, cần duyệt nội dung và chất lượng.' if job.get('export_kind','draft')=='draft' else 'Đã xuất bản được duyệt. Hãy kiểm tra video cuối.', 100)
        store.finish_task(task['id'])
    except (JobCancelled, KeyboardInterrupt):
        store.update_job(jid, status='cancelled', stage='cancelled', error=None)
        store.finish_task(task['id'], 'cancelled')
    except Exception as exc:
        # Cancellation from a subprocess is represented by the same persisted flag.
        if (folder / 'cancel.request').exists() or store.get_job(jid)['status'] == 'cancelled':
            store.update_job(jid, status='cancelled', stage='cancelled', error=None)
            store.finish_task(task['id'], 'cancelled')
            return
        review = isinstance(exc, pipeline.NeedsReview)
        message = translate_message(str(exc))
        if message == str(exc) and not any(ord(c) > 127 for c in message):
            message = 'Không thể hoàn tất tác vụ. Hãy kiểm tra last-error.log, cấu hình và tệp nguồn rồi thử lại.'
        (folder / 'last-error.log').write_text(traceback.format_exc(), encoding='utf-8')
        cues = read_json(folder / 'cues.json')
        store.update_job(jid, status='awaiting_review' if review else 'failed', stage='awaiting_review' if review else 'failed',
                         error=message, cue_count=len(cues), progress=45 if review else store.get_job(jid)['progress'])
        store.event(jid, 'awaiting_review' if review else 'failed', message, 45 if review else 0)
        store.finish_task(task['id'], 'review' if review else 'failed')


def worker_loop(settings, stop=None):
    stop = stop or threading.Event()
    settings.ensure()
    store = Store(settings.db_path)
    with worker_lock(settings) as locked:
        if not locked:
            return
        store.recover()
        while not stop.is_set():
            atomic_json(settings.data_dir / 'worker-heartbeat.json', dict(pid=os.getpid(), time=time.time(), queue=settings.queue_backend))
            task = store.claim_next()
            if task:
                run_task(task, settings, store)
            else:
                stop.wait(1)


def run_rq_task(data_dir, task_id):
    settings = Settings(data_dir=Path(data_dir)).ensure()
    store = Store(settings.db_path)
    with worker_lock(settings) as locked:
        if not locked:
            raise RuntimeError('Worker khác đang dùng GPU.')
        task = store.claim_task(task_id)
        if task:
            run_task(task, settings, store)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rq', action='store_true')
    args = parser.parse_args()
    settings = Settings().ensure()
    if args.rq:
        if not settings.redis_url:
            raise SystemExit('Cần DUBFLOW_REDIS_URL để chạy RQ.')
        from redis import Redis
        from rq import Queue, SimpleWorker
        connection = Redis.from_url(settings.redis_url)
        SimpleWorker([Queue('dubflow', connection=connection)], connection=connection).work()
    else:
        worker_loop(settings)


if __name__ == '__main__':
    main()
