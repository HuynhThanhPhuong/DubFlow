"""Automatic logo / fixed-text candidates.

detect_static finds edges that persist on a changing background in sparsely sampled frames (needs numpy + cv2,
imported lazily). merge_candidates and apply_candidates are plain Python so the web process can import this module.
"""
from __future__ import annotations

from collections import Counter

SAMPLE_STEP = 2.0       # seconds between sampled frames
MAX_SAMPLES = 150
SAMPLE_WIDTH = 640      # sampled frames are downscaled to this width
EDGE_MIN = 40           # Sobel magnitude
PERSISTENCE_MIN = .5    # fraction of samples in which a pixel is an edge
CLOSE_SIZE = 5
AREA_MIN, AREA_MAX = .0003, .06   # component area as a fraction of the (downscaled) frame
PAD = 6                 # source px added around the component bbox
RING = 12               # source px of background ring checked for change
RING_STD_MIN = 6.0      # grey levels, mean temporal std over the ring
PRESENCE_MIN = .5       # fraction of the component's edge pixels present in a sample
GAP = 2                 # samples bridged when joining presence runs
WIDEN = 1.0             # seconds added to both ends of a run
FULL_PRESENCE = .8      # present in at least this fraction of samples -> whole video
EXCLUDE_OVERLAP = .5
IOU_MIN, CONTAIN_MIN = .3, .5
BLOCK_IOU = .5
LABEL_TEXT, LABEL_LOGO = 'Chữ cố định', 'Logo'


def user_owned(r):
    """A region the user touched (translation typed, or switched off) is never merged away or replaced."""
    return bool((r.get('translation') or '').strip()) or r.get('enabled', True) is False


def _box(r):
    return r['x'], r['y'], r['x'] + r['width'], r['y'] + r['height']


def _inter(a, b):
    return max(0., min(a[2], b[2]) - max(a[0], b[0])) * max(0., min(a[3], b[3]) - max(a[1], b[1]))


def _area(a):
    return max(0., a[2] - a[0]) * max(0., a[3] - a[1])


def _iou(a, b):
    i = _inter(a, b)
    return i / (_area(a) + _area(b) - i) if i else 0.


def _overlaps(a, b):
    """IoU > .3 or containment (intersection over the smaller box) > .5."""
    i = _inter(a, b)
    if not i:
        return False
    return i / (_area(a) + _area(b) - i) > IOU_MIN or i / max(1e-9, min(_area(a), _area(b))) > CONTAIN_MIN


