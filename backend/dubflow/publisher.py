"""Publish local render artifacts without replacing any existing file."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import unicodedata
from .media import contained, read_json
from .preferences import preferences

class PublishConflict(ValueError):
    pass

SIDECAR_FOLDER = 'Phụ đề và báo cáo'


def legacy_sidecars(job, others):
    """Only recorded flat sidecars paired with this job's MP4 can be retired."""
    if not job.get('export_dir'):
        return []
    directory = Path(job['export_dir']).resolve()
    paths = [Path(p) for p in job.get('exported_paths') or []]
    stems = {p.stem for p in paths if p.suffix.lower() == '.mp4' and p.resolve().parent == directory}
    shared = {Path(p).resolve() for other in others for p in other.get('exported_paths') or []}
    result = []
    for path in paths:
        suffix = next((s for s in ('.review.json', '.srt') if path.name.endswith(s)), None)
        if suffix and path.name[:-len(suffix)] in stems and path.resolve().parent == directory:
            if path.is_file() and not path.is_symlink() and path.resolve() not in shared:
                result.append(path)
    return list(dict.fromkeys(result))


def safe_name(value):
    name=unicodedata.normalize('NFC', str(value))
    name=re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(' .')[:140].rstrip(' .')
    if not name or name in ('.','..'):
        name='Video'
    if re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)',name,re.I):
        name='_'+name
    return name

def render_signature(folder, job, values):
    digest=hashlib.sha256()
    # Publication metadata does not affect content validity.
    digest.update(json.dumps({k:job.get(k) for k in ('mode','voice_id','voice_ref','source_path','export_kind','subtitle_font','subtitle_size','subtitle_italic')},sort_keys=True).encode())
    gains=('background_gain',) if job.get('mode')=='dub' else ('original_gain',)  # each mode's own gain only
    digest.update(json.dumps({k:values[k] for k in ('resolution','blur_original')+gains},sort_keys=True).encode())
    for name in ('cues.json','regions.json','parts.json','manifest.json','review-state.json','output.mp4'):
        path=folder/name
        if path.exists():
            with path.open('rb') as data:
                for chunk in iter(lambda:data.read(1024*1024),b''): digest.update(chunk)
    return digest.hexdigest()

def srt_text(cues):
    def stamp(seconds):
        n=round(float(seconds)*1000)
        return f'{n//3600000:02}:{n//60000%60:02}:{n//1000%60:02},{n%1000:03}'
    return '\n\n'.join(f"{i}\n{stamp(c['start'])} --> {stamp(c['end'])}\n{c.get('text','')}" for i,c in enumerate(cues,1))+'\n'

