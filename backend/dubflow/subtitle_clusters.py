"""Spatial OCR clusters and one-to-one tracks, independent of video/model libraries."""
from statistics import median

try:
    from .subtitle_lines import compatible, line_key, subtitle_lines
except ImportError:
    from subtitle_lines import compatible, line_key, subtitle_lines


def cluster_rows(rows):
    """OCR xyxy/text tuples -> separate rows, split at gaps over 1.5 glyph heights."""
    groups = []
    for row in sorted(rows, key=lambda r: ((r[1]+r[3])/2, r[0])):
        h = max(1, row[3]-row[1])
        group = next((g for g in groups if abs(median((r[1]+r[3])/2 for r in g)-(row[1]+row[3])/2)
                      <= .5*min(h, median(r[3]-r[1] for r in g))), None)
        if group is None:
            groups.append([row])
        else:
            group.append(row)
    out = []
    for group in groups:
        parts = []
        for row in sorted(group, key=lambda r: r[0]):
            if parts and row[0]-max(r[2] for r in parts[-1]) <= 1.5*median([r[3]-r[1] for r in parts[-1]]+[row[3]-row[1]]):
                parts[-1].append(row)
            else:
                parts.append([row])
        for part in parts:
            out.append(dict(text=''.join(r[4] for r in part),
                            box=[min(r[0] for r in part), min(r[1] for r in part),
                                 max(r[2] for r in part), max(r[3] for r in part)],
                            text_height=float(median(r[3]-r[1] for r in part))))
    return sorted(out, key=lambda c: (c['box'][1], c['box'][0]))


def _position(a, b, orientation='h'):
    if orientation == 'v':
        a, b = [a[1], a[0], a[3], a[2]], [b[1], b[0], b[3], b[2]]
    h = max(1, min(a[3]-a[1], b[3]-b[1]))
    if abs((a[1]+a[3]-b[1]-b[3])/2) > .6*h:
        return None
    overlap = max(0, min(a[2], b[2])-max(a[0], b[0]))
    small = max(1, min(a[2]-a[0], b[2]-b[0]))
    shift = abs((a[0]+a[2]-b[0]-b[2])/2)
    if overlap/small < .25 and shift > h:
        return None
    return overlap/small - shift/max(small, h)*.1


def clustered_lines(samples, duration, step=.4):
    """Frame samples {t, clusters:[{text, box, text_height}]} -> independently timed cues.

    Matching requires spatial agreement even for identical text. Every observation and
    every track is consumed at most once per frame, so simultaneous captions cannot fuse.
    """
    samples = sorted(samples, key=lambda s: float(s['t']))
    tracks = []
    for frame_index, sample in enumerate(samples):
        observations = sample.get('clusters') or []
        candidates = []
        for ti, track in enumerate(tracks):
            if float(sample['t'])-track['last_t'] > step*3+1e-6:
                continue
            for ci, obs in enumerate(observations):
                score = _position(track['box'], obs['box'], obs.get('orientation', 'h'))
                if score is not None:
                    a, b = line_key(track['text']), line_key(obs['text'])
                    score += .25 if compatible(a, b) or a.startswith(b) or b.startswith(a) else 0
                    candidates.append((score, ti, ci))
        used_tracks, used_obs = set(), set()
        assignments = []
        for _, ti, ci in sorted(candidates, reverse=True):
            if ti not in used_tracks and ci not in used_obs:
                used_tracks.add(ti)
                used_obs.add(ci)
                assignments.append((ti, ci))
        for ci, obs in enumerate(observations):
            if ci not in used_obs:
                tracks.append(dict(box=obs['box'], text=obs['text'], last_t=float(sample['t']), readings={}))
                assignments.append((len(tracks)-1, ci))
        for ti, ci in assignments:
            obs = observations[ci]
            tracks[ti].update(box=obs['box'], text=obs['text'], last_t=float(sample['t']))
            tracks[ti]['readings'][frame_index] = dict(obs, t=sample['t'])
    out = []
    for ti, track in enumerate(tracks):
        readings = [track['readings'].get(i, dict(t=s['t'], text='', miss=s.get('miss', False)))
                    for i, s in enumerate(samples)]
        for line in subtitle_lines(readings, duration, step):
            box = [line[k] for k in ('x0', 'y0', 'x1', 'y1')]
            heights = [r['text_height'] for r in track['readings'].values()
                       if line['s'] <= float(r['t']) <= line['e'] and r.get('text_height')]
            out.append(dict(line, box=box, cluster=ti,
                            text_height=float(median(heights)) if heights else max(1, box[3]-box[1])))
    return sorted(out, key=lambda c: (c['s'], c['box'][1], c['box'][0]))
