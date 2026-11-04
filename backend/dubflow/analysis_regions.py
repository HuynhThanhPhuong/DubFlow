"""User-drawn analysis regions of a job (job['analysis_regions']), in source-video pixels.

    {"no_hard_subs": bool, "subtitle": [x, y, w, h] | None, "logos": [[x, y, w, h], ...], "screen_text": [[x, y, w, h], ...]}

Pure helpers shared by the API (validation) and the pipeline (what to analyse). No video or OCR library is imported.
"""
from __future__ import annotations

import hashlib
import json
import math

MIN_SIZE = 8
MAX_BOXES = 20
MAX_SUBTITLES = 6
NOT_READY = 'Hãy chọn vùng sub trước khi phân tích.'


def clamp_box(box, width, height, what='Vùng chọn'):
    """[x, y, w, h] -> ints inside the frame; ValueError (Vietnamese) when it ends up smaller than MIN_SIZE px."""
    try:
        x, y, w, h = (float(v) for v in box)
    except (TypeError, ValueError):
        raise ValueError(f'{what} không hợp lệ.') from None
    if not all(math.isfinite(v) for v in (x, y, w, h)) or w <= 0 or h <= 0:
        raise ValueError(f'{what} không hợp lệ.')
    x0, y0 = max(0.0, x), max(0.0, y)
    x1, y1 = min(float(width), x + w), min(float(height), y + h)
    x0, y0, x1, y1 = int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))
    if x1 - x0 < MIN_SIZE or y1 - y0 < MIN_SIZE:
        raise ValueError(f'{what} quá nhỏ hoặc nằm ngoài khung hình (tối thiểu {MIN_SIZE} px).')
    return [x0, y0, x1 - x0, y1 - y0]


def normalize(data, width, height):
    """Request body -> stored value. Raises ValueError (Vietnamese). No subtitle box is kept when the video has no hard subs."""
    data = data or {}
    width, height = int(width or 0), int(height or 0)
    if width <= 0 or height <= 0:
        raise ValueError('Chưa biết kích thước video nguồn.')
    no_hard = bool(data.get('no_hard_subs'))
    subtitles = [] if no_hard else subtitle_regions(data)
    if len(subtitles) > MAX_SUBTITLES:
        raise ValueError(f'Tối đa {MAX_SUBTITLES} vùng sub.')
    subtitles = [dict(box=clamp_box(r['box'], width, height, 'Vùng sub'), orientation=r['orientation']) for r in subtitles]
    subtitle = subtitles[0]['box'] if subtitles else None
    logos = [clamp_box(b, width, height, 'Vùng logo') for b in (data.get('logos') or [])]
    texts = [clamp_box(b, width, height, 'Vùng chữ trên màn hình') for b in (data.get('screen_text') or [])]
    if len(logos) > MAX_BOXES or len(texts) > MAX_BOXES:
        raise ValueError(f'Tối đa {MAX_BOXES} vùng mỗi loại.')
    if subtitle is None and not no_hard:
        raise ValueError('Hãy vẽ vùng sub hoặc chọn video không có sub cứng.')
    return dict(no_hard_subs=no_hard, subtitle=subtitle, subtitles=subtitles, logos=logos, screen_text=texts)


def subtitle_regions(value):
    """Canonical regions; an explicitly empty list overrides the legacy alias."""
    raw = value.get('subtitles')
    if raw is None:
        raw = [value['subtitle']] if value.get('subtitle') else []
    result = []
    for item in raw:
        box = item.get('box') if isinstance(item, dict) else item
        try:
            default = 'v' if float(box[3]) > 1.5 * float(box[2]) else 'h'
        except (TypeError, ValueError, IndexError):
            raise ValueError('Vùng sub không hợp lệ.') from None
        orientation = item.get('orientation') or default if isinstance(item, dict) else default
        if orientation not in ('h', 'v'):
            raise ValueError('Hướng chữ không hợp lệ.')
        result.append(dict(box=box, orientation=orientation))
    return result


def usable(value):
    """The stored regions when they are valid for analysis (a subtitle box or no_hard_subs), else None."""
    if not isinstance(value, dict):
        return None
    box_ok = lambda b: isinstance(b, (list, tuple)) and len(b) == 4 and all(isinstance(v, (int, float)) for v in b)
    try:
        subtitles = [] if value.get('no_hard_subs') else subtitle_regions(value)
    except (ValueError, TypeError):
        return None
    if len(subtitles) > MAX_SUBTITLES or any(not box_ok(r['box']) or not all(math.isfinite(v) for v in r['box']) or min(r['box'][2:]) < MIN_SIZE for r in subtitles):
        return None
    if not (bool(value.get('no_hard_subs')) or subtitles):
        return None
    subtitles = [dict(box=[int(round(v)) for v in r['box']], orientation=r['orientation']) for r in subtitles]
    return dict(no_hard_subs=bool(value.get('no_hard_subs')),
                subtitle=subtitles[0]['box'] if subtitles else None, subtitles=subtitles,
                logos=[[int(round(v)) for v in b] for b in value.get('logos') or [] if box_ok(b)],
                screen_text=[[int(round(v)) for v in b] for b in value.get('screen_text') or [] if box_ok(b)])


def _key(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def source_key(cfg):
    """What decides the source cues: whether there are hard subs and where the band is (logos and screen text do not)."""
    return _key(dict(v=7, no_hard_subs=cfg['no_hard_subs'], subtitles=subtitle_regions(cfg)))


def source_matches(cfg, key):
    """Recognize pre-dot8 stamps without rebuilding paid translations on upgrade."""
    subs = subtitle_regions(cfg)
    legacy_ok = not subs or (len(subs) == 1 and subs[0]['orientation'] == 'h')
    return key in (source_key(cfg), _key(dict(v=3, no_hard_subs=cfg['no_hard_subs'], subtitles=subs))) or (legacy_ok and key == _key(dict(v=2, no_hard_subs=cfg['no_hard_subs'], subtitle=cfg.get('subtitle'))))


def screen_key(cfg):
    return _key(dict(v=1, boxes=cfg['screen_text']))
