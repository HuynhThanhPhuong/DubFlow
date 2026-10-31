"""Word-level Whisper zh on the full dialogue vocal stem; group into phrases at pauses > 0.35 s,
with median F0 per phrase as a male/female hint (verify by eye, not ground truth)."""
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from benchlib import RUN, SR
os.environ['HF_HOME'] = 'D:/OmniVoice/cache/hf'; os.environ['HF_HUB_OFFLINE'] = '1'
import numpy as np, soundfile as sf, torch, librosa
from transformers import pipeline
full = RUN / 'full'
v, _ = sf.read(full / 'dialogue-vocals.wav', dtype='float32'); v16 = librosa.resample(v, orig_sr=SR, target_sr=16000)
asr = pipeline('automatic-speech-recognition', model='openai/whisper-large-v3-turbo', dtype=torch.float16, device='cuda:0')
words = []
for t0 in range(0, int(len(v16) / 16000) + 1, 25):  # 25 s windows with 2 s overlap, de-duplicated by time
    seg = v16[t0 * 16000:(t0 + 27) * 16000]
    if len(seg) < 8000: break
    r = asr({'raw': seg, 'sampling_rate': 16000}, return_timestamps='word', generate_kwargs={'language': 'zh', 'task': 'transcribe'})
    for c in r['chunks']:
        s, e = c['timestamp']; s += t0; e = (e + t0) if e is not None else s + .3
        if s < t0 + 25 and (not words or s >= words[-1]['e'] - .05):
            words.append(dict(s=round(s, 2), e=round(e, 2), w=c['text']))
phr, cur = [], []
for w in words:
    if cur and w['s'] - cur[-1]['e'] > .35:
        phr.append(cur); cur = []
    cur.append(w)
phr.append(cur)
out = []
for p in phr:
    s, e = p[0]['s'], p[-1]['e']
    f0 = librosa.yin(v16[int(s * 16000):int(e * 16000)], fmin=70, fmax=400, sr=16000) if e - s > .15 else np.array([0])
    vo = f0[(f0 > 75) & (f0 < 380)]
    out.append(dict(s=s, e=e, zh=''.join(w['w'] for w in p).strip(), f0=float(np.median(vo)) if len(vo) else None))
(full / 'dialogue-zh-phrases.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
for x in out:
    print(f"{x['s']:7.2f} {x['e']:7.2f} {x['f0'] or 0:5.0f} {x['zh']}")
