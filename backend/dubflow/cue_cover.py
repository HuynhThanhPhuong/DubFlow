"""Dot13 item 5: hide the burned-in Chinese under captions the OCR track does not cover (pure functions, no I/O).

clean.mp4 is built from subtrack.json, i.e. from the lines the OCR found. A caption the user added by hand, or any cue whose time
the OCR lines do not cover, may still sit on a Chinese subtitle the OCR missed (test2: '[师尊]' read at confidence .58). For those
spans the render probes the strip of the cue's region for text (engine stage `cueprobe`) and blurs the boxes it finds, frame by
frame. When nothing is found and the cue was put there by the user, the whole strip of the region is blurred for the span."""
from __future__ import annotations

import math

PAD = .15          # the same padding the eraser puts around an OCR line
MIN_SPAN = .2      # shorter uncovered pieces are not probed
BRIDGE = .45       # a gap of at most this many seconds between two detections is bridged (the OCR misses frames)
PROBE_VERSION = 1
AUTO_SOURCES = ('ocr', 'ocr+asr', 'asr')


def is_manual(cue):
    return cue.get('source') not in AUTO_SOURCES


def _supp(c):
    return c.get('kind') == 'supplementary' or c.get('orientation') == 'v'


def _subtract(span, covered):
    pieces = [list(span)]
    for a, b in covered:
        nxt = []
        for s, e in pieces:
            if b <= s or a >= e:
                nxt.append([s, e])
                continue
            if a > s:
                nxt.append([s, a])
            if b < e:
                nxt.append([b, e])
        pieces = nxt
    return [(s, e) for s, e in pieces if e - s >= MIN_SPAN - 1e-9]


def uncovered_windows(cues, segments, specs, duration):
    """Dialogue cues -> [{id, start, end, region, box:[x,y,w,h], manual}]: the pieces of each cue's time that no OCR line of the same
    region covers (lines padded by PAD). A cue with a region is probed in that region's strip; a cue without one (added by hand)
    in the strip of every horizontal region, and only the first of them is the fallback strip. ASR-only cues are probed (a
    subtitle the OCR missed may be there) but never blurred when nothing is found."""
    horizontal = [i for i, r in enumerate(specs) if r.get('orientation') == 'h']
    lines = {}
    for s in segments:
        if s.get('orientation') == 'v' or s.get('kind') == 'supplementary':
            continue
        lines.setdefault(s.get('region', 0), []).append((float(s['s']) - PAD, float(s['e']) + PAD))
    out = []
    for c in cues:
        if _supp(c) or float(c['end']) <= float(c['start']):
            continue
        manual = is_manual(c)
        if not manual and c.get('source') != 'asr':
            continue  # an OCR cue is covered by its own line
        regions = [c['region']] if c.get('region') in horizontal else horizontal
        for n, r in enumerate(regions):
            for s, e in _subtract((max(0., float(c['start'])), min(float(duration), float(c['end']))), lines.get(r, [])):
                out.append(dict(id=c['id'], start=round(s, 3), end=round(e, 3), region=r, box=[int(v) for v in specs[r]['box']],
                                manual=manual, fallback=manual and n == 0))
    return out


def probe_key(window):
    return f"{PROBE_VERSION}:{window['start']:.3f}:{window['end']:.3f}:" + ','.join(str(v) for v in window['box'])


def _union(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def boxes_from_samples(samples, start, end, step=.2, band=None, grow=4):
    """Probe samples [{t, box:[x0,y0,x1,y1]|None}] -> timed boxes [{start, end, x, y, width, height}] (None = nothing read).

    A sample covers [t, t + step). Gaps of at most BRIDGE s between detections are bridged with the union of both neighbours, the
    first / last detection is extended by half a step, and everything is cut to [start, end) and (when given) the band
    [x, y, w, h]."""
    hits = sorted((float(s['t']), [float(v) for v in s['box']]) for s in samples if s.get('box'))
    if not hits:
        return []
    runs = [[hits[0]]]
    for h in hits[1:]:
        if h[0] - runs[-1][-1][0] - step <= BRIDGE + 1e-9:
            runs[-1].append(h)
        else:
            runs.append([h])
    out = []
    for run in runs:
        box = _union([b for _, b in run])
        a, b = max(start, run[0][0] - step/2), min(end, run[-1][0] + step*1.5)
        x0, y0, x1, y1 = box[0] - grow, box[1] - grow, box[2] + grow, box[3] + grow
        if band:
            x0, y0, x1, y1 = max(x0, band[0]), max(y0, band[1]), min(x1, band[0] + band[2]), min(y1, band[1] + band[3])
        if b > a and x1 > x0 and y1 > y0:
            out.append(dict(start=round(a, 3), end=round(b, 3), x=int(x0), y=int(y0), width=math.ceil(x1) - int(x0), height=math.ceil(y1) - int(y0)))
    return out


def cover_regions(windows, probes, width, height):
    """Windows + probe results {key: {'boxes': [...]}} -> (render mask rows, warnings in Vietnamese).

    rows are `subtitle`-like mask regions (kind 'cuefill') the renderer blurs with delogo + gaussian blur."""
    rows, warnings = [], []
    for w in windows:
        found = (probes.get(probe_key(w)) or {}).get('boxes') or []
        if found:
            rows.append(dict(id=f"cuefill-{w['id']}-{w['start']:.2f}", kind='cuefill', enabled=True, x=0, y=0, width=1, height=1,
                             start=w['start'], end=w['end'], boxes=[dict(b) for b in found]))
        elif w['fallback']:
            x, y, bw, bh = w['box']
            rows.append(dict(id=f"cuefill-{w['id']}-{w['start']:.2f}", kind='cuefill', enabled=True, x=x, y=y, width=bw, height=bh,
                             start=w['start'], end=w['end']))
            warnings.append(f"Không dò được chữ Trung dưới câu {w['id']} ({w['start']:.1f}-{w['end']:.1f} s); đã làm mờ cả dải chữ của vùng sub trong khoảng này.")
    return rows, warnings
