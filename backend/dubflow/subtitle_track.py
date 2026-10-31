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


def auto_band(row_density, height, top, frac=.25, pad=6):
    """Cumulative per-row 'white with dark outline' density (rows top..height) -> (y0, y1) source px or None."""
    d = np.asarray(row_density, dtype=float)
    if d.size == 0 or d.max() <= 0:
        return None
    rows = np.where(d >= frac * d.max())[0]
    runs = np.split(rows, np.where(np.diff(rows) > 1)[0] + 1)
    best = max(runs, key=len)
    return max(0, int(top + best[0]) - pad), min(int(height), int(top + best[-1] + 1) + pad)


def order_lines(boxes):
    """[(x0, y0, x1, y1, text)] -> text joined row by row (rows by y-centre within half the median height, then x)."""
    if not boxes:
        return ''
    hs = sorted(b[3] - b[1] for b in boxes)
    tol = max(1.0, hs[len(hs) // 2] / 2)
    rows = []
    for b in sorted(boxes, key=lambda b: (b[1] + b[3]) / 2):
        c = (b[1] + b[3]) / 2
        if rows and c - rows[-1]['c'] <= tol:
            r = rows[-1]; r['b'].append(b); r['c'] = sum((x[1] + x[3]) / 2 for x in r['b']) / len(r['b'])
        else:
            rows.append(dict(c=c, b=[b]))
    return ''.join(b[4] for r in rows for b in sorted(r['b'], key=lambda b: b[0]))


try:
    from .subtitle_cues import chinese
except ImportError:  # top-level import (engine scripts)
    from subtitle_cues import chinese
from difflib import SequenceMatcher


def _overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def _agreement(ocr, asr):
    a, b = chinese(ocr), chinese(asr)
    if not b:
        return 1.0
    if not a:
        return 0.0
    m = sum(x.size for x in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks())
    return m / max(len(a), len(b))


def build_source_cues(segments, asr_cues, duration, mismatch=.6, uncovered=.3):
    """OCR segments are the primary source; ASR fills uncaptioned speech. OCR text is never rewritten.

    OCR cues get source_mismatch = source_agreement < mismatch. An ASR cue partly covered by OCR is
    kept (full original, verbatim) over its largest uncovered interval when that is >= .8 s
    (source_partial=True); otherwise it is skipped."""
    segs = sorted(segments, key=lambda s: (s['s'], s['e']))
    asrs = sorted(asr_cues, key=lambda c: (c['start'], c['end']))
    out = []
    segs = [sg for sg in segs if min(float(sg['e']), float(duration)) > float(sg['s'])]
    for i, sg in enumerate(segs, 1):
        s, e = float(sg['s']), min(float(sg['e']), float(duration))
        if e <= s:
            continue
        hits = [(c, _overlap(s, e, c['start'], c['end'])) for c in asrs]
        hits = [(c, o) for c, o in hits if o > 1e-9]
        parts = []
        for c, _ in hits:
            han = chinese(c['original'])
            d = c['end'] - c['start']
            a = max(s, c['start']); b = min(e, c['end'])
            parts.append(han[int(round((a - c['start']) / d * len(han))):int(round((b - c['start']) / d * len(han)))])
        asr_text = ''.join(parts)
        best = max(hits, key=lambda h: h[1])[0] if hits else None
        cue = dict(id=f'ocr-{i:06}', start=s, end=e, original=sg['text'], text='',
                   speaker=best['speaker'] if best else 'unconfirmed', status='needs_review',
                   source='ocr+asr' if hits else 'ocr', source_ids=[c['id'] for c, _ in hits] or [f'ocr-{i:06}'],
                   box=[sg['x0'], sg['y0'], sg['x1'], sg['y1']], source_agreement=_agreement(sg['text'], asr_text))
        cue['source_mismatch'] = cue['source_agreement'] < mismatch
        if hits:
            cue['asr_text'] = asr_text
        out.append(cue)
    for c in asrs:
        d = c['end'] - c['start']
        if d <= 0:
            continue
        pos, gaps = c['start'], []
        for sg in segs:
            if sg['e'] <= c['start'] or sg['s'] >= c['end']:
                continue
            if sg['s'] > pos:
                gaps.append((pos, sg['s']))
            pos = max(pos, sg['e'])
        if pos < c['end']:
            gaps.append((pos, c['end']))
        cov = d - sum(b - a for a, b in gaps)
        if cov / d < uncovered:
            out.append(dict(c, source='asr', source_agreement=1.0))
            continue
        a, b = max(gaps, key=lambda g: g[1] - g[0], default=(0, 0))
        if b - a >= .8 - 1e-9:
            out.append(dict(c, start=a, end=b, source='asr', source_agreement=1.0, source_partial=True))
    return sorted(out, key=lambda c: (c['start'], c['end']))


def snap_to_speech(cues, rms, hop, threshold=None, pad=.05):
    """Move cue edges onto real speech (rms above threshold), at most .5 s beyond the original
    timing and never into the previous/next cue. Only for ASR-timed cues: OCR cue times follow the
    on-screen subtitle and must not be snapped."""
    rms = np.asarray(rms, dtype=float)
    if threshold is None:
        threshold = max(0.01, float(np.median(rms)) * 2) if rms.size else 0.01
    out = [dict(c) for c in cues]
    for i, c in enumerate(out):
        lo = max(0.0, c['start'] - .5)
        hi = min(rms.size * hop, c['end'] + .5)
        if i > 0:
            lo = max(lo, out[i - 1]['end'])
        if i + 1 < len(out):
            hi = min(hi, out[i + 1]['start'])
        i0, i1 = int(np.ceil(lo / hop - 1e-9)), int(np.floor(hi / hop + 1e-9))
        act = np.where(rms[i0:i1] > threshold)[0]
        if act.size == 0:
            continue
        start = max(lo, (i0 + act[0]) * hop - pad)
        end = min(hi, (i0 + act[-1] + 1) * hop + pad)
        if end > start:
            c['start'], c['end'] = round(float(start), 6), round(float(end), 6)
    return out
