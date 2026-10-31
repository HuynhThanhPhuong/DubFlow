"""Original-voice refs cut from the Demucs vocal stems (prompt text = Whisper zh of the same span).
dialogue: m/f = the reviewed actor refs; t/s = longest 3-10 s zh phrase inside that speaker's cues.
review: narrator = longest 3-10 s Whisper zh segment of review-vocals.
Writes refs-orig/refs.json (dialogue) and refs-origreview/refs.json (review, speaker m)."""
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from benchlib import RUN, OLD, SR, cues, sha
os.environ['HF_HOME'] = 'D:/OmniVoice/cache/hf'; os.environ['HF_HUB_OFFLINE'] = '1'
import soundfile as sf, librosa, torch
full = RUN / 'full'

def cut(src, s, e, dest):
    v, _ = sf.read(src, dtype='float32'); seg = v[int(s * SR):int(e * SR)]
    sf.write(dest, librosa.resample(seg * (.9 / max(abs(seg).max(), 1e-9)), orig_sr=SR, target_sr=24000), 24000); return dest

d = RUN / 'refs-orig'; d.mkdir(exist_ok=True)
refs = {'m': dict(path=str(OLD / 'more-repos/actor-m-reference.wav'), text='我知道不严重，就是看着不放心。慢点，我扶你。'),
        'f': dict(path=str(OLD / 'more-repos/actor-f-reference.wav'), text='看你怎么比我还紧张。没事，可以松了。')}
cs = cues('dialogue-full'); ph = json.loads((full / 'dialogue-zh-phrases.json').read_text(encoding='utf-8'))
def speaker(t):
    return next((c['speaker'] for c in cs if c['s'] - .3 <= t <= c['e'] + .3), None)
for sp in ['t', 's']:
    cand = [p for p in ph if speaker((p['s'] + p['e']) / 2) == sp and 3 <= p['e'] - p['s'] <= 10] or \
           sorted([p for p in ph if speaker((p['s'] + p['e']) / 2) == sp], key=lambda p: p['s'] - p['e'])[:1]
    p = max(cand, key=lambda p: p['e'] - p['s'])
    refs[sp] = dict(path=str(cut(full / 'dialogue-vocals.wav', p['s'], p['e'], d / f'{sp}.wav')), text=p['zh'], span=[p['s'], p['e']])
for v in refs.values():
    v['hash'] = sha(Path(v['path']))
(d / 'refs.json').write_text(json.dumps(refs, ensure_ascii=False, indent=2), encoding='utf-8')

from transformers import pipeline
asr = pipeline('automatic-speech-recognition', model='openai/whisper-large-v3-turbo', dtype=torch.float16, device='cuda:0')
v, _ = sf.read(full / 'review-vocals.wav', dtype='float32'); v16 = librosa.resample(v, orig_sr=SR, target_sr=16000)
segs = asr({'raw': v16, 'sampling_rate': 16000}, chunk_length_s=30, return_timestamps=True, generate_kwargs={'language': 'zh', 'task': 'transcribe'})['chunks']
print([(c['timestamp'], c['text']) for c in segs]); segs = [c for c in segs if c['timestamp'][1] and 2 <= c['timestamp'][1] - c['timestamp'][0] <= 15]
c = max(segs, key=lambda c: c['timestamp'][1] - c['timestamp'][0]); s, e = c['timestamp']
r = RUN / 'refs-origreview'; r.mkdir(exist_ok=True)
p = cut(full / 'review-vocals.wav', s, e, r / 'narrator.wav')
(r / 'refs.json').write_text(json.dumps({'m': dict(path=str(p), text=c['text'], span=[s, e], hash=sha(p))}, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(refs, ensure_ascii=False, indent=1)); print('review', s, e, c['text'])
