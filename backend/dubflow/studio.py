"""Studio management routes; no GPU or model runtime imports."""
from pathlib import Path
import threading
import uuid
from fastapi import Body, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError
from .preferences import Preferences, CollectionInput, PROVIDERS, preferences, public_preferences
from .translate_api import LABELS, ProviderError, make_provider
from .native import pick_folder, open_folder
from .publisher import publish, PublishConflict
from .voices import get_voice


def install_routes(app,settings,store,public_job,writable,save_upload):
    dialog_lock=threading.Lock()
    settings_lock=threading.Lock()
    def collection(cid):
        c=store.get_record('collection',cid)
        if not c: raise HTTPException(404,'Không tìm thấy bộ sưu tập.')
        return c
    def public_collection(c):
        jobs=[j for j in store.list_jobs() if j.get('collection_id')==c['id']]
        return dict(c,job_count=len(jobs),done_count=sum(j['status']=='done' for j in jobs))
    def validate_voice(vid):
        if vid and not get_voice(settings,vid): raise HTTPException(422,'Giọng không tồn tại.')

    @app.get('/api/settings')
    def get_settings():
        return public_preferences(preferences(store,settings))

    @app.get('/api/settings/models')
    def settings_models(provider: str):
        if provider not in PROVIDERS: raise HTTPException(422,'Nhà cung cấp dịch không hợp lệ.')
        prefs=preferences(store,settings)
        key=prefs[f'{provider}_api_key']
        if not key.strip(): raise HTTPException(409,f'Chưa nhập key {LABELS[provider]}. Nhập key trong Cài đặt rồi thử lại.')
        try:
            with make_provider(provider,key,prefs[f'{provider}_model'],thinking=prefs['thinking']) as p:
                models=p.list_models()
        except ProviderError as e:
            raise HTTPException(502,str(e).replace(key,'***')) from None
        return dict(models=models)

    @app.put('/api/settings')
    def put_settings(body: dict=Body(...)):
        with settings_lock:
            body=dict(body)
            current=preferences(store,settings)
            for name in PROVIDERS:
                clear=body.pop(f'clear_{name}_key',False)
                if not isinstance(clear,bool): raise HTTPException(422,f'clear_{name}_key phải là boolean.')
                body.pop(f'has_{name}_key',None)
                if clear:
                    body[f'{name}_api_key']=''
                elif body.get(f'{name}_api_key')=='':
                    body.pop(f'{name}_api_key')
            try:
                value=Preferences(**(current | body)).model_dump()
            except ValidationError:
                # Never echo submitted secrets in validation responses.
                raise HTTPException(422,'Thiết lập không hợp lệ. Kiểm tra giá trị và đường dẫn.') from None
            validate_voice(value['default_voice_id'])
            if Path(value['output_dir']).is_relative_to(settings.data_dir.resolve()):
                raise HTTPException(422,'Thư mục xuất phải nằm ngoài dữ liệu nội bộ.')
            store.put_record('settings','main',value)
            return public_preferences(value)

    @app.get('/api/collections')
    def collections():
        return [public_collection(c) for c in store.list_records('collection')]

    @app.post('/api/collections',status_code=201)
    def create_collection(body: CollectionInput):
        validate_voice(body.default_voice_id)
        c=dict(body.model_dump(),id=uuid.uuid4().hex,cover_url=None)
        store.put_record('collection',c['id'],c)
        return public_collection(c)

    @app.get('/api/collections/{cid}')
    def get_collection(cid: str):
        return public_collection(collection(cid))

    @app.put('/api/collections/{cid}')
    def update_collection(cid: str,body: dict=Body(...)):
        c=collection(cid)
        try:
            values=CollectionInput(**({k:c[k] for k in CollectionInput.model_fields}|body)).model_dump()
        except ValidationError:
            raise HTTPException(422,'Thông tin bộ sưu tập không hợp lệ.') from None
        validate_voice(values['default_voice_id'])
        c.update(values)
        store.put_record('collection',cid,c)
        return public_collection(c)

    @app.delete('/api/collections/{cid}',status_code=204)
    def delete_collection(cid: str):
        collection(cid)
        store.unlink_collection(cid)

    @app.post('/api/collections/{cid}/cover')
    async def cover(cid: str,file: UploadFile=File(...)):
        c=collection(cid)
        folder=settings.data_dir/'covers'; folder.mkdir(exist_ok=True)
        dest=folder/(uuid.uuid4().hex+'.image')
        await save_upload(file,dest,8*1024*1024)
        header=dest.read_bytes()[:16]
        if not (header.startswith(b'\x89PNG\r\n\x1a\n') or header.startswith(b'\xff\xd8\xff') or (header[:4]==b'RIFF' and header[8:12]==b'WEBP')):
            dest.unlink(missing_ok=True)
            raise HTTPException(422,'Ảnh bìa phải là PNG, JPEG hoặc WebP.')
        c['cover_file']=dest.name
        c['cover_url']=f'/api/collections/{cid}/cover'
        store.put_record('collection',cid,c)
        return public_collection(c)

    @app.get('/api/collections/{cid}/cover')
    def get_cover(cid: str):
        c=collection(cid)
        if not c.get('cover_file'): raise HTTPException(404,'Chưa có ảnh bìa.')
        dest=settings.data_dir/'covers'/Path(c['cover_file']).name
        header=dest.read_bytes()[:16]
        media='image/png' if header.startswith(b'\x89PNG') else 'image/jpeg' if header.startswith(b'\xff\xd8') else 'image/webp'
        return FileResponse(dest,media_type=media)

    @app.post('/api/system/pick-folder')
    def system_pick(body: dict | None=Body(default=None)):
        initial=(body or {}).get('initial_dir')
        if initial is not None and (not isinstance(initial,str) or not Path(initial).is_absolute() or '\x00' in initial):
            raise HTTPException(422,'Thư mục ban đầu không hợp lệ.')
        if initial:
            current=Path(initial)
            while not current.is_dir() and current.parent != current:
                current=current.parent
            initial=str(current) if current.is_dir() else None
        if not dialog_lock.acquire(blocking=False): raise HTTPException(409,'Hộp chọn thư mục đang mở.')
        try:
            return {'path':pick_folder(initial)}
        finally:
            dialog_lock.release()

    @app.post('/api/system/open-folder')
    def system_open(body: dict | None=Body(default=None)):
        body=body or {}
        if set(body)-{'job_id'}: raise HTTPException(422,'Chỉ chấp nhận job_id.')
        root=Path(preferences(store,settings)['output_dir']).resolve()
        if body.get('job_id'):
            job=writable(body['job_id'])
            if not job.get('export_dir') or not job.get('exported_paths'): raise HTTPException(409,'Dự án chưa được xuất ra thư mục.')
            dest=Path(job['export_dir']).resolve()
            # Exact recorded folder only; arbitrary client paths are never accepted.
            if any(Path(p).resolve().parent!=dest for p in job['exported_paths']):
                raise HTTPException(422,'Thư mục xuất không hợp lệ.')
        else:
            dest=root
            dest.mkdir(parents=True,exist_ok=True)
        open_folder(dest)
        return {'path':str(dest)}

    @app.post('/api/jobs/{job_id}/publish')
    def publish_job(job_id: str):
        writable(job_id)
        try:
            job=publish(store,settings,job_id)
        except PublishConflict as exc:
            raise HTTPException(409,str(exc)) from None
        if preferences(store,settings)['open_after_export']:
            try: open_folder(job['export_dir'])
            except ValueError as exc:
                job=store.update_job(job_id,warnings=job.get('warnings',[])+[str(exc)])
        return public_job(job)
