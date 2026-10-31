"""Shared helpers for DubFlow headless benchmark run (no UI)."""
import hashlib, json, subprocess, time
from pathlib import Path
import numpy as np, soundfile as sf

FF = 'D:/OmniVoice/tools/ffmpeg.exe'
SR = 44100
OLD = Path('D:/Codex/2026-10-26/pha/work/repo-benchmark')
REFS = Path('D:/Codex/2026-10-26/pha/work/dubflow-test/vietvoice')
OUT = Path('D:/Codex/2026-10-26/pha/outputs')
VIDEOS = {
    'review': 'C:/Users/PC/Downloads/SaveDouyin_Douyin_Media_7694606242899053859_001_1080p.mp4',
    'dialogue': 'C:/Users/PC/Downloads/SaveDouyin_Douyin_Media_7696391076050996514_001_1080p.mp4',
}
RUN = Path(__file__).resolve().parent / 'runs' / '20261027'
RUN.mkdir(parents=True, exist_ok=True)


def sha(data):
    if isinstance(data, Path):
        h = hashlib.sha256()
        with data.open('rb') as f:
            for block in iter(lambda: f.read(1 << 20), b''):
                h.update(block)
        return h.hexdigest()[:16]
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


VIDEOS['review-full'] = VIDEOS['review']; VIDEOS['dialogue-full'] = VIDEOS['dialogue']
LENGTH = {'review-full': 71.05, 'dialogue-full': 251.9}


def cues(name):
    if name.endswith('-full'):
        return json.loads((RUN / 'full' / f'{name}-cues.json').read_text(encoding='utf-8'))
    return json.loads((OLD / f'{name}-cues.json').read_text(encoding='utf-8'))


def background(name):
    return RUN / 'full' / f'{name[:-5]}-background.wav' if name.endswith('-full') else OLD / f'{name}-background.wav'


def decode(path, sr=SR, t=None):
    cmd = [FF, '-v', 'error'] + (['-t', str(t)] if t else []) + ['-i', str(path), '-ac', '1', '-ar', str(sr), '-f', 'f32le', '-']
    return np.frombuffer(subprocess.check_output(cmd), dtype=np.float32).copy()


TRIM = 'silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse,adelay=20,apad=pad_dur=0.04'


def fit_and_place(name, files, work, max_rate=1.25, length=None, trim=False):
    length = length or LENGTH.get(name, 30.0)
    """Place lines at cue start. Speed up (atempo) only when a line overruns the
    gap to the next cue start; never slow down; never crop. Everything logged.
    trim=True strips leading/trailing silence (e.g. Edge MP3 padding) first."""
    cs = cues(name)
    dry = np.zeros(int(length * SR), dtype=np.float32)
    rows = []
    if trim:
        out = []
        for f in files:
            t = Path(work) / 'lines' / (Path(f).stem + '-trim.wav')
            subprocess.run([FF, '-v', 'error', '-y', '-i', str(f), '-af', TRIM, '-ac', '1', '-ar', str(SR), str(t)], check=True)
            out.append(t)
        files = out
    for i, (c, f) in enumerate(zip(cs, files)):
        wave = decode(f)
        natural = len(wave) / SR
        slot = (cs[i + 1]['s'] if i + 1 < len(cs) else length) - c['s'] - 0.05
        rate = min(max_rate, max(1.0, natural / slot))
        if rate > 1.001:
            wave = np.frombuffer(subprocess.check_output([FF, '-v', 'error', '-i', str(f), '-af', f'aformat=sample_fmts=s16:sample_rates={SR}:channel_layouts=mono,atempo={rate:.6f}', '-ac', '1', '-ar', str(SR), '-f', 'f32le', '-']), dtype=np.float32).copy()
        a = round(c['s'] * SR); b = min(len(dry), a + len(wave))
        dry[a:b] += wave[:b - a]
        end = c['s'] + len(wave) / SR
        rows.append(dict(i=i, speaker=c['speaker'], text=c['text'], source_start=c['s'], source_end=c['e'],
                         actual_start=c['s'], actual_end=round(end, 3), natural_dur=round(natural, 3),
                         speed_rate=round(rate, 3), overlap_next_s=round(max(0., end - (c['s'] + slot + .05)), 3),
                         over_source_end_s=round(max(0., end - c['e']), 3), cropped_s=round(max(0., a + len(wave) - len(dry)) / SR, 3)))
    peak = float(np.abs(dry).max())
    if peak > .95:
        dry *= .95 / peak
    sf.write(work / 'dry.wav', dry, SR, subtype='FLOAT')
    (work / 'placements.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    return rows


class Timer:
    def __enter__(self):
        self.t = time.time(); return self

    def __exit__(self, *a):
        self.s = round(time.time() - self.t, 2)