def detect_static(frames, times, duration, exclude, scale):
    """Persistent edge regions on a changing background.

    frames: grayscale uint8 arrays, all the same size, already downscaled by `scale` (small px = source px * scale).
    exclude: (x, y, w, h) boxes in source px. Returns dicts in source px: x, y, width, height, start, end, presence.
    """
    import cv2
    import numpy as np
    n = len(frames)
    if n < 4 or n != len(times):
        return []
    h, w = frames[0].shape
    source_w, source_h = max(1, round(w / scale)), max(1, round(h / scale))
    stack = np.stack(frames).astype(np.uint8)
    edges = np.empty((n, h, w), bool)
    for i in range(n):
        gx = cv2.Sobel(stack[i], cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(stack[i], cv2.CV_32F, 0, 1, ksize=3)
        edges[i] = np.hypot(gx, gy) > EDGE_MIN
    persistent = edges.mean(0) >= PERSISTENCE_MIN
    closed = cv2.morphologyEx(persistent.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((CLOSE_SIZE, CLOSE_SIZE), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(closed, connectivity=8)
    pad_s, ring_s = max(1, int(np.ceil(PAD * scale))), max(1, int(np.ceil(RING * scale)))
    out = []
    for label in range(1, count):
        bx, by, bw, bh, area = (int(v) for v in stats[label])
        if not AREA_MIN * h * w <= area <= AREA_MAX * h * w:
            continue
        # box in source px, padded
        x0, y0 = max(0, int(np.floor(bx / scale)) - PAD), max(0, int(np.floor(by / scale)) - PAD)
        x1, y1 = min(source_w, int(np.ceil((bx + bw) / scale)) + PAD), min(source_h, int(np.ceil((by + bh) / scale)) + PAD)
        if x1 - x0 < 2 or y1 - y0 < 2:
            continue
        own = (x1 - x0) * (y1 - y0)
        if any(_inter((x0, y0, x1, y1), (ex, ey, ex + ew, ey + eh)) > EXCLUDE_OVERLAP * own for ex, ey, ew, eh in exclude):
            continue
        # a still shot has no changing background around the box: the whole frame is "persistent"
        px0, py0, px1, py1 = max(0, bx - pad_s), max(0, by - pad_s), min(w, bx + bw + pad_s), min(h, by + bh + pad_s)
        rx0, ry0, rx1, ry1 = max(0, px0 - ring_s), max(0, py0 - ring_s), min(w, px1 + ring_s), min(h, py1 + ring_s)
        ring = np.ones((ry1 - ry0, rx1 - rx0), bool)
        ring[py0 - ry0:py1 - ry0, px0 - rx0:px1 - rx0] = False
        if not ring.any():
            continue
        values = stack[:, ry0:ry1, rx0:rx1][:, ring].astype(np.float32)
        if float(values.std(0).mean()) < RING_STD_MIN:
            continue
        core = (labels[by:by + bh, bx:bx + bw] == label) & persistent[by:by + bh, bx:bx + bw]
        if not core.any():
            continue
        hit = edges[:, by:by + bh, bx:bx + bw][:, core].mean(1) >= PRESENCE_MIN
        presence = float(hit.mean())
        if not hit.any():
            continue
        box = dict(x=x0, y=y0, width=x1 - x0, height=y1 - y0, presence=round(presence, 3))
        if presence >= FULL_PRESENCE:
            out.append(dict(box, start=0.0, end=round(float(duration), 3)))
            continue
        runs, run = [], None
        for i in np.flatnonzero(hit):
            if run is not None and i - run[1] - 1 <= GAP:
                run[1] = int(i)
            else:
                run = [int(i), int(i)]
                runs.append(run)
        for a, b in runs:
            start, end = max(0., float(times[a]) - WIDEN), min(float(duration), float(times[b]) + WIDEN)
            if end > start:
                out.append(dict(box, start=round(start, 3), end=round(end, 3)))
    return sorted(out, key=lambda r: (r['x'], r['y'], r['start']))


def _clusters(fragments):
    """Union OCR static fragments that overlap (IoU > .3 or containment > .5), via union-find over an x sweep."""
    order = sorted(range(len(fragments)), key=lambda i: fragments[i]['x'])
    parent = list(range(len(fragments)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    boxes = [_box(f) for f in fragments]
    for a, i in enumerate(order):
        for j in order[a + 1:]:
            if boxes[j][0] >= boxes[i][2]:
                break
            if _overlaps(boxes[i], boxes[j]):
                parent[find(j)] = find(i)
    groups = {}
    for i in order:
        groups.setdefault(find(i), []).append(i)
    clusters = []
    for members in groups.values():
        frags = [fragments[i] for i in members]
        texts = Counter(f.get('text', '').strip() for f in frags if f.get('text', '').strip())
        x0, y0 = min(f['x'] for f in frags), min(f['y'] for f in frags)
        x1, y1 = max(f['x'] + f['width'] for f in frags), max(f['y'] + f['height'] for f in frags)
        clusters.append(dict(x=x0, y=y0, width=x1 - x0, height=y1 - y0, start=min(f['start'] for f in frags),
                             end=max(f['end'] for f in frags), text=texts.most_common(1)[0][0] if texts else '',
                             texts=texts, ids=[f['id'] for f in frags]))
    return sorted(clusters, key=lambda c: (c['x'], c['y']))


def merge_candidates(detected, ocr_static, duration):
    """Few candidate regions from edge detections and the (often hundreds of) OCR static fragments.

    Output regions: kind static, auto, not confirmed, enabled; label "Chữ cố định" when OCR text is present else "Logo".
    `merged_ids` lists the OCR fragments folded in (apply_candidates removes them) and is not stored in regions.json.
    """
    clusters = _clusters([f for f in ocr_static if f.get('width', 0) > 0 and f.get('height', 0) > 0 and not user_owned(f)])
    used = set()
    rows = []
    for d in detected:
        mine = [i for i, c in enumerate(clusters) if _overlaps(_box(d), _box(c))]
        used.update(mine)
        parts = [d] + [clusters[i] for i in mine]
        texts = Counter()
        for i in mine:
            texts.update(clusters[i]['texts'])
        rows.append(dict(parts=parts, text=texts.most_common(1)[0][0] if texts else '', ids=[x for i in mine for x in clusters[i]['ids']],
                         presence=d.get('presence')))
    for i, c in enumerate(clusters):
        if i not in used:
            rows.append(dict(parts=[c], text=c['text'], ids=c['ids'], presence=None))
    out = []
    for n, row in enumerate(sorted(rows, key=lambda r: (min(p['x'] for p in r['parts']), min(p['y'] for p in r['parts']))), 1):
        parts = row['parts']
        x0, y0 = min(p['x'] for p in parts), min(p['y'] for p in parts)
        x1, y1 = max(p['x'] + p['width'] for p in parts), max(p['y'] + p['height'] for p in parts)
        region = dict(id=f'logo-{n}', kind='static', x=x0, y=y0, width=x1 - x0, height=y1 - y0,
                      start=max(0., min(p['start'] for p in parts)), end=min(float(duration), max(p['end'] for p in parts)),
                      text=row['text'], translation='', enabled=True, auto=True, confirmed=False,
                      label=LABEL_TEXT if row['text'] else LABEL_LOGO, merged_ids=row['ids'])
        if row['presence'] is not None:
            region['presence'] = row['presence']
        if region['end'] > region['start']:
            out.append(region)
    return out


def apply_candidates(existing, candidates):
    """regions.json content after a detection run.

    Kept: every non-static region, every confirmed region, every user-owned region (translation typed or disabled) and
    every non-auto static region that was not merged into a candidate. Dropped: merged OCR fragments and old unconfirmed auto candidates. A candidate overlapping (IoU > .5)
    a confirmed or rejected (disabled) static region is not added, so a re-run never resurrects a decision.
    """
    merged = {i for c in candidates for i in c.get('merged_ids', ())}
    kept = []
    for r in existing:
        if r.get('kind') != 'static' or r.get('confirmed'):
            kept.append(r)
        elif user_owned(r) or (not r.get('auto') and r.get('id') not in merged):
            kept.append(r)
    blockers = [_box(r) for r in kept if r.get('kind') == 'static' and (r.get('confirmed') or user_owned(r))]
    taken = {r.get('id') for r in kept}
    out = list(kept)
    n = 0
    for c in candidates:
        if any(_iou(_box(c), b) > BLOCK_IOU for b in blockers):
            continue
        n += 1
        while f'logo-{n}' in taken:
            n += 1
        row = {k: v for k, v in c.items() if k not in ('merged_ids', 'presence')}
        row['id'] = f'logo-{n}'
        taken.add(row['id'])
        out.append(row)
    return out
