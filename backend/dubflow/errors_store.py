"""Gom mọi lỗi hiện có của một video cho tab "Lỗi" trong popup Chi tiết (đọc file trong thư mục job, không gọi mạng)."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from . import source_audit

IMPORT_FILE = 'srt-import-issues.json'
DISMISS_FILE = 'errors-dismissed.json'
FAILED_FILE = 'translation-failed.json'
LOG_FILE = 'last-error.log'
BATCH_FILE = 'translation-failed-batches.json'
DELETABLE = ('NO_CJK', 'NEAR_DUPLICATE', 'FRAGMENT')

_STEP_BY_STAGE = {'translating': 'Dịch', 'rendering': 'Xuất', 'exporting': 'Xuất', 'synthesizing': 'Giọng'}


def _read(path: Path, default):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def _write(path: Path, value) -> None:
    path = Path(path)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def _tag(*parts) -> str:
    return hashlib.sha1('|'.join(str(p) for p in parts).encode('utf-8')).hexdigest()[:8]


def _iso(path: Path) -> str:
    try:
        return datetime.fromtimestamp(Path(path).stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        return datetime.now(timezone.utc).isoformat()


def save_import_issues(folder, empty: list[dict], skipped: list[dict]) -> None:
    """Ghi vấn đề của lần nhập SRT gần nhất (thay thế lần trước)."""
    _write(Path(folder) / IMPORT_FILE, dict(
        time=datetime.now(timezone.utc).isoformat(),
        empty=[e['id'] for e in empty],
        skipped=[dict(number=b.get('number'), text=str(b.get('text', ''))[:80], start=b.get('start'), end=b.get('end'))
                 for b in skipped]))


def dismissed(folder) -> set[str]:
    return {k for k in _read(Path(folder) / DISMISS_FILE, []) if isinstance(k, str)}


def dismiss(folder, key: str) -> None:
    keys = sorted(dismissed(folder) | {key})
    _write(Path(folder) / DISMISS_FILE, keys)


def collect(folder, job: dict, report: dict | None = None) -> dict:
    folder = Path(folder)
    cues = _read(folder / 'cues.json', [])
    number = {c.get('id'): i for i, c in enumerate(cues, 1)}
    text_of = {c.get('id'): str(c.get('text') or '').strip() for c in cues}
    skip = dismissed(folder)
    items: list[dict] = []
    activity: list[dict] = []

    def add(key, kind, step, time, message, cue_id=None, actions=(), **extra):
        if key in skip:
            return
        items.append(dict(key=key, kind=kind, step=step, time=time, cue_id=cue_id, cue_number=number.get(cue_id),
                          severity=extra.pop('severity', 'warn' if kind == 'warning' else 'error'),
                          message=message, actions=list(actions) + ['dismiss'], **extra))

    def note(time, message):
        activity.append(dict(t=time,msg=message))

    def recovery(message, step, code=None):
        if 'Hãy' in message or 'hãy' in message:
            return message
        instructions={'NO_CUES':'Hãy chọn Phân tích lại hoặc nhập phụ đề để tạo danh sách câu.',
                      'SCREEN_TEXT_UNTRANSLATED':'Hãy mở Tuỳ chỉnh để dịch hoặc tắt vùng chữ này rồi xuất lại.',
                      'CUE_IDS':'Hãy tải lại danh sách câu hoặc chọn Phân tích lại để tạo lại mã câu.'}
        instruction=instructions.get(code) or {'Xuất':'Hãy kiểm tra tệp nguồn và thư mục xuất trong Tuỳ chỉnh rồi xuất lại.',
                     'Dịch':'Hãy kiểm tra cài đặt dịch rồi bấm Dịch tiếp.',
                     'Giọng':'Hãy kiểm tra giọng đã chọn rồi xử lý lại.'}.get(step,'Hãy kiểm tra tệp nguồn rồi chọn Phân tích lại.')
        return message.rstrip()+' '+instruction

    failed_time = _iso(folder / FAILED_FILE)
    for cid in _read(folder / FAILED_FILE, []):
        if cid in number and not text_of.get(cid) and not str(cid).startswith('region:'):
            add(f'tr:{cid}:{_tag(failed_time)}', 'translate', 'Dịch', failed_time,
                'Gemini không trả bản dịch hợp lệ cho câu này (lỗi tạm thời, hết hạn mức hoặc kết quả hỏng).',
                cid, ['jump', 'edit', 'retry'])
    for rec in _read(folder / BATCH_FILE, []):
        ids = [i for i in rec.get('cue_ids', []) if i in number and not text_of.get(i)]
        if not ids:
            continue
        tag = _tag('|'.join(ids), rec.get('time'))  # a later failure of the same cues is a new error
        label = f"Lô {rec.get('batch')}/{rec.get('batches')}" if rec.get('batch') else 'Lô'
        add(f'trb:{tag}', 'translate', 'Dịch', rec.get('time') or failed_time,
            f"{label}: {len(ids)} câu chưa được dịch. Lý do: {rec.get('reason', 'kết quả hỏng')}.",
            ids[0], ['jump', 'retry_batch'], cue_ids=ids, batch=rec.get('batch'), batches=rec.get('batches'),
            reason=rec.get('reason'))
    imp = _read(folder / IMPORT_FILE, {})
    if imp:
        when = imp.get('time') or _iso(folder / IMPORT_FILE)
        for cid in imp.get('empty', []):
            if cid in number and not text_of.get(cid):
                add(f'srt-empty:{_tag(when)}:{cid}', 'srt', 'Nhập SRT', when, 'Câu chưa có bản dịch sau lần nhập SRT gần nhất.',
                    cid, ['jump', 'edit', 'retry'])
        for b in imp.get('skipped', []):
            tag = _tag(b.get('number'), b.get('text'), when)
            label = f"Khối {b['number']}" if b.get('number') is not None else 'Khối'
            if f'srt-skip:{tag}' not in skip:
                note(when,f'{label} không khớp câu nào nên bị bỏ qua: "{b.get("text", "")}"')
    if job.get('status') in ('error', 'failed'):
        stage = str(job.get('stage') or '')
        step = _STEP_BY_STAGE.get(stage, 'Phân tích')
        mtime = _iso(folder / LOG_FILE) if (folder / LOG_FILE).exists() else job.get('updated_at') or _iso(folder/'cues.json')
        add(f'log:{mtime}', 'task', step, mtime,
            recovery(job.get('error') or 'Tác vụ gần nhất bị lỗi.',step))
    for w in job.get('warnings') or []:
        if isinstance(w, str) and w.strip():
            note(job.get('updated_at') or _iso(folder/'cues.json'),w.strip())
    quality_codes=set()
    for f in (report or {}).get('flags',[]):
        ids=[i for i in f.get('cue_ids',[]) if i in number]
        if not ids or f.get('resolved'):
            continue
        code=f.get('code')
        quality_codes.add(code)
        if code=='MISSING_TRANSLATION':
            continue  # all empty lines receive the same edit/retry controls below
        add(f"quality:{f.get('id') or _tag(code,ids,f.get('message'))}",'blocking' if f.get('severity')=='error' else 'audit',
            'Xuất',_iso(folder/'cues.json'),f.get('message',''),ids[0],['jump'],
            severity='error' if f.get('severity')=='error' else 'warn',code=code,cue_ids=ids)
    for r in (report or {}).get('reasons', []):
        if r.get('code') == 'MISSING_TRANSLATION':
            continue
        ids = [i for i in r.get('cue_ids', []) if i in number]
        if ids and r.get('code') in quality_codes:
            continue
        add(f"block:{r.get('code')}:{_tag(r.get('message', ''))}", 'blocking', 'Xuất', _iso(folder/'cues.json'), recovery(r.get('message', ''),'Xuất',r.get('code')),
            ids[0] if ids else None, ['jump'] if ids else [])
    for cid in number:
        if not text_of[cid] and not any(i['cue_id']==cid and 'edit' in i['actions'] for i in items):
            add(f'empty:{cid}','translate','Dịch',_iso(folder/'cues.json'),'Câu chưa có lời Việt. Hãy nhập bản dịch hoặc bấm Dịch lại.',cid,['jump','edit','retry'])
    flags: dict[str, list[dict]] = {}
    by_id = {c.get('id'): c for c in cues}
    try:
        findings = source_audit.audit_cues(cues, job.get('duration') or 0)
    except Exception:  # noqa: BLE001 - the audit must never break the error list
        findings = []
    when = _iso(folder / 'cues.json')
    for f in findings:
        shown = [by_id[i] for i in f['cue_ids'] if i in by_id]
        # the content is part of the key: dismissing a finding must not hide another one that reuses the same cue ids
        key = f"audit:{f['code']}:{','.join(str(i) for i in f['cue_ids'])}:{_tag(*[(c.get('original'), c.get('start'), c.get('end')) for c in shown])}"
        if key in skip:
            continue
        ids = [i for i in f['cue_ids'] if i in number]
        for i in ids:
            flags.setdefault(i, []).append(dict(code=f['code'], severity=f['severity'], message=f['message_vi']))
        delete_ids = _extra_cues(f, by_id) if f['code'] in DELETABLE else []
        add(key, 'audit', 'Phân tích', when, f['message_vi'], ids[0] if ids else None,
            (['jump'] if ids else []) + (['delete_cues'] if delete_ids else []),
            severity=f['severity'], code=f['code'], cue_ids=ids, delete_ids=delete_ids)
    return dict(count=len(items), items=items, cue_flags=flags, activity=activity)


def _extra_cues(finding: dict, by_id: dict) -> list[str]:
    """Which cue of a finding is the surplus one: the only cue (NO_CJK / FRAGMENT) or, of a duplicate pair, the ASR one,
    else the one with the shorter source text (the later one on a tie)."""
    ids = [i for i in finding['cue_ids'] if i in by_id]
    if len(ids) <= 1:
        return ids
    a, b = by_id[ids[0]], by_id[ids[1]]
    if (a.get('source') == 'asr') != (b.get('source') == 'asr'):
        return [ids[0] if a.get('source') == 'asr' else ids[1]]
    return [ids[0] if len(str(a.get('original') or '')) < len(str(b.get('original') or '')) else ids[1]]
