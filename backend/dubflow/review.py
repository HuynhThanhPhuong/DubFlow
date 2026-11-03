"""Source provenance and revision-bound human review, without model imports."""
from datetime import datetime, timezone
from pathlib import Path
import math
import re
import uuid
import threading

_SAVE_LOCK=threading.RLock()

if __package__:
    from .pipeline import read, write, cache_key, file_hash
    from .subtitle_style import overflows
    from .textcheck import needs_translation, screen_text_noise
else:
    from pipeline import read, write, cache_key, file_hash
    from subtitle_style import overflows
    from textcheck import needs_translation, screen_text_noise

STATE_FIELDS = ('characters', 'assignments', 'address_rules', 'scene_context', 'omissions')
VOLATILE = {'status','asr_edits','take_url','take_path','path','delay','overrun'}


def stamp():
    return datetime.now(timezone.utc).isoformat()


def content(cues):
    return [{k:v for k,v in c.items() if k not in VOLATILE} for c in cues]


def load_state(folder):
    with _SAVE_LOCK:
        return _load_state(folder)


def _load_state(folder):
    folder=Path(folder)
    state=read(folder/'review-state.json')
    if state is None:
        job=read(folder/'job.json',{})
        path=Path(job['source_path']) if job.get('source_path') else None
        if path is not None and not path.is_absolute():path=folder/path
        state=dict(version=1, revision=0, source_cues=content(read(folder/'cues.json',[])),
                   characters=[], assignments={}, address_rules=[], scene_context='', omissions={},
                   resolutions={}, approval=None,source_video_sha256=file_hash(path) if path and path.is_file() else None)
        write(folder/'review-state.json',state)
    cues=read(folder/'cues.json',[])
    known={c['id'] for c in state.get('source_cues',[])}
    # Old region builds used ASR evidence IDs as review source IDs. Only repair
    # this generated-source format; incomplete/manual source mappings still block.
    if ((read(folder/'source-build.json',{}) or {}).get('mode')=='regions' and cues
        and all(c.get('original','').strip() and c.get('source') in ('ocr','ocr+asr','asr') for c in cues)
        and any(set(c.get('source_ids') or [])-known for c in cues)):
        state=_replace_source(folder,cues,state,reason='repair-region-source')
    return state


def replace_source(folder, cues):
    """Publish a newly generated transcript and its review provenance together.

    Displayed OCR lines are source units themselves. ASR IDs are evidence, not
    links to review units (one ASR sentence may span several displayed lines).
    """
    with _SAVE_LOCK:
        return _replace_source(Path(folder),cues,read(Path(folder)/'review-state.json'),reason='rebuild-source')


def _replace_source(folder,cues,previous,reason):
    cues=[dict(c) for c in cues]
    for c in cues:
        if c.get('source_ids') and c['source_ids']!=[c['id']]:
            c['asr_source_ids']=c.get('asr_source_ids') or c['source_ids']
        c['source_ids']=[c['id']]
    state=dict(previous or dict(version=1,revision=0,characters=[],address_rules=[],scene_context='',source_video_sha256=None))
    if previous:
        archive=folder/'review-history';archive.mkdir(exist_ok=True)
        write(archive/f"{reason}-{uuid.uuid4().hex}.json",dict(before=previous,time=stamp()))
    state.update(source_cues=content([dict(c,text='') for c in cues]),source_basis_version=2,
                 revision=state.get('revision',0)+1,assignments={},assignment_basis={},listener_basis={},
                 omissions={},resolutions={},approval=None)
    write(folder/'cues.json',cues)
    write(folder/'review-state.json',state)
    return state


def synthesis_cues(cues, state, automatic=False):
    result=[]
    for cue in cues:
        assignment=state.get('assignments',{}).get(cue['id'],{})
        speaker=assignment.get('speaker_confirmed')
        if automatic and (not speaker or state.get('assignment_basis',{}).get(cue['id'])!=role_basis(cue)):
            candidate=cue.get('speaker')
            if not candidate or candidate in ('unconfirmed','low','high'):
                raise ValueError('Chưa tách rõ giọng ở một số câu. Sửa nhãn Người nói ngay trong Lời dịch rồi xuất lại; không cần bảng duyệt riêng.')
            result.append(dict(cue,speaker=candidate));continue
        if not speaker or not assignment.get('evidence','').strip() or state.get('assignment_basis',{}).get(cue['id'])!=role_basis(cue):
            raise ValueError('Cần xác nhận người nói và căn cứ từng câu trước khi clone. Nhãn cao/thấp không phải nhân vật.')
        result.append(dict(cue,speaker=speaker))
    return result


