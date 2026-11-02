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
    subtitle = data.get('subtitle')
    subtitle = None if no_hard or subtitle is None else clamp_box(subtitle, width, height, 'Vùng sub')
    logos = [clamp_box(b, width, height, 'Vùng logo') for b in (data.get('logos') or [])]
    texts = [clamp_box(b, width, height, 'Vùng chữ trên màn hình') for b in (data.get('screen_text') or [])]
    if len(logos) > MAX_BOXES or len(texts) > MAX_BOXES:
        raise ValueError(f'Tối đa {MAX_BOXES} vùng mỗi loại.')
    if subtitle is None and not no_hard:
        raise ValueError('Hãy vẽ vùng sub hoặc chọn video không có sub cứng.')
    return dict(no_hard_subs=no_hard, subtitle=subtitle, logos=logos, screen_text=texts)


def usable(value):
    """The stored regions when they are valid for analysis (a subtitle box or no_hard_subs), else None."""
    if not isinstance(value, dict):
        return None
    box_ok = lambda b: isinstance(b, (list, tuple)) and len(b) == 4 and all(isinstance(v, (int, float)) for v in b)
    if not (bool(value.get('no_hard_subs')) or box_ok(value.get('subtitle'))):
        return None
    return dict(no_hard_subs=bool(value.get('no_hard_subs')),
                subtitle=None if value.get('no_hard_subs') else [int(round(v)) for v in value['subtitle']],
                logos=[[int(round(v)) for v in b] for b in value.get('logos') or [] if box_ok(b)],
                screen_text=[[int(round(v)) for v in b] for b in value.get('screen_text') or [] if box_ok(b)])


def _key(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def source_key(cfg):
    """What decides the source cues: whether there are hard subs and where the band is (logos and screen text do not)."""
    return _key(dict(v=2, no_hard_subs=cfg['no_hard_subs'], subtitle=cfg['subtitle']))


def screen_key(cfg):
    return _key(dict(v=1, boxes=cfg['screen_text']))
