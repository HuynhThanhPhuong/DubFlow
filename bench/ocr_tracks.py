"""Group OCR boxes into tracks (overlapping box, consecutive samples). A track visible >= 80 % of
the 60 s is 'static' (logo/watermark -> blur only); others are 'transient' (blur + Vietnamese text).
Writes <name>-tracks.json; the 'vi' field is filled from <name>-tracks-vi.json when present."""
import json, sys
from pathlib import Path
RUN = Path(__file__).resolve().parent / 'runs' / '20261027'
def iou(a, b):
    ix = max(0, min(a['x1'], b['x1']) - max(a['x0'], b['x0'])); iy = max(0, min(a['y1'], b['y1']) - max(a['y0'], b['y0']))
    return ix * iy / max(1, min((a['x1'] - a['x0']) * (a['y1'] - a['y0']), (b['x1'] - b['x0']) * (b['y1'] - b['y0'])))
for name in ['review', 'dialogue']:
    d = json.loads((RUN / 'full' / f'{name}-ocr.json').read_text(encoding='utf-8')); step = 1 / d['fps']
    tracks = []
    for b in sorted(d['det'], key=lambda b: b['t']):
        if b['score'] < .6: continue
        for tr in tracks:
            if tr['e'] >= b['t'] - 2.01 * step and iou(tr, b) > .5 and (tr['static_cand'] or tr['texts'][-1] == b['text'] or iou(tr, b) > .8):
                tr['e'] = b['t'] + step; tr['n'] += 1; tr['texts'].append(b['text'])
                for k in 'x0', 'y0': tr[k] = min(tr[k], b[k])
                for k in 'x1', 'y1': tr[k] = max(tr[k], b[k])
                break
        else:
            tracks.append(dict(s=b['t'], e=b['t'] + step, n=1, texts=[b['text']], static_cand=False, **{k: b[k] for k in ['x0', 'y0', 'x1', 'y1']}))
    out = []
    for tr in tracks:
        texts = list(dict.fromkeys(tr['texts']))
        out.append(dict(s=tr['s'], e=round(tr['e'], 2), x0=tr['x0'], y0=tr['y0'], x1=tr['x1'], y1=tr['y1'], n=tr['n'],
                        kind='static' if tr['n'] * step >= 48 else 'transient', text=max(texts, key=tr['texts'].count), variants=texts[:5]))
    (RUN / 'full' / f'{name}-tracks.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    print('==', name)
    for i, t in enumerate(out):
        print(i, t['kind'][0], f"{t['s']:5.1f}-{t['e']:5.1f}", (t['x0'], t['y0'], t['x1'], t['y1']), t['n'], t['text'], '|', '/'.join(t['variants'][1:3]))
