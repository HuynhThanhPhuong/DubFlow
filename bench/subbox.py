"""Find the burned-in Chinese subtitle box over time (white glyphs with dark outline) in the bottom band.
Output: segments [{s, e, x0, y0, x1, y1}] in source pixels, for delogo/cover only where text is."""
import json, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from benchlib import RUN, FF, VIDEOS
import numpy as np

def boxes(video, BAND, length=60, fps=10, top=900):
    W, H = map(int, subprocess.check_output(['D:/OmniVoice/tools/ffprobe.exe', '-v', 'error', '-select_streams', 'v', '-show_entries', 'stream=width,height', '-of', 'csv=p=0', video]).decode().split(','))
    h = H - top
    raw = subprocess.check_output([FF, '-v', 'error', '-t', str(length), '-i', video, '-vf', f'fps={fps},crop={W}:{h}:0:{top},format=gray', '-f', 'rawvideo', '-'])
    fr = np.frombuffer(raw, np.uint8).reshape(-1, h, W)
    out = []
    for k, g in enumerate(fr):
        white, dark = g > 205, g < 70
        dd = dark.copy()
        for dy, dx in [(-3, 0), (3, 0), (0, -3), (0, 3)]:
            dd |= np.roll(np.roll(dark, dy, 0), dx, 1)
        t = white & dd
        band = t[BAND[0] - top:BAND[1] - top]
        cols = np.where(band.sum(0) >= 2)[0]
        if band.sum() < 250 or not len(cols):
            out.append(None); continue
        # subtitles are centred: grow a cluster out from the centre, bridging gaps < 70 px
        c = W // 2; near = cols[np.argmin(abs(cols - c))]
        if abs(near - c) > 250:
            out.append(None); continue
        x0 = x1 = near
        for x in cols[cols > near]:
            if x - x1 > 70: break
            x1 = x
        for x in cols[cols < near][::-1]:
            if x0 - x > 70: break
            x0 = x
        out.append((int(x0), BAND[0], int(x1), BAND[1]))
    segs = []
    for k, b in enumerate(out):
        t = k / fps
        if b is None:
            continue
        if segs and segs[-1]['e'] >= t - 1.5 / fps and abs(segs[-1]['y0'] - b[1]) < 25:
            s = segs[-1]; s['e'] = t + 1 / fps
            s['x0'], s['y0'], s['x1'], s['y1'] = min(s['x0'], b[0]), min(s['y0'], b[1]), max(s['x1'], b[2]), max(s['y1'], b[3])
        else:
            segs.append(dict(s=t, e=t + 1 / fps, x0=b[0], y0=b[1], x1=b[2], y1=b[3]))
    return W, H, [s for s in segs if s['e'] - s['s'] >= .3]

if __name__ == '__main__':
    for n in ['review', 'dialogue']:
        W, H, segs = boxes(VIDEOS[n], {'review': (976, 1068), 'dialogue': (984, 1046)}[n])
        (RUN / 'full' / f'{n}-subbox.json').write_text(json.dumps(dict(W=W, H=H, segs=segs), indent=1), encoding='utf-8')
        print(n, W, H, len(segs), 'y-range', min(s['y0'] for s in segs), max(s['y1'] for s in segs))
        for s in segs[:6]:
            print('  ', s)
