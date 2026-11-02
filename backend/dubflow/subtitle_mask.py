"""Small, dependency-free contract between OCR and the CPU renderer.

Regions may contain timed ``boxes`` in absolute source coordinates. Each box
can supply ``mask_path`` (a box-sized grayscale glyph mask, white = erase).
Creating glyph masks belongs in the OCR process; this module imports no CV stack.
An explicit empty boxes list suppresses the coarse parent fallback.
"""
from __future__ import annotations

import math
from copy import deepcopy


def refine_legacy_regions(existing_regions, detected_regions):
    """Attach OCR footprints while retaining user region metadata and fallbacks.

    Call with detections whose mask_path already points to published assets.
    Empty OCR is deliberately non-destructive. Unmatched new detections are
    appended; disabled parents still consume matches, preserving opt-outs.
    """
    existing = deepcopy(existing_regions)
    used = set()
    fields = ('x', 'y', 'width', 'height', 'start', 'end', 'mask_path', 'mask_crop')
    for parent in existing:
        boxes = []
        for index, detection in enumerate(detected_regions):
            if detection['start'] >= parent['end'] or detection['end'] <= parent['start']:
                continue
            overlap = max(0, min(parent['x']+parent['width'], detection['x']+detection['width'])-max(parent['x'],detection['x'])) * max(0, min(parent['y']+parent['height'], detection['y']+detection['height'])-max(parent['y'],detection['y']))
            area = min(parent['width']*parent['height'], detection['width']*detection['height'])
            if area <= 0 or overlap/area < .5:
                continue
            boxes.append({key: detection[key] for key in fields if key in detection})
            used.add(index)
        if boxes:
            parent['boxes'] = boxes
    ids = {r.get('id') for r in existing}
    for index, detection in enumerate(detected_regions):
        if index in used:
            continue
        detection = deepcopy(detection)
        base = detection.get('id', f'r{index+1}')
        name = base
        suffix = 1
        while name in ids:
            name = f'{base}-ocr{suffix}'
            suffix += 1
        detection['id'] = name
        ids.add(name)
        existing.append(detection)
    return existing


def refined_regions(regions, width, height, duration=float('inf')):
    """Flatten, intersect and clip detections without mutating stored regions."""
    result = []
    for parent in regions:
        if not parent.get('enabled'):
            continue
        for box in parent.get('boxes', [parent]):
            r = dict(parent, **box)
            r.pop('boxes', None)
            try:
                x, y, w, h = (float(r[k]) for k in ('x', 'y', 'width', 'height'))
                times = [float(parent['start']), float(r['start']), float(parent['end']), float(r['end'])]
                if not all(math.isfinite(v) for v in (x, y, w, h, *times)):
                    continue
                start = max(0., *times[:2])
                end = min(duration, *times[2:])
                left, top = max(0, math.floor(x)), max(0, math.floor(y))
                right, bottom = min(width, math.ceil(x+w)), min(height, math.ceil(y+h))
                if w <= 0 or h <= 0 or right <= left or bottom <= top or end <= start:
                    continue
                # Cropping a supplied glyph mask would change its alignment.
                if r.get('mask_path') and (left != x or top != y or right != x+w or bottom != y+h):
                    raise ValueError('Glyph mask boxes must have integer bounds inside the source frame')
                r.update(x=left, y=top, width=right-left, height=bottom-top, start=start, end=end)
                result.append(r)
            except (KeyError, TypeError, OverflowError):
                continue
    return result


def mask_filters(region, index, last, mask_input=None, frame_size=None, timed=True):
    """Return a feathered local erasure graph and its output label.

    FFmpeg delogo interpolates from the box perimeter; gentle smoothing removes
    seams. A supplied glyph mask confines replacement to strokes and shadows.
    This avoids the readable silhouettes left by blurring white glyphs alone.
    Work is proportional to the OCR box, not the whole frame. Half-open time
    intervals avoid an extra stale frame when consecutive detections change.
    timed=False drops the overlay's enable gate for a stream that already
    holds only the frames of the region's window (see windowed_filters).
    """
    w, h, x, y = (region[k] for k in ('width', 'height', 'x', 'y'))
    box_w,box_h = w,h
    pad = min(10,x,y,frame_size[0]-x-w,frame_size[1]-y-h) if frame_size and mask_input is not None else 0
    x-=pad; y-=pad; w+=2*pad; h+=2*pad
    radius = max(.5, min(8., h / 5))
    feather = min(1.5, max(.5, h / 32))
    prefix = f'sm{index}'
    erase = f'delogo=x=1:y=1:w={w-2}:h={h-2},' if w >= 6 and h >= 6 else ''
    graph = [f'[{last}]split[{prefix}base][{prefix}crop]',
             f'[{prefix}crop]crop={w}:{h}:{x}:{y}:exact=1,format=yuv444p,split[{prefix}sharp][{prefix}src]',
             f'[{prefix}src]{erase}gblur=sigma={min(radius,2)}:steps=2[{prefix}blur]']
    if mask_input is None:
        # Subpixel-soft perimeter; the interior remains fully opaque.
        expr = f"255*min(1,min(min(X+0.5,W-X-0.5),min(Y+0.5,H-Y-0.5))/{feather})"
        graph.append(f"[{prefix}sharp]format=gray,geq=lum='{expr}'[{prefix}mask]")
    else:
        graph.append(f'[{prefix}sharp]nullsink')
        label = f'{mask_input}:v' if isinstance(mask_input,int) else mask_input
        crop = region.get('mask_crop')
        extract = f"crop={int(crop[2])}:{int(crop[3])}:{int(crop[0])}:{int(crop[1])}:exact=1," if crop else ''
        padding = f'pad={w}:{h}:{pad}:{pad}:color=black,' if pad else ''
        graph.append(f'[{label}]{extract}scale={box_w}:{box_h},format=gray,{padding}'+'dilation,'*6+f'gblur=sigma=0.6[{prefix}mask]')
    gate = f":enable='gte(t,{region['start']})*lt(t,{region['end']})'" if timed else ''
    graph += [f'[{prefix}blur][{prefix}mask]alphamerge[{prefix}patch]',
              f'[{prefix}base][{prefix}patch]overlay={x}:{y}:format=auto{gate}[{prefix}out]']
    return ';'.join(graph), f'{prefix}out'