def role_basis(cue):
    return cache_key(dict({k:cue.get(k) for k in ('id','start','end','speaker','original')},source_ids=cue.get('source_ids') or [cue['id']]))


def current_assignment(cue,state):
    assignment=dict(state.get('assignments',{}).get(cue['id'],{}))
    for field in ('speaker','listener'):
        basis='assignment_basis' if field=='speaker' else 'listener_basis'
        if state.get(basis,{}).get(cue['id'])!=role_basis(cue):
            if assignment.get(field+'_confirmed'):
                assignment[field+'_candidate']=assignment[field+'_confirmed']
                assignment[field+'_confirmed']=None
    return assignment


def translation_dependency(cue, state, cues=None, terminology=''):
    return cache_key(dict(source={k:cue.get(k) for k in ('id','original','start','end','speaker')},
        review={k:state.get(k) for k in STATE_FIELDS},
        speaker_basis=state.get('assignment_basis',{}),listener_basis=state.get('listener_basis',{}),
        nearby_source=[{k:c.get(k) for k in ('id','original','start','end','speaker')} for c in (cues or [])],terminology=terminology or ''))


def imported_links(value, previous):
    matches=[c for c in previous if abs(c['start']-value['start'])<1e-6 and abs(c['end']-value['end'])<1e-6]
    if len(matches)!=1:return []
    return matches[0].get('source_ids') or [matches[0]['id']]


def fingerprint(folder, job, state=None):
    state=state or load_state(folder)
    folder=Path(folder)
    path=Path(job['source_path']) if job.get('source_path') else None
    if path is not None and not path.is_absolute():path=folder/path
    source_identity=[str(path),path.stat().st_size,path.stat().st_mtime_ns] if path and path.is_file() else None
    return cache_key(dict(cues=content(read(folder/'cues.json',[])),
        regions=read(folder/'regions.json',[]), parts=read(folder/'parts.json',[]),
        job={k:job.get(k) for k in ('mode','duration','voice_id','voice_ref','collection_id','review_terms')},
        source=state['source_cues'],source_video=source_identity,review={k:state.get(k) for k in STATE_FIELDS},
        speaker_basis=state.get('assignment_basis',{}),listener_basis=state.get('listener_basis',{})))


def source_evidence(cues, regions):
    """Many-to-many links are candidates, not source corrections or timing truth."""
    links=[]
    for cue in cues:
        nearby=[]
        for r in regions:
            if not r.get('enabled') or r.get('kind')!='subtitle' or not r.get('text','').strip():
                continue
            overlap=max(0,min(cue['end'],r['end'])-max(cue['start'],r['start']))
            if overlap or (r['start']<=cue['end']+.5 and r['end']>=cue['start']-.5):
                nearby.append(dict(region_id=r['id'],text=r['text'],start=r['start'],end=r['end'],overlap=round(overlap,3)))
        if nearby:
            links.append(dict(cue_id=cue['id'], asr_text=cue.get('original',''), candidates=nearby,
                              status='candidate', timing_is_not_alignment=True))
    return links


