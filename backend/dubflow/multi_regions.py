"""Independent OCR and confined cleanup passes for user subtitle regions.

No model imports here. Each erase pass uses the existing confined band eraser;
intermediate videos live inside the job, never in a global temp directory.
"""
from pathlib import Path
import shutil
import tempfile

try:
    from .pipeline import read, write
except ImportError:
    from pipeline import read, write


def read_regions(directory, request, read_band):
    directory = Path(directory)
    specs = request['subtitles']
    tracks, segments = [], []
    for index, spec in enumerate(specs):
        read_band(directory, {k: v for k, v in dict(request, box=spec['box'], orientation=spec['orientation']).items() if k != 'subtitles'})
        track = read(directory/'subtrack.json', {})
        x, y, w, h = spec['box']
        for line in track.get('segments', []):
            # The user band bounds layout; the measured union positions the cue.
            actual = [line.get('x0', x), line.get('y0', y), line.get('x1', x+w), line.get('y1', y+h)]
            line.update(region=index, box=actual, band=[x, y, x+w, y+h], orientation=spec['orientation'])
            if spec['orientation'] == 'v':
                line['kind'] = 'supplementary'
                line.pop('reveal', None)
            line.setdefault('text_height', max(1, line['y1']-line['y0']) if spec['orientation'] == 'h' else max(1, min(w, line['x1']-line['x0']) / 2))
        tracks.append(dict(track, region=index, orientation=spec['orientation']))
        segments.extend(track.get('segments', []))
    if len(tracks) == 1:
        out = tracks[0]
    else:
        out = dict(version=3, mode='regions', regions=tracks, segments=sorted(segments, key=lambda s: (s['s'], s['region'])))
    write(directory/'subtrack.json', out)


def erase_regions(directory, request, erase_band):
    directory = Path(directory)
    track = read(directory/'subtrack.json', {})
    tracks = [dict(t, segments=[s for s in t.get('segments', [])
                               if s.get('orientation') != 'v' and s.get('kind') != 'supplementary'])
              for t in track['regions'] if t.get('orientation') != 'v' and t.get('kind') != 'supplementary']
    tracks = [t for t in tracks if t['segments']]
    if not tracks:
        tracks = [dict(version=2, mode='none', box=None, segments=[])]
    stamps = []
    source = request['source']
    with tempfile.TemporaryDirectory(prefix='erase-regions-', dir=directory) as temp:
        for i, item in enumerate(tracks):
            if (directory/'cancel.request').exists():
                raise RuntimeError('cancelled')
            target = Path(temp)/str(i)
            target.mkdir()
            write(target/'subtrack.json', item)
            erase_band(target, dict(request, source=str(source), static_regions=request.get('static_regions', []) if i == 0 else []))
            stamps.append(read(target/'erase.json', {}))
            source = target/'clean.mp4'
        shutil.copyfile(source, directory/'clean.tmp.mp4')
        (directory/'clean.tmp.mp4').replace(directory/'clean.mp4')
    fills = [s.get('fill') for s in stamps]
    fill = 'lama' if all(f=='lama' for f in fills) else 'smooth' if all(f=='smooth' for f in fills) else 'lama+smooth'
    stamp = dict(stamps[0], version=11, region_passes=len(stamps), fill=fill,
                 lama=all(s.get('lama') for s in stamps),
                 runtime_fallback=any(s.get('runtime_fallback') for s in stamps),
                 warnings=list(dict.fromkeys(w for s in stamps for w in s.get('warnings', []))),
                 seconds=sum(s.get('seconds', 0) for s in stamps))
    write(directory/'erase.json', stamp)
