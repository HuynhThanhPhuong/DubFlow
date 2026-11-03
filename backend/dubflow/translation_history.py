"""Durable translation snapshots owned by one job; never store provider credentials."""
from datetime import datetime, timezone
from pathlib import Path
import re
import threading
import unicodedata
import uuid

from .pipeline import read, write

_LOCK = threading.RLock()
_ID = re.compile(r'^[a-f0-9]{32}$')
FIELDS = ('start', 'end', 'original', 'text')
META = ('provider', 'model', 'requests', 'input_tokens', 'output_tokens', 'cost_usd', 'error')


def save_snapshot(folder, cues, *, source, status='done', metadata=None, snapshot_id=None):
    with _LOCK:
        sid = snapshot_id or uuid.uuid4().hex
        if not _ID.fullmatch(sid):
            raise ValueError('Mã bản dịch không hợp lệ.')
        directory = Path(folder)/'translation-history';directory.mkdir(exist_ok=True)
        rows = [{k: c.get(k, '' if k in ('original','text') else 0) for k in FIELDS} for c in cues]
        old = read(directory/(sid+'.json'), {}) or {}
        value = dict(id=sid, created_at=old.get('created_at') or datetime.now(timezone.utc).isoformat(),
                     source=source, status=status, cue_count=sum(bool(c['text'].strip()) for c in rows),
                     total_count=len(rows), cues=rows,
                     **{k:v for k,v in (metadata or {}).items() if k in META})
        write(directory/(sid+'.json'),value)
        return value


def get_snapshot(folder, sid):
    if not _ID.fullmatch(sid):
        return None
    value=read(Path(folder)/'translation-history'/(sid+'.json'))
    return value if isinstance(value,dict) and value.get('id')==sid else None


def list_snapshots(folder):
    rows=[]
    for path in (Path(folder)/'translation-history').glob('*.json'):
        value=get_snapshot(folder,path.stem)
        if value:
            rows.append({k:v for k,v in value.items() if k!='cues'})
    return sorted(rows,key=lambda v:(v['created_at'],v['id']),reverse=True)


def _original(text):
    return re.sub(r'\s+','',unicodedata.normalize('NFKC',text or '')).casefold()


def match_cues(saved, current):
    """One-to-one, text AND time. Never guess across repeated or distant dialogue."""
    matched=[];used=set();unmatched=0
    for old in saved:
        if not old.get('text','').strip():
            continue
        candidates=[]
        for i,c in enumerate(current):
            if i in used or not _original(old.get('original')) or _original(old.get('original'))!=_original(c.get('original')):
                continue
            ds,de=abs(old['start']-c['start']),abs(old['end']-c['end'])
            if ds<=.75 and de<=.75:
                candidates.append((ds+de,i))
        candidates.sort()
        if not candidates or (len(candidates)>1 and abs(candidates[0][0]-candidates[1][0])<1e-6):
            unmatched+=1;continue
        index=candidates[0][1];used.add(index)
        matched.append((index,old))
    return matched,unmatched
