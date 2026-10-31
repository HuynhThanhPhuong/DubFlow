"""Render the 60 s deliverables. Original Chinese subtitles are removed only where detected
(delogo inside the measured box, per time segment), Vietnamese subtitles sit in the same band.
  vietsub : dialogue video, original audio untouched
  dub     : review video, Demucs background + cloned narrator (no time-stretch)
  tm      : dialogue video, original audio ducked to -10 dB + one Vietnamese narrator"""
import json, subprocess, sys, textwrap
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from benchlib import RUN, OUT, FF, VIDEOS, cues
mode = sys.argv[1]; LEN = 60.0
name = 'review' if mode in ('dub', 'tmr', 'vc', 'mix', 'kcx') else 'dialogue'
box = json.loads((RUN / 'full' / f'{name}-subbox.json').read_text(encoding='utf-8'))
W, H = box['W'], box['H']; y0, y1 = box['segs'][0]['y0'], box['segs'][0]['y1']
work = RUN / 'v60' / mode; work.mkdir(parents=True, exist_ok=True)
if mode == 'vietsub':
    cs = [c for c in cues('dialogue-full') if c['s'] < LEN - .5]
else:
    cs = [dict(s=r['start'], e=max(r['end'], r['start'] + .8), text=r['text']) for r in json.loads((work / 'manifest.json').read_text(encoding='utf-8'))['lines']]
ts = lambda t: (lambda c: f'{c // 360000}:{c // 6000 % 60:02}:{c // 100 % 60:02}.{c % 100:02}')(round(t * 100))
size = round((y1 - y0) * .78)
ass = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,3,1,5,40,40,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
# subtitles: hold until the next one starts (max +1.2 s), one line if it fits
for i, c in enumerate(cs):
    e = min(cs[i + 1]['s'] if i + 1 < len(cs) else LEN, c['e'] + 1.2)
    ass += f"Dialogue: 0,{ts(c['s'])},{ts(e)},Default,,0,0,0,,{{\\pos({W // 2},{(y0 + y1) // 2})}}{c['text']}\n"
(work / 'captions.ass').write_text(ass, encoding='utf-8-sig')
pad = 6
# other on-screen text (OCR tracks, see ocr_tracks.py): static logo/watermark -> blurred for the whole clip;
# transient captions outside the subtitle band -> blurred while shown + Vietnamese text in the same place
VI = {'（细心的男生很加分）': '(Con trai tinh tế được cộng điểm)'}
tracks = json.loads((RUN / 'full' / f'{name}-tracks.json').read_text(encoding='utf-8'))
in_band = lambda t: t['y0'] >= y0 - 25 and t['y1'] <= y1 + 25
blur = []
for t in tracks:
    if t['kind'] == 'static' and not in_band(t):
        blur.append((t['x0'], t['y0'], t['x1'], t['y1'], 0, LEN))
    elif t['text'] in ('黑皮电影',):  # watermark: OCR loses it on bright frames, so treat as static
        blur.append((t['x0'], t['y0'], t['x1'], t['y1'], 0, LEN))
    elif t['kind'] == 'transient' and not in_band(t) and t['n'] >= 2 and t['text'] in VI:
        blur.append((t['x0'], t['y0'], t['x1'], t['y1'], t['s'] - .3, t['e'] + .3))
        fs = round((t['y1'] - t['y0']) * .8)
        ass += f"Dialogue: 1,{ts(max(0, t['s'] - .3))},{ts(t['e'] + .3)},Default,,0,0,0,,{{\\an4\\fs{fs}\\pos({t['x0']},{(t['y0'] + t['y1']) // 2})}}{VI[t['text']]}\n"
merged = {}
for b in blur:  # one region per place
    k = next((k for k in merged if abs(k[0] - b[0]) < 40 and abs(k[1] - b[1]) < 40), None)
    if k is None: merged[b[:4]] = [b[4], b[5]]
    else: merged[k] = [min(merged[k][0], b[4]), max(merged[k][1], b[5])]
(work / 'captions.ass').write_text(ass, encoding='utf-8-sig')
v = '[0:v]' + ','.join(f"delogo=x={max(1, s['x0'] - pad)}:y={y0 - 2}:w={min(W - 2, s['x1'] + pad) - max(1, s['x0'] - pad)}:h={min(H - 2 - (y0 - 2), y1 - y0 + 4)}:enable='between(t,{s['s'] - .1:.2f},{s['e'] + .1:.2f})'"
                       for s in box['segs'] if s['s'] < LEN) + '[v0]'
for k, ((x0, b0, x1, b1), (s, e)) in enumerate(merged.items()):
    x0, b0 = max(0, x0 - 10), max(0, b0 - 8); w, h = min(W, x1 + 10) - x0, min(H, b1 + 8) - b0
    v += f";[v{k}]split[m{k}][c{k}];[c{k}]crop={w}:{h}:{x0}:{b0},boxblur=lr=12:lp=3:cr=6:cp=3[b{k}];[m{k}][b{k}]overlay={x0}:{b0}:enable='between(t,{s:.2f},{e:.2f})'[v{k + 1}]"
v += f";[v{len(merged)}]ass=captions.ass[vout]"
print('blur regions', merged)
dest = OUT / f'DubFlow-20261027-60s-{mode}.mp4'
cmd = [FF, '-hide_banner', '-y', '-t', str(LEN), '-i', VIDEOS[name]]
if mode == 'vietsub':
    a, amap = '', '0:a:0'
else:
    voice = str(work / 'dry.wav')
    if mode in ('dub', 'vc', 'mix', 'kcx'):
        cmd += ['-i', str(RUN / 'full/review-background.wav'), '-i', voice]
        a = ';[1:a]volume=0.8[bg];[2:a]volume=0.85[vo];[bg][vo]amix=inputs=2:normalize=0:duration=first,loudnorm=I=-17:TP=-2.5:LRA=11[a]'
    else:
        cmd += ['-i', voice]
        a = ';[0:a]volume=0.32[og];[1:a]volume=0.9[vo];[og][vo]amix=inputs=2:normalize=0:duration=first,loudnorm=I=-17:TP=-2.5:LRA=11[a]'
    amap = '[a]'
cmd += ['-filter_complex', v + a, '-map', '[vout]', '-map', amap, '-c:a', 'aac', '-b:a', '192k', '-ar', '48000',
        '-t', str(LEN), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(dest)]
with (work / 'render.log').open('w', encoding='utf-8') as log:
    subprocess.run(cmd, cwd=work, stdout=log, stderr=log, check=True)
print('RENDERED', dest)
