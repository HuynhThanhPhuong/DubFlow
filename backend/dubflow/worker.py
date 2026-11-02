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
from .store import Store, push_activity


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
    terminology = (collection or {}).get('terminology','')
    if job:
        job['review_terms']=terminology
        job['vietsub_cps']=settings.vietsub_cps
    folder = settings.jobs_dir / jid
    if not job or job['status'] == 'cancelled' or (folder / 'cancel.request').exists():
        store.finish_task(task['id'], 'cancelled')
        return
    if not folder.is_dir():
        store.finish_task(task['id'], 'cancelled')
        return
    atomic_json(folder / 'job.json', job)
    if not store.begin_processing(jid):
        store.finish_task(task['id'], 'cancelled')
        return

    def update_active(**values):
        if (folder / 'cancel.request').exists() or not store.update_active_job(jid,**values):
            raise JobCancelled('Đã dừng tác vụ.')

    from . import timing
    clock = timing.StageClock(settings.data_dir, store, jid, job, task['action'])
    idle = dict(stage_step=None, stage_started_at=None, stage_detail=None)

    def emit(stage, message, progress, detail=None):
        current = store.get_job(jid)
        if not current or current['status'] == 'cancelled':
            raise JobCancelled('Đã dừng tác vụ.')
        extra = clock.enter(stage)
        if detail is not None:
            extra['stage_detail'] = detail
        update_active(status='processing', stage=stage, progress=max(0, min(99, int(progress))), activity=push_activity(current, message), **extra)
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
            if task['action']=='translate':
                from . import translate_run
                result = translate_run.run_job(folder, settings, job, emit, terminology, check_cancel=lambda: update_active()) or {}
            else:
                result = pipeline.prepare(folder, settings, emit) or {}
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
            clock.finish()
            update_active(status='awaiting_review', stage='awaiting_review', progress=45, cue_count=len(cues), **idle,
                             activity=push_activity(store.get_job(jid), 'Xong; nội dung sẵn sàng để duyệt.'),
                             warnings=[translate_message(w) for w in result.get('warnings', job.get('warnings', []))]+summaries)
            store.event(jid, 'awaiting_review', 'Nội dung đã sẵn sàng để duyệt.', 45)
        elif task['action'] == 'detect_logos':
            # the job goes back to where it was (a finished job keeps its output); detection never fails the job
            request = folder / 'detect-logos-request.json'
            before = read_json(request, {}) or {}
            restore = dict(status=before.get('status') or 'awaiting_review', stage=before.get('stage') or 'awaiting_review',
                           progress=before.get('progress', 45), error=before.get('error'))
            try:
                _, _, source, meta = pipeline.context(folder, settings)
                pipeline.detect_logos(folder, source, meta, settings, emit, force=True)
                message = 'Đã tìm logo và chữ cố định; hãy xem các khung gợi ý.'
                update_active(**restore)
            except (JobCancelled, KeyboardInterrupt, pipeline.Cancelled):
                raise
            except Exception as exc:  # noqa: BLE001 - warn like translate does, keep the job's status and output
                if not isinstance(exc, pipeline.NeedsReview):
                    (folder / 'last-error.log').write_text(traceback.format_exc(), encoding='utf-8')
                message = translate_message(str(exc))
                if not isinstance(exc, pipeline.NeedsReview) and message == str(exc) and not any(ord(c) > 127 for c in message):
                    message = 'Không tìm được logo và chữ cố định. Kiểm tra detect-logos trong logs và thử lại.'
                update_active(**restore, warnings=list(store.get_job(jid).get('warnings', [])) + [message])
            finally:
                request.unlink(missing_ok=True)
            store.event(jid, restore['stage'], message, restore['progress'])
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
            if (store.get_job(jid) or {}).get('status', 'cancelled') == 'cancelled' or (folder / 'cancel.request').exists():
                raise JobCancelled()
            publish(store, settings, jid, rendering=True, render_values={k:getattr(settings,k) for k in ('resolution','blur_original','original_gain')})
            cues = read_json(folder / 'cues.json')
            passed = sum(c.get('asr_edits') == 0 for c in cues) if job['mode'] != 'vietsub' else 0
            clock.finish()
            update_active(status='done', stage='done', progress=100, error=None, cue_count=len(cues), ready_count=passed, **idle,
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
        if store.get_job(jid):
            store.update_job(jid, status='cancelled', stage='cancelled', error=None, **idle)
        store.finish_task(task['id'], 'cancelled')
    except Exception as exc:
        # Cancellation from a subprocess is represented by the same persisted flag.
        latest = store.get_job(jid)
        if not latest or (folder / 'cancel.request').exists() or latest['status'] == 'cancelled':
            if latest:
                store.update_job(jid, status='cancelled', stage='cancelled', error=None)
            store.finish_task(task['id'], 'cancelled')
            return
        from .translate_run import TranslateFailed
        review = isinstance(exc, (pipeline.NeedsReview, TranslateFailed))
        message = translate_message(str(exc))
        if message == str(exc) and not any(ord(c) > 127 for c in message):
            message = 'Không thể hoàn tất tác vụ. Hãy kiểm tra last-error.log, cấu hình và tệp nguồn rồi thử lại.'
        (folder / 'last-error.log').write_text(traceback.format_exc(), encoding='utf-8')
        cues = read_json(folder / 'cues.json')
        store.update_job(jid, status='awaiting_review' if review else 'failed', stage='awaiting_review' if review else 'failed',
                         error=message, cue_count=len(cues), activity=push_activity(latest, message), **idle, progress=45 if review else latest['progress'])
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
