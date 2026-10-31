"""Uniform ASR screening for every engine at three stages:
raw  = each synthesized line on its own (generation errors)
dry  = timed voice-only 30s track (adds fit/crop/overlap losses)
final= AAC audio of the delivered MP4 (adds bed/loudnorm/codec)
Whisper large-v3-turbo; screening only, not listening/emotion/identity."""
import csv, json, os, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from benchlib import RUN, OLD, OUT, cues, decode, sha
os.environ['HF_HOME'] = 'D:/OmniVoice/cache/hf'; os.environ['HF_HUB_OFFLINE'] = '1'
import torch
from transformers import pipeline

tok = lambda s: re.findall(r'\w+', s.lower())
def dist(a, b):
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        new = [i]
        for j, y in enumerate(b, 1):
            new.append(min(new[-1] + 1, row[j] + 1, row[j - 1] + (x != y)))
        row = new
    return row[-1]

M = OLD / 'more-repos'
def old_lines(d, pat):
    return sorted(p for p in d.glob(pat) if '_adjusted' not in p.name)
def new_lines(work, field):
    return [Path(l[field]) for l in json.loads((work / 'manifest.json').read_text(encoding='utf-8'))['lines']]
E = {}
for n in ['review', 'dialogue']:
    E[('pyVideoTrans-Edge', n)] = ([], OLD / f'pyVideoTrans-{n}/voice.wav', OUT / f'DubFlow-test-pyVideoTrans-{n}-30s.mp4')
    E[('rtsubs-VieNeu', n)] = (old_lines(OLD / f'rtsubs-{n}/lines', '*.wav'), None, OUT / f'DubFlow-test-rtsubs-VieNeu-{n}-30s.mp4')
    E[('open-dubbing-MMS', n)] = (old_lines(M / f'open-dubbing-MMS-{n}/lines', 'dubbed_*.mp3'), M / f'open-dubbing-MMS-{n}/dry.wav', OUT / f'DubFlow-test-open-dubbing-MMS-{n}-30s.mp4')
    for e in ['VideoLingo-Edge', 'Linly-Edge-adapter']:
        E[(e, n)] = (old_lines(M / f'{e}-{n}/lines', '*.mp3'), M / f'{e}-{n}/dry.wav', OUT / f'DubFlow-test-{e}-{n}-30s.mp4')
    E[('VoiceStudio-OmniVoice-old', n)] = (old_lines(M / f'VoiceStudio-OmniVoice-{n}/lines', '*.wav'), M / f'VoiceStudio-OmniVoice-{n}/dry.wav', OUT / f'DubFlow-test-VoiceStudio-OmniVoice-{n}-30s.mp4')
    E[('VietVoice', n)] = (new_lines(RUN / f'VietVoice-{n}', 'file'), RUN / f'VietVoice-{n}/dry.wav', OUT / f'DubFlow-20261027-VietVoice-{n}-30s.mp4')
    for e, field in [('Edge-young', 'file'), ('Edge-span', 'file'), ('VieNeu-young', 'file'), ('VietVoice-young', 'file'), ('VoiceStudio-OmniVoice-young', 'raw')]:
        w = RUN / f'{e}-{n}'
        E[(e, n)] = (new_lines(w, field), w / 'dry.wav', OUT / f'DubFlow-20261027-{e}-{n}-30s.mp4')
for v in ['viterbox', 'voxcpm-ref', 'voxcpm-ultimate']:
    w = RUN / f'{v}-actor-zh-dialogue'
    if (w / 'manifest.json').exists():
        E[(f'{v}-actor-zh', 'dialogue')] = (new_lines(w, 'file'), w / 'dry.wav', OUT / f'DubFlow-20261027-{v}-actor-zh-dialogue-30s.mp4')