def quality_report(folder, job, state=None):
    state=state or load_state(folder)
    cues=read(Path(folder)/'cues.json',[])
    regions=read(Path(folder)/'regions.json',[])
    fp=fingerprint(folder,job,state)
    flags=[]
    failed_ids=set(i for i in read(Path(folder)/'translation-failed.json',[]) if isinstance(i,str))
    def flag(code, ids, message, severity='review'):
        key=cache_key([fp,code,ids,message])[:24]
        resolution=state.get('resolutions',{}).get(key)
        flags.append(dict(id=key,code=code,cue_ids=ids,message=message,severity=severity,
                          resolved=bool(resolution and resolution.get('reason','').strip()),resolution=resolution))
    duration=job.get('duration')
    ids=[c.get('id') for c in cues]
    if len(ids)!=len(set(ids)) or any(not i for i in ids):
        flag('CUE_IDS',[], 'ID câu bị trùng hoặc trống.', 'error')
    if not cues:
        flag('NO_CUES',[], 'Chưa có nội dung để xuất.', 'error')
    covered=set()
    known={c['id'] for c in state['source_cues']}
    for c in cues:
        linked=c.get('source_ids') or ([c['id']] if c['id'] in known else [])
        covered.update(linked)
        if set(linked)-known:
            flag('SOURCE_UNKNOWN',[c['id']], 'Liên kết tới ID nguồn không tồn tại.','error')
        s,e=c.get('start'),c.get('end')
        valid=all(isinstance(v,(int,float)) and math.isfinite(v) for v in (s,e)) and 0<=s<e
        if not valid or (duration is not None and e>duration+.05):
            flag('INVALID_TIME',[c['id']], 'Mốc câu không hợp lệ hoặc vượt video.','error')
            continue
        text=c.get('text','').strip()
        if text and c.get('translation_dependency') and c['translation_dependency']!=translation_dependency(c,state,cues,job.get('review_terms','')):
            flag('TRANSLATION_STALE',[c['id']], 'Nguồn, vai hoặc ngữ cảnh đã đổi từ lần sinh bản dịch. Kiểm tra/sửa hoặc xóa lời Việt để dịch lại.')
        if not text:
            flag('MISSING_TRANSLATION',[c['id']], 'Câu chưa có lời Việt.','error')
        if re.search(r'[\u3400-\u9fff]',text):
            flag('LANGUAGE_SUSPECT',[c['id']], 'Lời Việt còn ký tự Trung; kiểm tra ngôn ngữ hoặc tên riêng.')
        elif len(text.split())>=5 and text.isascii() and re.search(r'\b(the|you|your|with|have|this|that|only)\b',text,re.I):
            flag('LANGUAGE_SUSPECT',[c['id']], 'Câu có dấu hiệu là tiếng Anh; cần kiểm tra ngôn ngữ. Đây chỉ là sàng lọc.')
        if c.get('source_mismatch'):
            flag('SOURCE_MISMATCH',[c['id']], 'Chữ trên hình và lời nghe được khác nhau; kiểm tra lời gốc.')
        if c.get('ocr_empty'):
            flag('OCR_EMPTY',[c['id']], 'Không đọc được chữ trên hình; lời gốc tạm lấy từ lời nghe được.')
        if c.get('source_partial'):
            flag('ASR_PARTIAL',[c['id']], 'Có lời nghe được nằm ngoài sub trên hình; kiểm tra có thiếu câu không.')
        source_numbers=re.findall(r'\d+(?:[.,]\d+)?',c.get('original',''))
        target_numbers=re.findall(r'\d+(?:[.,]\d+)?',text)
        if source_numbers!=target_numbers:
            flag('NUMBER_SUSPECT',[c['id']], 'Cách ghi số khác nguồn; kiểm tra chuyển số sang chữ hoặc đổi đơn vị.')
        if text.startswith('?:') or re.match(r'^\s*(?:Translation|Vietnamese|Tiếng Việt)\s*:',text,re.I):
            flag('OUTPUT_METADATA',[c['id']], 'Bản dịch có thể chứa nhãn do model thêm.')
        if e-s<.5 or len(text)/(e-s)>20 or any(len(line)>48 for line in text.splitlines()):
            flag('READABILITY',[c['id']], 'Câu ngắn hoặc khó đọc trong thời lượng hiện tại; ngưỡng chỉ để sàng lọc.')
        if text and job.get('mode')=='vietsub' and job.get('vietsub_cps') and len(text)/(e-s)>float(job['vietsub_cps'])*1.15:
            flag('READ_TOO_FAST',[c['id']], 'Câu Việt dài, khó đọc kịp; nên rút gọn.')
        if text and job.get('mode') in ('tm','dub') and len(text.split())>max(1,math.floor((e-s)*4.5)):
            flag('SPEECH_TOO_LONG',[c['id']], 'Lời Việt dài hơn thời lượng câu; nên rút gọn để giọng đọc vừa thời gian.')
        if not text and c['id'] in failed_ids:
            flag('TRANSLATE_FAILED',[c['id']], 'Chưa dịch được câu này; hãy dịch tay hoặc bấm Dịch tiếp.')
        if text and job.get('width') and job.get('height') and overflows(text,c.get('box'),int(job['width']),int(job['height'])):
            flag('LINES_OVERFLOW',[c['id']], 'Câu quá dài, vượt 2 dòng sub; nên rút gọn lời Việt.')
        assignment=current_assignment(c,state)
        if job.get('mode')=='dub' and (not assignment.get('speaker_confirmed') or state.get('assignment_basis',{}).get(c['id'])!=role_basis(c)):
            flag('SPEAKER_UNCONFIRMED',[c['id']], 'Nhân vật nói chưa chắc chắn; hệ thống cần phân nhóm giọng hoặc sửa nhãn ngay ở Lời dịch.')
        for rule in state.get('address_rules',[]):
            if rule.get('status')!='confirmed' or rule['speaker_id']!=assignment.get('speaker_confirmed') or rule['listener_id']!=assignment.get('listener_confirmed'):
                continue
            if rule.get('start') is not None and c['start']<rule['start']:continue
            if rule.get('end') is not None and c['start']>=rule['end']:continue
            # Surface checks are suspicions only: mentions and quotations need review.
            if re.search(r'\b(bạn|cậu|mày|tao)\b',text,re.I) and not any(v in text.lower() for v in (rule['self_form'].lower(),rule['addressee_form'].lower())):
                flag('ADDRESS_SUSPECT',[c['id']], 'Có từ xưng hô khác quy tắc cặp; kiểm tra ngữ cảnh, không tự thay.')
        if re.search(r'[我你您]|\b(tôi|em|anh|chị|thầy|cô|bạn|cậu)\b',c.get('original','')+' '+text,re.I) and not assignment.get('listener_confirmed'):
            flag('ADDRESS_UNCONFIRMED',[c['id']], 'Máy chưa xác định chắc người nghe/xưng hô; xem lời Việt theo cảnh.')
    for source_id in sorted(known-covered):
        omission=state.get('omissions',{}).get(source_id,'')
        if not omission.strip():flag('SOURCE_MISSING',[source_id], 'Mất liên kết nội dung nguồn; cần mapping tách/gộp hoặc lý do loại.','error')
    ordered=sorted(cues,key=lambda c:c.get('start',0))
    normalize=lambda t:re.sub(r'[\W_]+','',t).lower()
    for i,c in enumerate(ordered):
        if i>=2 and normalize(c.get('original','')) and normalize(c.get('original',''))==normalize(ordered[i-1].get('original',''))==normalize(ordered[i-2].get('original','')):
            flag('REPETITION_SUSPECT',[c['id']], 'Lời gốc lặp qua nhiều đoạn; có thể là ASR lặp hoặc thoại thật. Giữ nguyên để xem lại, không tự xóa.')
    active=[]
    for c in ordered:
        active=[o for o in active if o['end']>c['start']]
        for other in active:
            if other['end']>c['start']:
                if c.get('overlap_group') and c.get('overlap_group')==other.get('overlap_group'):continue
                flag('CUE_OVERLAP',[other['id'],c['id']], 'Hai cue chồng thời gian; xác nhận chồng thoại thật và vị trí hiển thị.')
        active.append(c)
    norm=lambda t:re.sub(r'[\W_]+','',t).lower()
    evidence=source_evidence(cues,regions)
    for link in evidence:
        c=next(c for c in cues if c['id']==link['cue_id'])
        texts={norm(r['text']) for r in link['candidates']}
        if norm(c.get('original','')) not in texts:
            flag('ASR_OCR_CONFLICT',[c['id']], 'ASR và OCR có khác biệt; kiểm cả âm thanh và chữ, không tự chọn nguồn.')
    for r in regions:
        if r.get('enabled') and r.get('kind')=='transient' and needs_translation(r.get('text','')) and not r.get('translation','').strip():
            if screen_text_noise(r,regions):  # an OCR flicker is a hint for the reviewer, never a block
                flag('SCREEN_TEXT_UNTRANSLATED',[], f"Chữ trên hình {r['id']} rất ngắn (dưới nửa giây, tối đa 2 ký tự), có thể là nhiễu OCR; kiểm tra rồi bỏ qua hoặc dịch.")
            else:
                flag('SCREEN_TEXT_UNTRANSLATED',[], f"Chữ trên hình {r['id']} chưa có bản dịch.",'error')
    technical=not any(f['severity']=='error' for f in flags)
    unresolved=[f for f in flags if f['severity']=='review' and not f['resolved']]
    approval=state.get('approval') or {}
    final=technical and not unresolved and approval.get('fingerprint')==fp and bool(approval.get('reviewer'))
    return dict(fingerprint=fp,revision=state['revision'],technical_status='passed' if technical else 'failed',
        review_status='human_reviewed' if final else 'in_review' if state.get('resolutions') else 'unreviewed',
        export_status='final_allowed' if final else 'draft_allowed' if technical else 'blocked',
        draft_allowed=technical,final_allowed=final,flags=flags,source_evidence=evidence,
        coverage=dict(source=len(known),covered=len(known&covered),omitted=len(known-covered),output=len(cues)),
        limitations=['Máy chỉ gắn cờ nghi vấn; không chứng nhận nghĩa hoặc chất lượng giọng.',
                     'Liên kết OCR là ứng viên, chưa phải căn từng từ hoặc lip-sync.'])


