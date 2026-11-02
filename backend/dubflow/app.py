import asyncio
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import Settings
from .preferences import preferences, translation_ready
from . import translate_run, timing
from .studio import install_routes
from .publisher import safe_name
from .media import atomic_json, contained, parse_srt, poster, probe, read_json, run
from . import logos as logo_lib
from .schemas import OverlaysIn, TextLogoIn, Cue, JobUpdate, Part, Region, VoiceUpdate, ReviewUpdate, RenderRequest, TranslateRequest, DetectLogosRequest
from . import review
from .pipeline import erase_current, erases_static
from .store import Store
from .subtitle_style import FONT_FILE, FONTS_DIR, style_for
from .messages import translate_message
from .voices import all_voices, check_audio, get_voice, public_voice, voice_ref

BUSY = {'queued', 'processing', 'separating', 'transcribing', 'synthesizing', 'rendering'}
SAMPLE_FILES = {
    'review': ('Thí nghiệm bí ẩn', 'SaveDouyin_Douyin_Media_7694606242899053859_001_1080p.mp4', 'dub'),
    'dialogue': ('Đừng lo cho em', 'SaveDouyin_Douyin_Media_7696391076050996514_001_1080p.mp4', 'vietsub'),
}


def create_app(settings: Settings | None = None, start_worker=True):
    settings = (settings or Settings()).ensure()
    store = Store(settings.db_path)
    stop = threading.Event()
    thumbnail_lock = threading.Lock()
    if start_worker:
        tempfile.tempdir = str(settings.data_dir / 'tmp')

    @asynccontextmanager
    async def lifespan(app):
        thread = None
        if start_worker and not settings.redis_url and os.getenv('DUBFLOW_EMBEDDED_WORKER', '1') == '1':
            from .worker import worker_loop
            thread = threading.Thread(target=worker_loop, args=(settings, stop), daemon=True, name='dubflow-worker')
            thread.start()
        yield
        stop.set()
        if thread:
            thread.join(timeout=3)

    app = FastAPI(title='DubFlow Local API', version='0.1.0', lifespan=lifespan)
    app.state.store, app.state.settings = store, settings
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.allowed_origins), allow_methods=['GET', 'POST', 'PUT', 'DELETE'], allow_headers=['Content-Type', 'Last-Event-ID'])
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])

    @app.middleware('http')
    async def local_origin_guard(request, call_next):
        if request.method in ('POST', 'PUT', 'DELETE', 'PATCH'):
            origin = request.headers.get('origin')
            if origin and origin not in settings.allowed_origins:
                return JSONResponse({'detail': 'Không chấp nhận thao tác từ trang ngoài.'}, 403)
        return await call_next(request)

    def job_or_404(job_id):
        job = store.get_job(job_id)
        if not job:
            raise HTTPException(404, 'Không tìm thấy dự án.')
        return job

    def review_job(job):
        collection=store.get_record('collection',job.get('collection_id')) if job.get('collection_id') else None
        return dict(job,review_terms=(collection or {}).get('terminology',''),vietsub_cps=preferences(store,settings)['vietsub_cps'])

    def terminology_for(job):
        collection=store.get_record('collection',job.get('collection_id')) if job.get('collection_id') else None
        return (collection or {}).get('terminology','')

    def job_dir(job_id):
        job_or_404(job_id)
        return contained(settings.jobs_dir, job_id)

    def writable(job_id):
        job = job_or_404(job_id)
        if job['status'] in BUSY:
            raise HTTPException(409, 'Tạm dừng tác vụ trước khi sửa dự án.')
        return job

    def public_job(job):
        value = {k: v for k, v in job.items() if k not in ('source_path', 'voice_ref', 'root')}
        collection = store.get_record('collection', job.get('collection_id')) if job.get('collection_id') else None
        value.update(collection_id=job.get('collection_id'), collection_name=collection['name'] if collection else None, episode=job.get('episode',''), exported_paths=job.get('exported_paths',[]), export_dir=job.get('export_dir'))
        value['error'] = translate_message(value.get('error'))
        value['warnings'] = [translate_message(w) for w in value.get('warnings', [])]
        value['export_filename'] = safe_name(job.get('title','Video')) + '.mp4'
        base = f"/api/jobs/{job['id']}"
        folder = settings.jobs_dir / job['id']
        value['source_url_path'] = base + '/source'
        value['poster_url'] = base + '/poster' if (folder / 'poster.jpg').exists() else None
        value['output_url'] = base + '/output' if (folder / 'output.mp4').exists() and job['status'] == 'done' else None
        value['dry_url'] = base + '/audio' if (folder / 'dry.wav').exists() else None
        clean = folder / 'clean.mp4'
        value['clean_url'] = None
        if clean.is_file() and job.get('source_path') and erase_current(folder, job['source_path'], full=False):
            value['clean_url'] = f'{base}/clean?v={clean.stat().st_mtime_ns}'
        value['overlays'] = job.get('overlays', [])
        value['translation_usage'] = translate_run.read_usage(folder)
        est = timing.estimates(settings.data_dir, job)
        value['stage_estimates'] = est
        value['stage_step'] = job.get('stage_step')
        value['stage_started_at'] = job.get('stage_started_at')
        value['stage_detail'] = job.get('stage_detail')
        value['eta_seconds'] = timing.eta_seconds(job, est)
        value['activity'] = job.get('activity') or []
        value['queue'] = None
        if job.get('status') == 'queued':
            info = store.queue_info(job['id'])
            if info:
                beat = read_json(settings.data_dir / 'worker-heartbeat.json', {}) or {}
                # the heartbeat is only refreshed between tasks, so a running task also proves the worker is alive
                info['worker_alive'] = info['running_ahead'] or (isinstance(beat.get('time'), (int, float)) and time.time() - beat['time'] < 15)
                value['queue'] = info
        value['subtitle_style'] = style_for(int(job.get('width') or 1920), int(job.get('height') or 1080))
        return value

    def invalidate(job_id):
        job = store.update_job(job_id, status='awaiting_review', stage='awaiting_review', progress=45, error=None, ready_count=0)
        store.event(job_id, 'awaiting_review', 'Nội dung đã thay đổi. Cần xử lý lại để cập nhật kết quả.', 45)
        return job

    def save_job_file(job):
        atomic_json(job_dir(job['id']) / 'job.json', job)

    async def save_upload(upload: UploadFile, dest: Path, limit):
        size = 0
        try:
            with dest.open('wb') as out:
                while data := await upload.read(1024 * 1024):
                    size += len(data)
                    if size > limit:
                        raise HTTPException(413, 'File vượt quá giới hạn dung lượng.')
                    out.write(data)
            if size == 0:
                raise HTTPException(400, 'File trống.')
        except Exception:
            dest.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()

    def validate_cues(cues, job, require_text=False):
        if len(cues) > 50000:
            raise HTTPException(422, 'Quá nhiều câu.')
        ids = set()
        prev = -1.0
        for cue in cues:
            if cue.id in ids or cue.start < prev or cue.end <= cue.start or cue.end > job['duration'] + .05:
                raise HTTPException(422, 'Mốc câu phải theo thứ tự, không trùng ID và nằm trong thời lượng video.')
            if require_text and not cue.text.strip():
                raise HTTPException(409, 'Có câu chưa có bản dịch tiếng Việt. Hãy sửa lời hoặc nhập SRT.')
            prev = cue.start
            ids.add(cue.id)
        optional = ('source', 'asr_text', 'source_agreement', 'source_mismatch', 'source_partial', 'ocr_empty', 'box')
        return [{k: v for k, v in c.model_dump().items() if k not in optional or v is not None} for c in cues]

    def dispatch(job_id, action, before_commit=None):
        (job_dir(job_id) / 'cancel.request').unlink(missing_ok=True)
        try:
            task_id = store.enqueue(job_id, action, before_commit)
        except ValueError as e:
            raise HTTPException(409, str(e))
        if settings.redis_url:
            from redis import Redis
            from rq import Queue
            try:
                Queue('dubflow', connection=Redis.from_url(settings.redis_url)).enqueue('dubflow.worker.run_rq_task', str(settings.data_dir), task_id, job_timeout=86400)
            except Exception:
                store.finish_task(task_id, 'failed')
                store.update_job(job_id, status='failed', error='Không kết nối được Redis. Kiểm tra Redis và worker.')
                raise HTTPException(503, 'Không kết nối được Redis.')
        store.event(job_id, 'queued', 'Đã đưa vào hàng đợi.', 0)
        return public_job(store.get_job(job_id))

    def default_overlays(prefs, metadata):
        pref = prefs.get('default_overlay')
        logo = store.get_record('logo', pref['logo_id']) if pref else None
        if not logo or not (settings.data_dir / 'logos' / f"{logo['id']}.png").is_file():
            return []
        return [logo_lib.default_overlay(pref, logo, metadata['width'], metadata['height'], metadata['duration'])]

    @app.get('/api/health')
    def health():
        cache = Path(settings.model_cache)
        capabilities = dict(ffmpeg=Path(settings.ffmpeg).exists(), voice_synthesis=Path(settings.tts_python).exists() and (cache / 'models--openbmb--VoxCPM2').exists(),
                            transcription=Path(settings.asr_python).exists(), ocr=Path(settings.ocr_python).exists(),
                            automatic_translation=translation_ready(preferences(store,settings)),
                            douyin_download=False)
        warnings = []
        if not capabilities['automatic_translation']:
            warnings.append('Chưa cấu hình dịch tự động. Duyệt/nhập lời Việt hoặc nhập SRT trước khi xuất.')
        if not capabilities['voice_synthesis']:
            warnings.append('Chưa tìm thấy runtime hoặc model VoxCPM2.')
        lock = settings.data_dir / 'worker-heartbeat.json'
        return dict(status='ok', queue_backend=settings.queue_backend, capabilities=capabilities, warnings=warnings,
                    worker=read_json(lock, {}), disk_free_bytes=shutil.disk_usage(settings.data_dir).free)

    @app.get('/api/fonts/{name}')
    def font_file(name: str):
        if name != FONT_FILE:
            raise HTTPException(404, 'Không tìm thấy font.')
        return FileResponse(FONTS_DIR / FONT_FILE, media_type='font/ttf', headers={'Cache-Control': 'public, max-age=86400'})

    @app.get('/api/jobs')
    def jobs():
        return [{**public_job(j), 'activity': []} for j in store.list_jobs()]

    @app.post('/api/jobs', status_code=201)
    async def upload_job(file: UploadFile = File(...), mode: Literal['dub', 'tm', 'vietsub'] | None = Form(None),
                         voice_id: str | None = Form(None), source_url: str = Form(''), rights_confirmed: bool = Form(False),
                         collection_id: str = Form(''), episode: str = Form(''), title: str = Form('')):
        if not rights_confirmed:
            raise HTTPException(400, 'Cần xác nhận có quyền sử dụng video và giọng nói.')
        prefs = preferences(store, settings)
        collection = store.get_record('collection',collection_id) if collection_id else None
        if collection_id and not collection:
            raise HTTPException(422, 'Bộ sưu tập không tồn tại.')
        if len(episode)>100 or len(title)>200:
            raise HTTPException(422, 'Tên hoặc tập quá dài.')
        mode = mode or prefs['default_mode']
        if voice_id is None:
            voice_id = (collection or {}).get('default_voice_id') or prefs['default_voice_id'] or ''
        name = Path((file.filename or 'video').replace('\\', '/')).name
        suffix = Path(name).suffix.lower()
        if suffix not in ('.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v'):
            raise HTTPException(400, 'Định dạng video chưa được hỗ trợ.')
        if len(source_url) > 2000:
            raise HTTPException(422, 'Link nguồn quá dài.')
        v = get_voice(settings, voice_id) if voice_id else None
        if voice_id and not v:
            raise HTTPException(422, 'Giọng không tồn tại.')
        temp = settings.data_dir / 'tmp' / (uuid.uuid4().hex + suffix)
        await save_upload(file, temp, settings.max_upload_bytes)
        try:
            metadata = probe(temp, settings)
        except (ValueError, OSError, TimeoutError) as e:
            temp.unlink(missing_ok=True)
            raise HTTPException(400, str(e))
        overlays = default_overlays(prefs, metadata)
        job = store.create_job(dict(title=title.strip() or Path(name).stem[:200], collection_id=collection_id or None, episode=episode, filename=name, mode=mode, voice_id=voice_id or None,
                                   source_url=source_url, rights_confirmed=True, overlays=overlays, **metadata))
        folder = settings.jobs_dir / job['id']
        folder.mkdir()
        source = folder / ('source' + suffix)
        temp.replace(source)
        values = dict(source_path=str(source))
        if v:
            values['voice_ref'] = voice_ref(v)
        job = store.update_job(job['id'], **values)
        save_job_file(job)
        atomic_json(folder / 'parts.json', [dict(id='1', title='Phần 1', start=0, end=job['duration'])])
        try:
            poster(source, folder / 'poster.jpg', settings)
        except ValueError:
            pass
        store.event(job['id'], 'created', 'Đã tải video lên máy chủ cục bộ.', 0)
        return public_job(job)

    @app.get('/api/jobs/{job_id}')
    def get_job(job_id: str):
        return public_job(job_or_404(job_id))

    @app.put('/api/jobs/{job_id}')
    def update_job(job_id: str, values: JobUpdate):
        previous = writable(job_id)
        fields = values.model_dump(exclude_unset=True)
        if fields.get('title') is None:
            fields.pop('title',None)
        if 'title' in fields and not fields['title'].strip():
            raise HTTPException(422,'Tên dự án không được trống.')
        if fields.get('collection_id') and not store.get_record('collection',fields['collection_id']):
            raise HTTPException(422,'Bộ sưu tập không tồn tại.')
        if 'voice_id' in fields:
            v = get_voice(settings, fields['voice_id']) if fields['voice_id'] else None
            if fields['voice_id'] and not v:
                raise HTTPException(422, 'Giọng không tồn tại.')
            fields['voice_ref'] = voice_ref(v) if v else None
        if fields.get('mode') is None:
            fields.pop('mode', None)
        job = store.update_job(job_id, **fields)
        if any(key in fields and fields[key] != previous.get(key) for key in ('mode','voice_id','voice_ref')):
            invalidate(job_id)
        save_job_file(store.get_job(job_id))
        return public_job(store.get_job(job_id))

    @app.get('/api/jobs/{job_id}/cues')
    def get_cues(job_id: str):
        cs = sorted(read_json(job_dir(job_id) / 'cues.json'),key=lambda c:(c['start'],c['end']))
        if cs:
            report=review.quality_report(job_dir(job_id),review_job(job_or_404(job_id)))
            flags={c['id']:[] for c in cs}
            for flag in report['flags']:
                for cid in flag['cue_ids']:
                    if cid in flags:flags[cid].append(flag['message'])
            for c in cs:c['auto_flags']=list(dict.fromkeys(flags[c['id']]))[:4]
        for c in cs:
            path = c.get('take_path') or c.get('path')
            if path:
                try:
                    relative = Path(path).resolve().relative_to(job_dir(job_id).resolve()).as_posix()
                    c['take_url'] = f'/api/jobs/{job_id}/lines/{relative}'
                except ValueError:
                    pass
            c.pop('take_path', None)
            c.pop('path', None)
        return cs

    @app.get('/api/jobs/{job_id}/source-subtitles.srt')
    def source_subtitles(job_id: str):
        job=job_or_404(job_id)
        cues=sorted(read_json(job_dir(job_id)/'cues.json',[]),key=lambda c:(c['start'],c['end']))
        if not cues:raise HTTPException(409,'Chưa có lời gốc. Phân tích video trước khi xuất tiếng Trung.')
        if any(not c.get('original','').strip() for c in cues):
            raise HTTPException(409,'Có câu chưa có lời Trung. Kiểm tra lời gốc trước khi xuất.')
        from urllib.parse import quote
        from .publisher import srt_text
        from .dialogue_export import dialogue_source_cues
        dialogue = dialogue_source_cues(cues)
        if not dialogue:raise HTTPException(409,'Không có câu thoại tiếng Trung để xuất.')
        filename=quote(safe_name(job['title'])+'.zh.srt')
        return Response(srt_text(dialogue).encode('utf-8-sig'),media_type='application/x-subrip',
                        headers={'Content-Disposition':f"attachment; filename*=UTF-8''{filename}"})

    @app.get('/api/jobs/{job_id}/translate-prompt')
    def translate_prompt(job_id: str, mode: Literal['vietsub', 'tm', 'dub'] | None = None):
        from .manual_translation import prompt_text
        job = job_or_404(job_id)
        chosen = mode or (job.get('mode') if job.get('mode') in ('vietsub', 'tm', 'dub') else 'vietsub')
        text = prompt_text(chosen, preferences(store, settings)['vietsub_cps'], terminology_for(job))
        return Response(text.encode('utf-8'), media_type='text/plain; charset=utf-8')

    @app.post('/api/jobs/{job_id}/translation-srt')
    async def import_translation_srt(job_id: str, file: UploadFile = File(...)):
        from .manual_translation import parse_indexed_srt, match_by_index
        from .dialogue_export import dialogue_source_cues
        job = writable(job_id)
        folder = job_dir(job_id)
        data = await file.read(2 * 1024 * 1024 + 1)
        await file.close()
        if len(data) > 2 * 1024 * 1024:
            raise HTTPException(413, 'SRT vượt quá 2 MB.')
        stored = read_json(folder / 'cues.json', [])
        if not stored:
            raise HTTPException(409, 'Chưa có lời gốc. Phân tích video trước khi nhập bản dịch.')
        review.load_state(folder)
        try:
            try:
                content = data.decode('utf-8-sig')
            except UnicodeError:
                raise ValueError('File phải mã hóa UTF-8.')
            blocks = parse_indexed_srt(content)
            dialogue = dialogue_source_cues(sorted(stored, key=lambda c: (c['start'], c['end'])))
            texts = match_by_index(blocks, [c['id'] for c in dialogue])
        except (ValueError, UnicodeError) as e:
            raise HTTPException(422, str(e))
        state = review.load_state(folder)
        collection_terms = terminology_for(job)
        touched = []
        for c in stored:
            if c['id'] in texts:
                c.update(text=texts[c['id']], status='needs_review', asr_edits=None, take_url=None, delay=None, overrun=None)
                touched.append(c)
        for c in touched:
            c['translation_dependency'] = review.translation_dependency(c, state, stored, collection_terms)
        atomic_json(folder / 'cues.json', stored)
        store.update_job(job_id, cue_count=len(stored))
        invalidate(job_id)
        return stored

    @app.put('/api/jobs/{job_id}/cues')
    def put_cues(job_id: str, cs: list[Cue]):
        job = writable(job_id)
        review.load_state(job_dir(job_id))
        values = validate_cues(cs, job)
        old={c['id']:c for c in read_json(job_dir(job_id)/'cues.json',[])}
        # Discard client-reported ASR success; synthesis cache is rechecked by the worker.
        for c in values:
            if old.get(c['id'],{}).get('translation_dependency'):
                c['translation_dependency']=old[c['id']]['translation_dependency']
            c.update(status='pending', asr_edits=None, take_url=None, delay=None, overrun=None)
            if c['id'] in old and old[c['id']].get('original') != c.get('original'):
                for flag in ('ocr_empty', 'source_mismatch', 'source_partial'):  # stale after a manual edit of the source text
                    c.pop(flag, None)
        atomic_json(job_dir(job_id) / 'cues.json', values)
        store.update_job(job_id, cue_count=len(values))
        invalidate(job_id)
        return values

    @app.post('/api/jobs/{job_id}/subtitles')
    async def import_subtitles(job_id: str, file: UploadFile = File(...)):
        job = writable(job_id)
        folder=job_dir(job_id)
        if read_json(folder/'cues.json',[]):
            review.load_state(folder)
        data = await file.read(2 * 1024 * 1024 + 1)
        await file.close()
        if len(data) > 2 * 1024 * 1024:
            raise HTTPException(413, 'SRT vượt quá 2 MB.')
        try:
            cs = [Cue(**c) for c in parse_srt(data.decode('utf-8-sig'))]
            values = validate_cues(cs, job)
        except (ValueError, UnicodeError) as e:
            raise HTTPException(422, str(e))
        # Retain old source links when importing translations on matching intervals.
        previous=read_json(folder/'cues.json',[])
        for value in values:
            value['source_ids']=review.imported_links(value,previous)
            value['id']='srt-'+uuid.uuid4().hex
            exact=next((c for c in previous if abs(c['start']-value['start'])<1e-6 and abs(c['end']-value['end'])<1e-6),None)
            if exact:value['original']=exact.get('original','')
        atomic_json(folder / 'cues.json', values)
        state=review.load_state(folder)
        current_ids={c['id'] for c in values}
        review.save_state(folder,review_job(job),dict(revision=state['revision'],assignments={k:v for k,v in state.get('assignments',{}).items() if k in current_ids}))
        store.update_job(job_id, cue_count=len(values))
        invalidate(job_id)
        return values

    def decorate_regions(job_id, j, rows):
        """Response-only fields (never stored): erased flag of static regions and preview mask urls."""
        folder=job_dir(job_id)
        if j.get('source_path') and (folder / 'clean.mp4').is_file() and erase_current(folder, j['source_path'], full=False):
            erased=set(read_json(folder / 'erase.json',{}).get('static_ids') or [])
            for row in rows:
                if erases_static(row) and row.get('id') in erased:
                    row['erased']=True
        for row in rows:
            for index,box in enumerate(row.get('boxes',[row])):
                if box.get('mask_path') and box.get('mask_crop'):
                    box['preview_mask_url']=f"/api/jobs/{job_id}/text-mask/{row['id']}?box={index}"
        return rows

    def only_decision_changed(previous, values):
        """True when the new regions differ from the stored ones in confirmed/label only (ticking or relabelling a box).
        Ticking an unreviewed auto candidate is not one: it starts being erased."""
        decision=('confirmed','label')
        try:
            old=[Region(**r).model_dump() for r in previous]
        except Exception:  # noqa: BLE001 - legacy rows that no longer validate: treat as a real change
            return False
        if len(old)!=len(values) or any(erases_static(a)!=erases_static(b) for a,b in zip(old,values)):
            return False
        strip=lambda row:{k:v for k,v in row.items() if k not in decision}
        return all(strip(a)==strip(b) for a,b in zip(old,values)) and any(any(a[k]!=b[k] for k in decision) for a,b in zip(old,values))

    @app.get('/api/jobs/{job_id}/regions')
    def get_regions(job_id: str):
        j=job_or_404(job_id)
        return decorate_regions(job_id,j,read_json(job_dir(job_id) / 'regions.json',[]))

    @app.get('/api/jobs/{job_id}/text-mask/{region_id}')
    def preview_text_mask(job_id: str,region_id: str,box: int=0):
        """Expose only server-owned OCR masks, never arbitrary filesystem paths."""
        import base64
        import struct
        job_or_404(job_id)
        folder=job_dir(job_id).resolve()
        row=next((r for r in read_json(folder/'regions.json',[]) if r['id']==region_id),None)
        boxes=row.get('boxes',[row]) if row else []
        if box<0 or box>=len(boxes):raise HTTPException(404,'Không có vùng chữ.')
        entry=boxes[box]
        path=(folder/entry.get('mask_path','')).resolve()
        crop=entry.get('mask_crop')
        if not path.is_relative_to(folder) or path.suffix.lower()!='.png' or not path.is_file() or not crop:
            raise HTTPException(404,'Không có mặt nạ chữ.')
        x,y,w,h=map(int,crop)
        raw=path.read_bytes()
        iw,ih=struct.unpack('>II',raw[16:24])
        data=base64.b64encode(raw).decode('ascii')
        svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="{x} {y} {w} {h}"><image width="{iw}" height="{ih}" href="data:image/png;base64,{data}"/></svg>'
        return Response(svg,media_type='image/svg+xml',headers={'Cache-Control':'private, max-age=3600'})

    @app.put('/api/jobs/{job_id}/regions')
    def put_regions(job_id: str, regions: list[Region]):
        j = writable(job_id)
        if len(regions) > 10000:
            raise HTTPException(422, 'Quá nhiều vùng chữ.')
        for r in regions:
            if r.x + r.width > j['width'] or r.y + r.height > j['height'] or r.end > j['duration'] + .05 or r.end <= r.start:
                raise HTTPException(422, 'Vùng chữ phải nằm trong khung hình và thời lượng video.')
        # Masks are server-generated assets. Retain them when users only edit
        # text/translation/enabled, but never accept arbitrary paths from clients.
        stored = read_json(job_dir(job_id)/'regions.json',[])
        previous = {r['id']: r for r in stored}
        values = [r.model_dump() for r in regions]
        decision_only = only_decision_changed(stored, values)
        for value in values:
            old = previous.get(value['id'],{})
            if all(old.get(k)==value.get(k) for k in ('x','y','width','height','start','end','kind')):
                for key in ('mask_path','mask_crop','boxes'):
                    if key in old:
                        value[key] = old[key]
        atomic_json(job_dir(job_id) / 'regions.json', values)
        if not decision_only:  # ticking or relabelling a box changes neither what is erased nor drawn: keep status and output
            invalidate(job_id)
        return decorate_regions(job_id,j,[dict(v) for v in values])

    def logo_or_404(logo_id):
        record = store.get_record('logo', logo_id) if logo_lib.LOGO_ID.match(logo_id) else None
        if not record or not (settings.data_dir / 'logos' / f'{logo_id}.png').is_file():
            raise HTTPException(404, 'Không tìm thấy logo.')
        return record

    @app.post('/api/logos', status_code=201)
    async def upload_logo(file: UploadFile = File(...), name: str = Form('')):
        raw = await file.read(logo_lib.MAX_BYTES + 1)
        label = (name.strip() or Path((file.filename or 'logo').replace('\\', '/')).stem or 'logo')[:100]
        try:
            return await asyncio.to_thread(logo_lib.save, raw, label, settings, store)
        except ValueError as e:
            raise HTTPException(422, str(e))

    @app.post('/api/logos/text', status_code=201)
    async def create_text_logo(body: TextLogoIn):
        # Editing a text logo is a new POST (a new id); overlays keep the old one until changed, and the old entry can be deleted once unused.
        def make():
            png, text, style = logo_lib.render_text(body.text, body.style, settings)
            return logo_lib.save(png, body.name.strip()[:100] or text, settings, store, 'text', dict(text=text, style=style))
        try:
            return await asyncio.to_thread(make)
        except ValueError as e:
            raise HTTPException(422, str(e))

    @app.get('/api/logos')
    def list_logos():
        return [logo_lib.public(r) for r in store.list_records('logo') if (settings.data_dir / 'logos' / f"{r['id']}.png").is_file()]

    @app.get('/api/logos/{logo_id}/image')
    def logo_image(logo_id: str):
        logo_or_404(logo_id)
        return FileResponse(settings.data_dir / 'logos' / f'{logo_id}.png', media_type='image/png', headers={'Cache-Control': 'private, max-age=86400'})

    @app.delete('/api/logos/{logo_id}', status_code=204)
    def delete_logo(logo_id: str):
        logo_or_404(logo_id)
        used = [j for j in store.list_jobs() if any(o.get('logo_id') == logo_id for o in j.get('overlays', []))]
        if used:
            raise HTTPException(409, f'Logo đang được dùng trong {len(used)} dự án. Gỡ logo khỏi các dự án đó trước khi xoá.')
        (settings.data_dir / 'logos' / f'{logo_id}.png').unlink(missing_ok=True)
        store.delete_record('logo', logo_id)
        prefs = preferences(store, settings)
        if (prefs.get('default_overlay') or {}).get('logo_id') == logo_id:  # a default that points nowhere would only fail new jobs
            store.put_record('settings', 'main', dict(prefs, default_overlay=None))
        return Response(status_code=204)

    @app.put('/api/jobs/{job_id}/overlays')
    def put_overlays(job_id: str, body: OverlaysIn):
        j = writable(job_id)
        W, H, D = float(j.get('width') or 0), float(j.get('height') or 0), float(j.get('duration') or 0)
        values = []
        for o in body.overlays:
            logo_or_404(o.logo_id)
            end = min(o.end if o.end is not None else D, D)
            if o.start >= end:
                raise HTTPException(422, 'Thời gian hiển thị logo phải nằm trong thời lượng video.')
            x, y, w, h = logo_lib.clamp_box(o.x, o.y, o.width, o.height, W, H)
            values.append(dict(id=o.id or uuid.uuid4().hex[:12], logo_id=o.logo_id, x=x, y=y, width=w, height=h, opacity=o.opacity, start=o.start, end=end))
        if len({v['id'] for v in values}) != len(values):
            raise HTTPException(422, 'ID logo bị trùng.')
        if values != j.get('overlays', []):
            j = store.update_job(job_id, overlays=values)
            save_job_file(j)
            if j['status'] == 'done':  # the exported file no longer matches; clean.mp4 is untouched (its signature ignores overlays)
                invalidate(job_id)
        return values

    @app.get('/api/jobs/{job_id}/parts')
    def get_parts(job_id: str):
        j = job_or_404(job_id)
        return read_json(job_dir(job_id) / 'parts.json', [dict(id='1', title='Phần 1', start=0, end=j['duration'])])

    @app.put('/api/jobs/{job_id}/parts')
    def put_parts(job_id: str, parts: list[Part]):
        j = writable(job_id)
        last = 0
        ids = set()
        if not parts:
            raise HTTPException(422, 'Cần ít nhất một phần.')
        for p in parts:
            if p.id in ids or p.start < last or p.end <= p.start or p.end > j['duration'] + .05:
                raise HTTPException(422, 'Các phần phải tăng dần, không chồng nhau và nằm trong video.')
            ids.add(p.id)
            last = p.end
        values = [p.model_dump() for p in parts]
        atomic_json(job_dir(job_id) / 'parts.json', values)
        invalidate(job_id)
        return values

    @app.post('/api/jobs/{job_id}/analyze')
    def analyze(job_id: str, reset_source: int = 0):
        writable(job_id)
        if reset_source:
            folder = job_dir(job_id)
            cues = folder / 'cues.json'
            if cues.exists():
                stamp = time.strftime('%Y%m%d-%H%M%S')
                shutil.copy2(cues, folder / f'cues.before-reset-{stamp}.json')
            for name in ('cues.json', 'subtrack.json', 'source-build.json', 'source-asr-cues.json'):
                (folder / name).unlink(missing_ok=True)
            store.update_job(job_id, cue_count=0)
        return dispatch(job_id, 'analyze')

    def translate_preflight(job, scope):
        prefs = preferences(store, settings)
        if not translation_ready(prefs):
            raise HTTPException(409, 'Chưa cấu hình bộ dịch. Mở Cài đặt → Dịch tự động, nhập key và chọn model.')
        folder = job_dir(job['id'])
        if not read_json(folder / 'cues.json', []):
            raise HTTPException(409, 'Chưa có lời gốc. Bấm Phân tích video trước khi dịch.')
        return prefs, folder

    @app.get('/api/jobs/{job_id}/translate/estimate')
    def translate_estimate(job_id: str, scope: Literal['missing', 'all'] = 'missing'):
        job = job_or_404(job_id)
        prefs, folder = translate_preflight(job, scope)
        result = translate_run.estimate(folder, scope, job.get('mode') or 'vietsub', prefs, terminology_for(job))
        if result is None:
            raise HTTPException(409, 'Không có câu nào cần dịch.')
        return result

    @app.post('/api/jobs/{job_id}/translate')
    def translate_job(job_id: str, body: TranslateRequest):
        job = writable(job_id)
        if any(t['job_id'] == job_id and t['action'] == 'translate' and t['state'] in ('pending', 'running') for t in store.active_tasks()):
            raise HTTPException(409, 'Đang dịch video này.')
        prefs, folder = translate_preflight(job, body.scope)
        if not translate_run.collect_items(folder, body.scope):
            raise HTTPException(409, 'Không có câu nào cần dịch.')
        request = folder / translate_run.REQUEST_FILE
        # The file is written inside the enqueue transaction, only once this call owns the task.
        write_request = lambda: atomic_json(request, dict(scope=body.scope, allow_over_cap=body.allow_over_cap))
        try:
            return dispatch(job_id, 'translate', write_request)
        except HTTPException as exc:
            if exc.status_code == 503:  # Redis refused: nobody will read this request
                request.unlink(missing_ok=True)
            raise

    @app.post('/api/jobs/{job_id}/detect-logos')
    def detect_logos_job(job_id: str, body: DetectLogosRequest):
        job = writable(job_id)
        if not job.get('source_path'):
            raise HTTPException(409, 'Chưa có video nguồn.')
        request = job_dir(job_id) / 'detect-logos-request.json'
        # where the job was, so the worker can put it back (written only once this call owns the task)
        write_request = lambda: atomic_json(request, {k: job.get(k) for k in ('status', 'stage', 'progress', 'error')})
        try:
            return dispatch(job_id, 'detect_logos', write_request)
        except HTTPException as exc:
            if exc.status_code == 503:
                request.unlink(missing_ok=True)
            raise

    @app.get('/api/jobs/{job_id}/review')
    def get_review(job_id: str):
        return review.public_state(job_dir(job_id),review_job(job_or_404(job_id)))

    @app.get('/api/jobs/{job_id}/quality')
    def get_quality(job_id: str):
        return review.quality_report(job_dir(job_id),review_job(job_or_404(job_id)))

    @app.put('/api/jobs/{job_id}/review')
    def put_review(job_id: str, body: ReviewUpdate):
        job=writable(job_id)
        known={c['id'] for c in body.characters}
        if len(known)!=len(body.characters):raise HTTPException(422,'ID nhân vật bị trùng.')
        cue_ids={c['id'] for c in read_json(job_dir(job_id)/'cues.json',[])}
        if set(body.assignments)-cue_ids:raise HTTPException(422,'Gán vai có ID câu không tồn tại.')
        for assignment in body.assignments.values():
            if any(v and v not in known for v in (assignment.speaker_confirmed,assignment.listener_confirmed,assignment.speaker_candidate,assignment.listener_candidate)):
                raise HTTPException(422,'Nhân vật gán chưa có trong danh sách.')
        for rule in body.address_rules:
            if rule.speaker_id not in known or rule.listener_id not in known:raise HTTPException(422,'Cặp xưng hô có nhân vật không tồn tại.')
        try:
            state=review.save_state(job_dir(job_id),review_job(job),body.model_dump())
        except ValueError as exc:
            raise HTTPException(409,str(exc)) from None
        invalidate(job_id)
        return state

    @app.post('/api/jobs/{job_id}/render')
    def render_job(job_id: str, body: RenderRequest | None = None):
        job = writable(job_id)
        cs = sorted([Cue(**c) for c in read_json(job_dir(job_id) / 'cues.json')],key=lambda c:(c.start,c.end))
        if not cs:
            raise HTTPException(409, 'Chưa có lời dịch. Phân tích video hoặc nhập SRT trước.')
        validate_cues(cs, job, require_text=True)
        kind=body.kind if body else 'auto'
        try:review.require_export(job_dir(job_id),review_job(job),kind)
        except ValueError as exc:raise HTTPException(409,str(exc)) from None
        if job['mode'] == 'tm' and not job.get('voice_id'):
            raise HTTPException(409, 'Chọn giọng thuyết minh trước khi xử lý.')
        store.update_job(job_id,export_kind=kind)
        return dispatch(job_id, 'render')

    @app.post('/api/jobs/{job_id}/cancel')
    def cancel_job(job_id: str):
        job_or_404(job_id)
        (job_dir(job_id) / 'cancel.request').touch()
        store.cancel(job_id)
        store.event(job_id, 'cancelled', 'Đã yêu cầu dừng. Worker sẽ giải phóng tác vụ hiện tại.', 0)
        return public_job(store.get_job(job_id))

    @app.get('/api/jobs/{job_id}/logs')
    def logs(job_id: str):
        job_or_404(job_id)
        return dict(events=store.events(job_id))

    @app.get('/api/jobs/{job_id}/events')
    async def events(job_id: str, request: Request):
        job_or_404(job_id)
        async def stream():
            previous = ''
            idle = 0
            while not await request.is_disconnected():
                current = store.get_job(job_id)
                if not current:
                    return  # job was deleted: end the stream quietly
                snapshot = json.dumps(public_job(current), ensure_ascii=False)
                if snapshot != previous:
                    yield f'data: {snapshot}\n\n'
                    previous = snapshot
                    idle = 0
                else:
                    idle += 1
                    if idle % 10 == 0:
                        yield ': keepalive\n\n'
                await asyncio.sleep(1)
        return StreamingResponse(stream(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    @app.get('/api/jobs/{job_id}/source')
    def source(job_id: str):
        j = job_or_404(job_id)
        path = Path(j.get('source_path', ''))
        if not path.is_file() or not path.resolve().is_relative_to(job_dir(job_id).resolve()):
            raise HTTPException(404, 'Không tìm thấy video nguồn.')
        return FileResponse(path)

    @app.get('/api/jobs/{job_id}/clean')
    def clean_video(job_id: str):
        j = job_or_404(job_id)
        path = job_dir(job_id) / 'clean.mp4'
        if not path.is_file() or not j.get('source_path') or not erase_current(job_dir(job_id), j['source_path'], full=False):
            raise HTTPException(404, 'Chưa có video đã xóa sub gốc.')
        return FileResponse(path, media_type='video/mp4')

    @app.get('/api/jobs/{job_id}/poster')
    def get_poster(job_id: str):
        path = job_dir(job_id) / 'poster.jpg'
        if not path.exists():
            raise HTTPException(404, 'Chưa có ảnh xem trước.')
        return FileResponse(path)

    @app.get('/api/jobs/{job_id}/thumbnails/{index}')
    def thumbnail(job_id: str, index: int):
        j = job_or_404(job_id)
        if not 0 <= index < 8:
            raise HTTPException(404, 'Không có khung hình này.')
        source_path = contained(job_dir(job_id), Path(j['source_path']).name)
        folder = job_dir(job_id) / 'thumbnails'
        path = folder / f'{index}.jpg'
        with thumbnail_lock:
            if not path.exists():
                folder.mkdir(exist_ok=True)
                dest = folder / f'{index}.tmp.jpg'
                stamp = max(0, float(j['duration']) * (index + .5) / 8)
                run([settings.ffmpeg, '-v', 'error', '-y', '-ss', str(stamp), '-i', source_path,
                     '-frames:v', '1', '-vf', 'scale=160:90:force_original_aspect_ratio=decrease,pad=160:90:(ow-iw)/2:(oh-ih)/2',
                     '-q:v', '4', dest], 30)
                if not dest.is_file():
                    raise HTTPException(422, 'Không lấy được khung hình video.')
                dest.replace(path)
        return FileResponse(path, media_type='image/jpeg')

    @app.get('/api/jobs/{job_id}/audio')
    def get_audio(job_id: str):
        path = job_dir(job_id) / 'dry.wav'
        if not path.exists():
            raise HTTPException(404, 'Chưa có track giọng Việt.')
        return FileResponse(path)

    @app.get('/api/jobs/{job_id}/lines/{name:path}')
    def get_line(job_id: str, name: str):
        try:
            path = contained(job_dir(job_id), name)
        except ValueError:
            raise HTTPException(404, 'Không tìm thấy audio.')
        if path.suffix.lower() not in ('.wav', '.mp3') or not path.is_file():
            raise HTTPException(404, 'Không tìm thấy audio.')
        return FileResponse(path)

    @app.get('/api/jobs/{job_id}/output')
    def output(job_id: str):
        j = job_or_404(job_id)
        path = job_dir(job_id) / 'output.mp4'
        if j['status'] != 'done' or not path.exists():
            raise HTTPException(409, 'Video chưa hoàn tất hoặc cần xuất lại.')
        return FileResponse(path, media_type='video/mp4', filename=f"{j['title']}.mp4")

    @app.get('/api/jobs/{job_id}/download.zip')
    def download_zip(job_id: str):
        j = job_or_404(job_id)
        folder = job_dir(job_id)
        if j['status'] != 'done' or not (folder / 'output.mp4').exists():
            raise HTTPException(409, 'Video chưa hoàn tất.')
        dest = folder / 'download.zip'
        with zipfile.ZipFile(dest, 'w', zipfile.ZIP_STORED) as archive:
            current_parts = [contained(folder, p['path']) for p in read_json(folder / 'part-outputs.json') if p.get('path')]
            paths = [folder / 'output.mp4', folder / 'cues.json', folder / 'captions.ass'] + current_parts
            for path in dict.fromkeys(paths):
                if path.is_file():
                    archive.write(path, path.relative_to(folder).as_posix())
        return FileResponse(dest, filename=f"{j['title']}.zip")

    @app.get('/api/samples')
    def samples():
        downloads = Path.home() / 'Downloads'
        return [dict(id=k, title=v[0], filename=v[1], mode=v[2], duration=60) for k, v in SAMPLE_FILES.items() if (downloads / v[1]).is_file()]

    @app.post('/api/samples/{sample_id}', status_code=201)
    def import_sample(sample_id: str):
        if sample_id not in SAMPLE_FILES:
            raise HTTPException(404, 'Không có video mẫu này.')
        title, filename, mode = SAMPLE_FILES[sample_id]
        src = Path.home() / 'Downloads' / filename
        if not src.exists():
            raise HTTPException(404, 'Video mẫu không còn trên máy.')
        j = store.create_job(dict(title=title, filename=filename, mode=mode, rights_confirmed=True))
        folder = settings.jobs_dir / j['id']
        folder.mkdir()
        dest = folder / 'source.mp4'
        try:
            run([settings.ffmpeg, '-v', 'error', '-y', '-i', src, '-t', '60', '-c', 'copy', dest], 120)
            meta = probe(dest, settings)
            # Copy-mux includes the final packet; cue bounds use its measured duration.
            meta['duration'] = min(meta['duration'], 60)
            full = settings.root / 'bench/runs/20261027/full'
            cs = read_json(full / f'{sample_id}-full-cues.json')
            cues = [dict(id=str(i), start=c['s'], end=min(c['e'], meta['duration']), speaker=c['speaker'], original=c.get('zh', ''), text=c['text'], status='pending') for i, c in enumerate(cs) if c['s'] < meta['duration'] - .5]
            atomic_json(folder / 'cues.json', cues)
            box = read_json(full / f'{sample_id}-subbox.json', {})
            regions = []
            if box.get('segs'):
                visible = [b for b in box['segs'] if b['s'] < meta['duration'] and b['e'] > 0]
                if visible:
                    x0, y0 = min(b['x0'] for b in visible), min(b['y0'] for b in visible)
                    x1, y1 = max(b['x1'] for b in visible), max(b['y1'] for b in visible)
                    regions.append(dict(id='subtitle', kind='subtitle', x=x0, y=y0, width=x1-x0, height=y1-y0, start=0, end=meta['duration'], enabled=True, text='', translation=''))
            for i, track in enumerate(read_json(full / f'{sample_id}-tracks.json')):
                kind = track.get('kind')
                watermark = track.get('text') == '黑皮电影'
                translation = '(Con trai tinh tế được cộng điểm)' if track.get('text') == '（细心的男生很加分）' else ''
                if kind != 'static' and not watermark and not translation:
                    continue
                if track['y0'] > .9 * meta['height'] and not watermark:
                    continue
                if kind != 'static' and not watermark and (track['s'] >= meta['duration'] or track['e'] <= 0):
                    continue
                regions.append(dict(id=f'region-{i}', kind='static' if kind == 'static' or watermark else 'transient',
                                    x=track['x0'], y=track['y0'], width=track['x1']-track['x0'], height=track['y1']-track['y0'],
                                    start=0 if kind == 'static' or watermark else max(0,track['s']), end=meta['duration'] if kind == 'static' or watermark else min(meta['duration'],track['e']),
                                    enabled=True, text=track.get('text', ''), translation=translation))
            atomic_json(folder / 'regions.json', regions)
            atomic_json(folder / 'parts.json', [dict(id='1', title='Phần 1', start=0, end=meta['duration'])])
            j = store.update_job(j['id'], source_path=str(dest), status='awaiting_review', stage='awaiting_review', progress=45, cue_count=len(cues),
                                 sample_fixture=sample_id, warnings=['Bản dịch mẫu đã hiệu đính từ bài thử cũ; chưa phải dịch tự động.'], **meta)
            save_job_file(j)
            poster(dest, folder / 'poster.jpg', settings)
        except Exception as e:
            store.update_job(j['id'], status='failed', error=str(e))
            raise HTTPException(400, str(e))
        store.event(j['id'], 'awaiting_review', 'Đã nhập video mẫu và bản dịch cũ để duyệt.', 45)
        return public_job(j)

    @app.get('/api/voices')
    def list_voices():
        return [public_voice(v) for v in all_voices(settings)]

    @app.get('/api/voices/{voice_id}/sample')
    def sample_voice(voice_id: str):
        v = get_voice(settings, voice_id)
        if not v:
            raise HTTPException(404, 'Không tìm thấy giọng.')
        return FileResponse(v['ref_audio'])

    @app.post('/api/voices', status_code=201)
    async def upload_voice(file: UploadFile = File(...), name: str = Form(...), ref_text: str = Form(''),
                           gender: Literal['male','female','other'] = Form('other'), source: str = Form('uploaded'), consent: bool = Form(False)):
        if not consent:
            raise HTTPException(400, 'Cần xác nhận có quyền sử dụng giọng này.')
        if not name.strip() or len(name) > 100 or len(ref_text) > 20000:
            raise HTTPException(422, 'Tên hoặc câu gốc không hợp lệ.')
        suffix = Path(file.filename or '').suffix.lower()
        if suffix not in ('.wav', '.mp3', '.m4a', '.flac', '.ogg', '.webm'):
            raise HTTPException(400, 'Định dạng âm thanh không hỗ trợ.')
        vid = 'user-' + uuid.uuid4().hex
        folder = settings.data_dir / 'voices' / vid
        folder.mkdir()
        original = folder / ('original' + suffix)
        try:
            await save_upload(file, original, 20 * 1024 * 1024)
            quality = check_audio(original, settings)
            run([settings.ffmpeg, '-v', 'error', '-y', '-i', original, '-t', '15', '-ac', '1', '-ar', '48000', folder / 'ref.wav'])
        except (ValueError, OSError) as e:
            raise HTTPException(400, str(e))
        voice = dict(id=vid, name=name.strip(), gender=gender, ref_text=ref_text.strip(), style=[], source='recorded' if source=='recorded' else 'uploaded',
                     commercialOk=None, consent=True, status='draft', quality=quality, ref_audio=str(folder / 'ref.wav'), original_path=str(original),
                     warnings=['Nghe và sửa câu gốc cho khớp đoạn mẫu. Chưa kiểm tra ASR hoặc chất lượng giọng sinh ra.'])
        if quality['duration'] > 15:
            voice['warnings'].append('File dài: hiện lấy 15 giây đầu. Hãy dùng đoạn mẫu sạch 6–15 giây với câu gốc tương ứng.')
        atomic_json(folder / 'voice.json', voice)
        voice['sample_url'] = f'/api/voices/{vid}/sample'
        return public_voice(voice)

    @app.put('/api/voices/{voice_id}')
    def update_voice(voice_id: str, body: VoiceUpdate):
        v = get_voice(settings, voice_id)
        if not v:
            raise HTTPException(404, 'Không tìm thấy giọng.')
        if v['source'] == 'system':
            raise HTTPException(409, 'Giọng hệ thống chỉ đọc.')
        v.update(body.model_dump(exclude_none=True))
        atomic_json(settings.data_dir / 'voices' / voice_id / 'voice.json', v)
        return public_voice(v)

    @app.post('/api/voices/{voice_id}/check')
    def check_voice(voice_id: str):
        v = get_voice(settings, voice_id)
        if not v:
            raise HTTPException(404, 'Không tìm thấy giọng.')
        try:
            v['quality'] = check_audio(Path(v['ref_audio']), settings)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if v['source'] != 'system':
            atomic_json(settings.data_dir / 'voices' / voice_id / 'voice.json', v)
        return public_voice(v)

    @app.delete('/api/voices/{voice_id}', status_code=204)
    def delete_voice(voice_id: str):
        v = get_voice(settings, voice_id)
        if not v:
            raise HTTPException(404, 'Không tìm thấy giọng.')
        if v['source'] == 'system':
            raise HTTPException(409, 'Không xóa giọng hệ thống.')
        if any(j.get('voice_id') == voice_id and j['status'] in BUSY for j in store.list_jobs()):
            raise HTTPException(409, 'Giọng đang được dùng bởi tác vụ đang chạy.')
        folder = contained(settings.data_dir / 'voices', voice_id)
        # Soft-delete preserves the user's recording for recovery.
        target = settings.data_dir / 'voices' / ('deleted-' + voice_id)
        folder.rename(target)
        return None

    @app.get('/api/voice-scripts')
    def scripts():
        return [dict(id='1',style='Kể chuyện',text='Buổi chiều hôm ấy, gió thổi nhẹ qua cánh đồng lúa chín vàng. Cậu bé ngồi bên hiên nhà, lặng lẽ nhìn những đám mây trôi về phía núi xa.'),
                dict(id='2',style='Review phim',text='Bộ phim mở đầu bằng một vụ mất tích bí ẩn giữa đêm mưa. Nhân vật chính buộc phải lần theo từng manh mối nhỏ, và càng đi sâu, anh càng nhận ra sự thật đáng sợ hơn mình tưởng.')]

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return JSONResponse({'detail': str(exc)}, 422)

    install_routes(app,settings,store,public_job,writable,save_upload)

    dist = settings.root / 'frontend/dist'
    if dist.exists():
        app.mount('/', StaticFiles(directory=dist, html=True), name='frontend')
    return app


app = create_app()