def publish(store, settings, job_id, *, rendering=False, render_values=None):
    values=preferences(store,settings)
    created=[]
    created_dirs=[]
    retired=[]
    try:
        # Serialize cancel, edits and publication with the same SQLite writer lock.
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT body FROM jobs WHERE id=?',(job_id,)).fetchone()
            job=json.loads(row['body']) if row else None
            folder=contained(settings.jobs_dir,job_id)
            if not job or job['status'] != ('processing' if rendering else 'done') or (folder/'cancel.request').exists():
                raise PublishConflict('Video chưa hoàn tất, đã dừng hoặc cần xuất lại.')
            source=folder/'output.mp4'
            if not source.is_file() or not source.stat().st_size:
                raise PublishConflict('Chưa có video hoàn tất để xuất.')
            if (folder/'review-state.json').exists() or job.get('export_kind'):
                from .review import require_export
                current_collection=store.get_record('collection',job.get('collection_id')) if job.get('collection_id') else None
                from .names import terminology as name_terminology
                try:report=require_export(folder,dict(job,review_terms=name_terminology(job,(current_collection or {}).get('terminology',''))),job.get('export_kind','draft'))
                except ValueError as exc:raise PublishConflict(str(exc)) from None
            if not rendering and (folder/'render-command.json').exists() and read_json(folder/'render-version.json',{}).get('version') != 'transparent-captions-v4':
                raise PublishConflict('Cần kết xuất lại video để áp dụng cách che phụ đề mới.')
            signature=render_signature(folder,job,values | (render_values or {}))
            if not rendering and job.get('render_signature') and signature != job['render_signature']:
                raise PublishConflict('Nội dung hoặc thiết lập đã đổi. Cần kết xuất lại video.')
            root=Path(values['output_dir']).resolve()
            # Exporting into internal media could corrupt source/reference/cache ownership.
            if root.is_relative_to(settings.data_dir.resolve()):
                raise ValueError('Thư mục xuất phải nằm ngoài thư mục dữ liệu nội bộ.')
            dest=root
            collection=store.get_record('collection',job.get('collection_id')) if job.get('collection_id') else None
            if collection and values['organize_by_collection']:
                dest=contained(root,safe_name(collection['name']))
            dest.mkdir(parents=True,exist_ok=True)
            if not dest.resolve().is_relative_to(root):
                raise ValueError('Thư mục xuất không hợp lệ.')
            artifacts=[('.mp4',source)]
            if (folder/'quality-report.json').exists():
                artifacts.append(('.review.json',json.dumps(read_json(folder/'quality-report.json',{}),ensure_ascii=False,indent=2)))
            if values['export_srt']:
                cues=read_json(folder/'cues.json')
                manifest=read_json(folder/'manifest.json',{})
                if job.get('mode') != 'vietsub' and len(manifest.get('lines',[])) == len(cues):
                    cues=[dict(c,start=line['start'],end=line['end']) for c,line in zip(cues,manifest['lines'])]
                artifacts.append(('.srt',srt_text(cues)))
            for i,part in enumerate(read_json(folder/'part-outputs.json')):
                path=contained(folder,part.get('path',''))
                if path==source.resolve():
                    continue
                if path.suffix.lower()!='.mp4' or not path.is_file():
                    raise ValueError('Tệp video phần không hợp lệ.')
                artifacts.append((f' - {i+1:02} {safe_name(part.get("title") or "Phần")[:70]}.mp4',path))
            base=safe_name(job['title']) + (' - ban nhap' if job.get('export_kind')=='draft' else '')
            for number in range(1,100001):
                stem=base if number==1 else f'{base} ({number})'
                targets=[contained(dest if suffix.endswith('.mp4') else contained(dest,SIDECAR_FOLDER),stem+suffix)
                         for suffix,_ in artifacts]
                if any(p.exists() for p in targets):
                    if values['collision']=='ask':
                        raise PublishConflict('Tên tệp đã tồn tại. Đổi tên hoặc chọn đánh số tự động.')
                    continue
                handles=[]
                try:
                    for path in targets:
                        if not path.parent.exists():
                            created_dirs.append(path.parent)
                        path.parent.mkdir(parents=True,exist_ok=True)
                        handles.append(path.open('xb'))
                        created.append(path)
                except FileExistsError:
                    for h in handles: h.close()
                    for path in created: path.unlink(missing_ok=True)
                    created.clear()
                    if values['collision']=='ask':
                        raise PublishConflict('Tên tệp đã tồn tại.')
                    continue
                except OSError:
                    for h in handles: h.close()
                    raise
                try:
                    for handle,(_,artifact) in zip(handles,artifacts):
                        if isinstance(artifact,Path):
                            with artifact.open('rb') as src: shutil.copyfileobj(src,handle)
                        else:
                            handle.write(artifact.encode('utf-8-sig'))
                finally:
                    for h in handles: h.close()
                break
            else:
                raise PublishConflict('Không tìm được tên xuất trống.')
            if (folder/'cancel.request').exists():
                raise PublishConflict('Đã dừng tác vụ trước khi xuất.')
            others=[json.loads(r['body']) for r in db.execute('SELECT body FROM jobs WHERE id != ?',(job_id,))]
            for path in legacy_sidecars(job,others):
                # The child is on the original export's drive, so rollback stays an atomic rename.
                # A process interruption also leaves any preserved sidecars out of the MP4 listing.
                retirement_dir=contained(path.parent,SIDECAR_FOLDER)
                if not retirement_dir.exists():
                    created_dirs.append(retirement_dir)
                retirement_dir.mkdir(parents=True,exist_ok=True)
                # Retain usable sidecars paired with the old MP4 instead of
                # requiring a fallible post-commit deletion of UUID backups.
                suffix = '.review.json' if path.name.endswith('.review.json') else '.srt'
                stem = path.name[:-len(suffix)]
                backup=contained(retirement_dir,path.name)
                number=1
                while backup.exists():
                    backup=contained(retirement_dir,f'{stem} - legacy ({number}){suffix}')
                    number+=1
                path.rename(backup)
                retired.append((path,backup))
            job.update(exported_paths=[str(p) for p in targets],export_dir=str(dest),render_signature=signature)
            db.execute('UPDATE jobs SET body=? WHERE id=?',(json.dumps(job,ensure_ascii=False),job_id))
    except Exception:
        for path,backup in reversed(retired):
            backup.rename(path)
        for path in created: path.unlink(missing_ok=True)
        for directory in reversed(created_dirs):
            try:
                directory.rmdir()
            except OSError:
                pass  # Preserve directories containing another publisher's files.
        raise
    return job
