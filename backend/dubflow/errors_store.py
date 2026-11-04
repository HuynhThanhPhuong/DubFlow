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

    def add(key, kind, step, time, message, cue_id=None, actions=(), **extra):
        if key in skip:
            return
        items.append(dict(key=key, kind=kind, step=step, time=time, cue_id=cue_id, cue_number=number.get(cue_id),
                          severity=extra.pop('severity', 'warn' if kind == 'warning' else 'error'),
                          message=message, actions=list(actions) + ['dismiss'], **extra))

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
            add(f'srt-skip:{tag}', 'srt', 'Nhập SRT', when,
                f'{label} không khớp câu nào nên bị bỏ qua: "{b.get("text", "")}"', None, ['delete_block'])
    if (folder / LOG_FILE).exists() and job.get('status') in ('error', 'failed'):
        stage = str(job.get('stage') or '')
        step = _STEP_BY_STAGE.get(stage, 'Phân tích')
        mtime = _iso(folder / LOG_FILE)
        add(f'log:{mtime}', 'task', step, mtime,
            job.get('error') or 'Tác vụ gần nhất bị lỗi. Xem last-error.log trong thư mục dự án.')
    for w in job.get('warnings') or []:
        if isinstance(w, str) and w.strip():
            add('warn:' + hashlib.sha1(w.encode('utf-8')).hexdigest()[:8], 'warning', 'Phân tích',
                job.get('updated_at') or _iso(folder / 'cues.json'), w.strip())
    for r in (report or {}).get('reasons', []):
        if r.get('code') == 'MISSING_TRANSLATION':
            continue
        ids = [i for i in r.get('cue_ids', []) if i in number]
        add(f"block:{r.get('code')}:{_tag(r.get('message', ''))}", 'blocking', 'Xuất', datetime.now(timezone.utc).isoformat(), r.get('message', ''),
            ids[0] if ids else None, ['jump'] if ids else [])
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
    return dict(count=len(items), items=items, cue_flags=flags)


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