for n in ['review-full', 'dialogue-full']:
    for v in ['viterbox', 'voxcpm-ref', 'voxcpm-ultimate']:
        w = RUN / f'{v}-omni-{n}'
        if (w / 'manifest.json').exists():
            E[(f'{v}-omni', n)] = (new_lines(w, 'file'), w / 'dry.wav', OUT / f'DubFlow-20261027-{v}-omni-{n}.mp4')
for e, n in [('voxcpm-ultimate-origreview', 'review-full'), ('voxcpm-ultimate-orig', 'dialogue-full')]:
    w = RUN / f'{e}-{n}'
    if (w / 'manifest.json').exists():
        E[(e, n)] = (new_lines(w, 'file'), w / 'dry.wav', OUT / f'DubFlow-20261027-{e}-{n}.mp4')
for v in ['actor-zh', 'clean-vi']:
    w = RUN / f'VoiceStudio-OmniVoice-{v}-dialogue'
    E[(f'VoiceStudio-OmniVoice-{v}', 'dialogue')] = (new_lines(w, 'raw'), w / 'dry.wav', OUT / f'DubFlow-20261027-VoiceStudio-OmniVoice-{v}-dialogue-30s.mp4')

asr = pipeline('automatic-speech-recognition', model='openai/whisper-large-v3-turbo', dtype=torch.float16, device='cuda:0')
cache_dir = RUN / 'asr-cache'; cache_dir.mkdir(exist_ok=True)
def recog(path, t=None):
    key = cache_dir / (sha(dict(p=str(path), h=sha(Path(path)), t=t)) + '.json')
    if key.exists():
        return json.loads(key.read_text(encoding='utf-8'))['text']
    r = asr({'raw': decode(path, 16000, t), 'sampling_rate': 16000}, chunk_length_s=30, generate_kwargs={'language': 'vi', 'task': 'transcribe', 'num_beams': 1})
    key.write_text(json.dumps(r, ensure_ascii=False), encoding='utf-8'); return r['text']

rows, lines_out = [], []
for (engine, n), (lines, dry, final) in E.items():
    cs = cues(n); ref = ' '.join(c['text'] for c in cs); W = len(tok(ref))
    row = dict(engine=engine, type=n, words=W, raw_edits=None, dry_edits=None, final_edits=None, note='')
    if lines and len(lines) == len(cs):
        tot = 0
        for c, p in zip(cs, lines):
            hyp = recog(p); d = dist(tok(c['text']), tok(hyp)); tot += d
            lines_out.append(dict(engine=engine, type=n, speaker=c['speaker'], text=c['text'], asr=hyp.strip(), edits=d))
        row['raw_edits'] = tot
    elif lines:
        row['note'] += f'raw lines {len(lines)} != cues {len(cs)}; '
    else:
        row['note'] += 'no per-line files kept; '
    if dry and dry.exists():
        h = recog(dry); row['dry_edits'] = dist(tok(ref), tok(h)); row['dry_asr'] = h.strip()
    else:
        row['note'] += 'no dry track (only mixed); '
    if final.exists():
        h = recog(final, None if n.endswith('-full') else 30); row['final_edits'] = dist(tok(ref), tok(h)); row['final_asr'] = h.strip()
    rows.append(row); print(engine, n, row['raw_edits'], row['dry_edits'], row['final_edits'], '/', W, row['note'], flush=True)

(RUN / 'score.json').write_text(json.dumps(dict(scope=__doc__, results=rows, lines=lines_out), ensure_ascii=False, indent=2), encoding='utf-8')
with (RUN / 'score.csv').open('w', newline='', encoding='utf-8-sig') as f:
    w = csv.DictWriter(f, ['engine', 'type', 'words', 'raw_edits', 'dry_edits', 'final_edits', 'note'], extrasaction='ignore'); w.writeheader(); w.writerows(rows)
with (RUN / 'score-lines.csv').open('w', newline='', encoding='utf-8-sig') as f:
    w = csv.DictWriter(f, ['engine', 'type', 'speaker', 'text', 'asr', 'edits']); w.writeheader(); w.writerows(lines_out)