def public_state(folder, job):
    state=load_state(folder)
    return dict(state, fingerprint=fingerprint(folder,job,state))


def save_state(folder, job, payload):
    with _SAVE_LOCK:
        return _save_state(folder,job,payload)


def _save_state(folder, job, payload):
    """Optimistic edits. Human approval is explicit and tied to actual content."""
    folder=Path(folder)
    previous=load_state(folder)
    if payload.get('revision')!=previous['revision'] or (payload.get('fingerprint') and payload['fingerprint']!=fingerprint(folder,job,previous)):
        raise ValueError('Nội dung đã thay đổi. Tải lại bảng duyệt trước khi lưu.')
    state=dict(previous)
    for field in STATE_FIELDS+('resolutions',):
        if field in payload:state[field]=payload[field]
    cues={c['id']:c for c in read(folder/'cues.json',[])}
    basis=dict(previous.get('assignment_basis',{}))
    listener_basis=dict(previous.get('listener_basis',{}))
    assignments={cid:dict(a) for cid,a in state.get('assignments',{}).items()}
    for cid,a in assignments.items():
        old=previous.get('assignments',{}).get(cid,{})
        explicit=a.pop('reconfirm',False)
        if cid in cues:
            if explicit or a.get('speaker_confirmed')!=old.get('speaker_confirmed'):basis[cid]=role_basis(cues[cid])
            if explicit or a.get('listener_confirmed')!=old.get('listener_confirmed'):listener_basis[cid]=role_basis(cues[cid])
    state['assignment_basis']={cid:v for cid,v in basis.items() if cid in assignments}
    state['listener_basis']={cid:v for cid,v in listener_basis.items() if cid in assignments}
    state['assignments']=assignments
    state['approval']=None
    report=quality_report(folder,job,state)
    if payload.get('approve_final'):
        if not payload.get('reviewer','').strip():raise ValueError('Cần ghi người duyệt trước khi chốt bản hoàn thiện.')
        if not report['draft_allowed'] or any(not f['resolved'] for f in report['flags'] if f['severity']=='review'):
            raise ValueError('Còn lỗi hoặc cảnh báo chưa được xử lý. Kiểm tra báo cáo trước khi duyệt.')
        state['approval']=dict(fingerprint=report['fingerprint'],reviewer=payload['reviewer'].strip(),time=stamp())
    state['revision']+=1
    history=folder/'review-history';history.mkdir(exist_ok=True)
    write(history/(f"{state['revision']:06}-{uuid.uuid4().hex}.json"),dict(before=previous,after=state,time=stamp()))
    write(folder/'review-state.json',state)
    return public_state(folder,job)


def require_export(folder, job, kind='draft'):
    report=quality_report(folder,job)
    write(Path(folder)/'quality-report.json',report)
    allowed=report['final_allowed'] if kind=='final' else report['draft_allowed']
    if not allowed:
        raise ValueError('Chưa thể xuất bản hoàn thiện: nội dung chưa được duyệt hoặc còn lỗi.' if kind=='final' else 'Chưa thể xuất: còn lỗi dữ liệu hoặc câu chưa dịch. Sửa trực tiếp ở Lời dịch hoặc Tuỳ chỉnh.')
    return report