def time_segments(regions, duration=float('inf')):
    """Cut the timeline at every region edge -> [(start, end, active region indices)], end None for the last one.

    The active set is constant inside a segment (a region covers [start, end) exactly or not at all), so each
    segment can be processed with its regions ungated. Neighbours with the same active set are merged."""
    edges = sorted({0.} | {float(t) for r in regions for t in (r['start'], r['end']) if 0 < t < duration})
    segments = []
    for k, start in enumerate(edges):
        end = edges[k+1] if k+1 < len(edges) else None
        active = tuple(i for i, r in enumerate(regions)
                       if r['start'] <= start and r['end'] >= (duration if end is None else end))
        if segments and segments[-1][2] == active:
            segments[-1] = (segments[-1][0], end, active)
        else:
            segments.append((start, end, active))
    return segments


def windowed_filters(regions, source, duration, frame_size, mask_files=None):
    """Apply mask_filters to each region on the frames of its own window only -> (chains, output label).

    The plain chain gated each region with overlay enable=, so every frame still went through crop, delogo, blur
    and a full-frame overlay for all regions (a 106 s clip with 91 regions: 20 minutes). Here a region that lasts
    the whole clip is applied once, ungated. For the others the timeline is cut at the region edges
    (time_segments), trim/setpts feed each piece, a piece holds only the regions active in it, and concat joins
    the pieces: a region costs work only during its window, other pieces pass untouched. Regions keep their
    order except that whole-clip regions come first.
    mask_files maps a region index to its glyph atlas as a filter-escaped path. The atlas is read by a movie source
    (one decoded frame, repeated by alphamerge): as a separate ffmpeg input the graph stalled, because ffmpeg kept
    feeding video and never read the input's end of file. A region used in several pieces gets one copy per piece."""
    mask_files = mask_files or {}
    chains, uses = [], {}

    def apply(i, tag, last):
        label = None
        if i in mask_files:
            label = f'glyph{len(uses.setdefault(mask_files[i], []))}x{len(uses)}'
            uses[mask_files[i]].append(label)
        filters, last = mask_filters(regions[i], tag, last, label, frame_size, timed=False)
        chains.append(filters)
        return last

    steady = [i for i, r in enumerate(regions) if r['start'] <= 0 and r['end'] >= duration]
    for i in steady:
        source = apply(i, f'a{i}', source)
    timed = [i for i in range(len(regions)) if i not in steady]
    segments = time_segments([regions[i] for i in timed], duration)
    finals, splits = [], []
    if any(active for _, _, active in segments):
        for k, (start, end, active) in enumerate(segments):
            last = source
            if len(segments) > 1:
                bounds = (f'start={start:.6f}' if start > 0 else '', f'end={end:.6f}' if end is not None else '')
                chains.append(f"[w{k}]trim={':'.join(b for b in bounds if b)},setpts=PTS-STARTPTS[v{k}]")
                splits.append(f'[w{k}]')
                last = f'v{k}'
            for j in active:
                last = apply(timed[j], f'{k}x{timed[j]}', last)
            finals.append(last)
    head = [f"movie='{path}',split={len(labels)}" + ''.join(f'[{label}]' for label in labels) for path, labels in uses.items()]
    if len(finals) > 1:
        head.append(f'[{source}]split={len(segments)}' + ''.join(splits))
        chains.append(''.join(f'[{label}]' for label in finals) + f'concat=n={len(finals)}:v=1:a=0[wout]')
        source = 'wout'
    elif finals:
        source = finals[0]
    return head + chains, source


def subtitle_spans(cue, regions):
    """One union box per temporal slice, even for overlapping OCR line boxes."""
    matches = [r for r in regions if r.get('kind') == 'subtitle'
               and r['start'] < cue['end'] and r['end'] > cue['start']]
    edges = sorted({cue['start'], cue['end']} |
                   {max(cue['start'], r['start']) for r in matches} |
                   {min(cue['end'], r['end']) for r in matches})
    spans = []
    for start, end in zip(edges, edges[1:]):
        active = [r for r in matches if r['start'] < end and r['end'] > start]
        bounds = None
        if active:
            x, y = min(r['x'] for r in active), min(r['y'] for r in active)
            bounds = (x, y, max(r['x']+r['width'] for r in active)-x,
                      max(r['y']+r['height'] for r in active)-y,
                      min(r['height'] for r in active))
        if spans and spans[-1][2] == bounds:
            spans[-1] = (spans[-1][0], end, bounds)
        elif end > start:
            spans.append((start, end, bounds))
    return spans
