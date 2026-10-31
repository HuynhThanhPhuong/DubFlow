"""Pure helpers: group per-frame burned-in subtitle detections into segments and vote OCR text."""
import unicodedata
from collections import Counter

import numpy as np


def _iou(a, b):
    union = np.logical_or(a, b).sum()
    return 1.0 if union == 0 else float(np.logical_and(a, b).sum() / union)


def segment_frames(frames, fps, min_len=.3, max_gap=2, change_iou=.5):
    """frames: [{t, box|None, sig|None}] -> [{s, e, x0, y0, x1, y1, frames}] (sig = bool 16x128)."""
    step = 1 / fps
    segs, cur, gap = [], None, 0
    for f in frames:
        box = f.get('box')
        if box is None:
            gap += 1
            if gap > max_gap:
                cur = None
            continue
        sig = f.get('sig')
        if cur is not None and (gap > max_gap or (sig is not None and cur['sig'] is not None
                                                  and _iou(sig, cur['sig']) < change_iou)):
            cur = None
        gap = 0
        t = float(f['t'])
        if cur is None:
            cur = dict(s=t, e=t + step, x0=box[0], y0=box[1], x1=box[2], y1=box[3], frames=[t], sig=sig)
            segs.append(cur)
        else:
            cur['e'] = t + step
            cur['x0'], cur['y0'] = min(cur['x0'], box[0]), min(cur['y0'], box[1])
            cur['x1'], cur['y1'] = max(cur['x1'], box[2]), max(cur['y1'], box[3])
            cur['frames'].append(t)
            if cur['sig'] is None:
                cur['sig'] = sig
    return [{k: v for k, v in s.items() if k != 'sig'} for s in segs if s['e'] - s['s'] >= min_len - 1e-9]


def _key(text):
    text = unicodedata.normalize('NFKC', text)
    return ''.join(c for c in text if unicodedata.category(c)[0] not in 'PZC')


def vote_text(readings):
    """Majority text after NFKC and punctuation/space stripping -> (longest original in winning group, vote share)."""
    groups = {}
    for r in readings:
        k = _key(r)
        if k:
            groups.setdefault(k, []).append(r)
    if not groups:
        return '', 0.0
    best = max(groups.values(), key=len)  # first group wins ties
    return max(best, key=len), len(best) / len(readings)  # first occurrence wins equal length


def static_rows(segments, duration, ratio=.8):
    """Segments covering at least `ratio` of the duration (logo / fixed text), to exclude from subtitles."""
    return [s for s in segments if duration > 0 and (s['e'] - s['s']) / duration >= ratio]
