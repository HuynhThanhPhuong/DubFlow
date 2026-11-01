"""Cầu nối giữa thư mục job (cues.json, regions.json) và lõi dịch API.

Dùng chung cho API (ước tính, tạo yêu cầu) và worker (chạy dịch trong tiến trình).
Không bao giờ ghi key ra file hay thông điệp.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from .translate_api import LABELS, ProviderError, make_provider
from .textcheck import needs_translation
from .translate_job import Item, RateLimiter, plan_translation, run_translation

REQUEST_FILE = 'translate-request.json'
USAGE_FILE = 'translation-usage.json'
FAILED_FILE = 'translation-failed.json'
RATE_FILE = 'translation-rate.json'
SCOPES = ('missing', 'all')
PREF_KEYS = ('rate_rpm', 'rate_rpd', 'price_in_per_mtok',
             'price_out_per_mtok', 'cost_cap_usd', 'vietsub_cps', 'max_output_tokens', 'max_input_tokens', 'thinking')


def _get(values, key):
    return values[key] if isinstance(values, dict) else getattr(values, key)


def prefs_ns(values) -> SimpleNamespace:
    return SimpleNamespace(tier=_get(values, 'translation_tier'), **{k: _get(values, k) for k in PREF_KEYS})


def selected(values) -> tuple[str, str, str]:
    """(provider, key, model) của provider đang chọn."""
    name = _get(values, 'translation_provider')
    return name, _get(values, f'{name}_api_key'), _get(values, f'{name}_model')


def scrub(text: str, key: str) -> str:
    return text.replace(key, '***') if key and len(key) >= 4 else text


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return default


def _write(path: Path, value) -> None:
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def collect_items(folder: Path, scope: str) -> list[Item]:
    """Câu và chữ trên hình cần dịch. 'missing' bỏ qua mọi chỗ đã có lời Việt."""
    items: list[Item] = []
    for c in _read(folder / 'cues.json', []):
        zh = str(c.get('original') or '').strip()
        if zh and (scope == 'all' or not str(c.get('text') or '').strip()):
            items.append(Item(str(c['id']), zh, float(c['start']), float(c['end']), str(c.get('speaker') or ''), 'cue'))
    for r in _read(folder / 'regions.json', []):
        if not (r.get('enabled') and r.get('kind') == 'transient' and str(r.get('text') or '').strip() and needs_translation(r.get('text'))):
            continue
        if scope == 'all' or not str(r.get('translation') or '').strip():
            items.append(Item(f"region:{r['id']}", str(r['text']).strip(), float(r['start']), float(r['end']), '', 'onscreen'))
    return items


def read_usage(folder: Path):
    value = _read(Path(folder) / USAGE_FILE, None)
    return value if isinstance(value, dict) else None


def _add_usage(folder: Path, provider: str, model: str, mode: str, outcome) -> None:
    if outcome.requests <= 0:
        return  # không có request thành công: giữ nguyên số liệu cộng dồn, kể cả mode
    old = read_usage(folder) or {}
    cost = None
    if outcome.cost_usd is not None or old.get('cost_usd') is not None:
        cost = (old.get('cost_usd') or 0) + (outcome.cost_usd or 0)
    _write(folder / USAGE_FILE, dict(
        requests=old.get('requests', 0) + outcome.requests,
        input_tokens=old.get('input_tokens', 0) + outcome.usage.input_tokens,
        output_tokens=old.get('output_tokens', 0) + outcome.usage.output_tokens + outcome.usage.thinking_tokens,
        cost_usd=cost, provider=provider, model=model, mode=mode,
        at=datetime.now(timezone.utc).isoformat()))


def _set_paused(folder: Path, paused: str | None) -> None:
    """Ghi cờ tạm dừng có cấu trúc vào số liệu dùng (nếu đã có); xóa khi lần chạy không tạm dừng."""
    old = read_usage(folder)
    if old is None:
        return
    value = paused if paused in ('quota', 'cost_cap') else None
    if 'paused' not in old or old['paused'] != value:
        _write(Path(folder) / USAGE_FILE, {**old, 'paused': value})


def spent_so_far(folder: Path) -> float:
    cost = (read_usage(folder) or {}).get('cost_usd')
    return float(cost) if isinstance(cost, (int, float)) else 0.0


def apply_outcome(folder: Path, items: list[Item], outcome, scope: str, terminology: str) -> None:
    from .review import load_state, translation_dependency
    cues = _read(folder / 'cues.json', [])
    regions = _read(folder / 'regions.json', [])
    state = load_state(folder)
    texts = outcome.texts
    done = []
    for c in cues:
        text = texts.get(str(c['id']))
        if text and (scope == 'all' or not str(c.get('text') or '').strip()):
            c['text'] = text
            c['status'] = 'needs_review'
            done.append(c)
    for c in done:
        c['translation_dependency'] = translation_dependency(c, state, cues, terminology)
    for r in regions:
        text = texts.get(f"region:{r.get('id')}")
        if text and (scope == 'all' or not str(r.get('translation') or '').strip()):
            r['translation'] = text
    _write(folder / 'cues.json', cues)
    _write(folder / 'regions.json', regions)
    ran = {i.id for i in items}
    failed = [i for i in _read(folder / FAILED_FILE, []) if i not in ran] + list(outcome.failed)
    _write(folder / FAILED_FILE, failed)


def run_job(folder: Path, settings, job: dict, emit, terminology: str, check_cancel=lambda: None) -> dict:
    """Chạy bước 'translate' trong tiến trình. Trả {'warnings': [...]}. ProviderError -> warnings."""
    folder = Path(folder)
    request = _read(folder / REQUEST_FILE, {})
    (folder / REQUEST_FILE).unlink(missing_ok=True)
    scope = request.get('scope') if request.get('scope') in SCOPES else 'missing'
    allow = bool(request.get('allow_over_cap'))
    name, key, model = selected(settings)
    label = LABELS.get(name, name)
    mode = job.get('mode') or 'vietsub'
    items = collect_items(folder, scope)
    if not items:
        return dict(warnings=['Không có câu nào cần dịch.'])
    emit('translating', 'Đang dịch lời gốc và chữ trên hình sang tiếng Việt', 45)
    prefs = prefs_ns(settings)
    provider = None
    try:
        provider = make_provider(name, key, model, thinking=settings.thinking)
        limiter = RateLimiter(Path(settings.data_dir) / RATE_FILE, prefs.rate_rpm, prefs.rate_rpd, scope=f'{name}/{model}')
        stop_file = folder / 'cancel.request'
        outcome = run_translation(folder, items, mode, prefs, provider, limiter=limiter,
                                  terminology=terminology, allow_over_cap=allow,
                                  spent_before=spent_so_far(folder) if prefs.tier == 'paid' else 0.0,
                                  should_stop=stop_file.exists)
    except ProviderError as exc:  # lỗi trước khi có request nào (tạo provider)
        return dict(warnings=[scrub(str(exc), key)])
    finally:
        if provider is not None:
            provider.close()
    # Request đã gửi luôn được ghi vào số liệu dùng. Khi hủy thì không ghi chữ vào cues.json
    # (người dùng có thể đang sửa); bản dịch đã trả tiền vẫn nằm trong cache.
    if outcome.paused != 'cancelled':
        apply_outcome(folder, items, outcome, scope, terminology)
    _add_usage(folder, name, model, mode, outcome)
    _set_paused(folder, outcome.paused)
    check_cancel()
    warnings = []
    if outcome.error:
        warnings.append(scrub(outcome.error, key))
    if outcome.paused == 'quota':
        warnings.append(f'Tạm dừng – hết hạn mức ngày của {label}. Đã dịch {len(outcome.texts)}/{len(items)} câu; '
                        'bấm "Dịch tiếp" khi hạn mức được làm mới.')
    elif outcome.paused == 'cost_cap':
        warnings.append(f'Tạm dừng – sắp vượt mức trần chi phí {prefs.cost_cap_usd:g} USD cho video này. '
                        'Bấm "Dịch tiếp, cho phép vượt trần" nếu muốn chạy tiếp.')
    return dict(warnings=warnings)


def estimate(folder: Path, scope: str, mode: str, values, terminology: str) -> dict | None:
    """Ước tính không gọi mạng; None nếu không có câu nào."""
    items = collect_items(Path(folder), scope)
    if not items:
        return None
    prefs = prefs_ns(values)
    plan = plan_translation(items, mode, prefs, terminology)
    paid = prefs.tier == 'paid'
    cap = prefs.cost_cap_usd if paid else None
    spent = spent_so_far(Path(folder)) if paid else None
    return dict(requests=plan.requests, input_tokens=plan.input_tokens, output_tokens=plan.output_tokens,
                cost_usd=plan.cost_usd, tier=prefs.tier, cap_usd=cap, spent_usd=spent,
                over_cap=bool(paid and plan.cost_usd is not None and cap is not None and spent + plan.cost_usd > cap),
                cue_count=len(items))
