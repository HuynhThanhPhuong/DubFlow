"""Gom mọi lỗi hiện có của một video cho tab "Lỗi" trong popup Chi tiết (đọc file trong thư mục job, không gọi mạng)."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

IMPORT_FILE = 'srt-import-issues.json'
DISMISS_FILE = 'errors-dismissed.json'
FAILED_FILE = 'translation-failed.json'
LOG_FILE = 'last-error.log'

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

    def add(key, kind, step, time, message, cue_id=None, actions=()):
        if key in skip:
            return
        items.append(dict(key=key, kind=kind, step=step, time=time, cue_id=cue_id, cue_number=number.get(cue_id),
                          message=message, actions=list(actions) + ['dismiss']))

    failed_time = _iso(folder / FAILED_FILE)
    for cid in _read(folder / FAILED_FILE, []):
        if cid in number and not text_of.get(cid) and not str(cid).startswith('region:'):
            add(f'tr:{cid}', 'translate', 'Dịch', failed_time,
                'Gemini không trả bản dịch hợp lệ cho câu này (lỗi tạm thời, hết hạn mức hoặc kết quả hỏng).',
                cid, ['jump', 'edit', 'retry'])
    imp = _read(folder / IMPORT_FILE, {})
    if imp:
        when = imp.get('time') or _iso(folder / IMPORT_FILE)
        for cid in imp.get('empty', []):
            if cid in number and not text_of.get(cid):
                add(f'srt-empty:{cid}', 'srt', 'Nhập SRT', when, 'Câu chưa có bản dịch sau lần nhập SRT gần nhất.',
                    cid, ['jump', 'edit', 'retry'])
        for b in imp.get('skipped', []):
            tag = hashlib.sha1(f"{b.get('number')}|{b.get('text')}".encode('utf-8')).hexdigest()[:8]
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
        add(f"block:{r.get('code')}", 'blocking', 'Xuất', datetime.now(timezone.utc).isoformat(), r.get('message', ''),
            ids[0] if ids else None, ['jump'] if ids else [])
    return dict(count=len(items), items=items)
