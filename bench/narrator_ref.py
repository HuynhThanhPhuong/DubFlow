"""Cut a longer original-narrator ref (6-11 s, whole phrases) from the review vocal stem.
Word-level Whisper zh gives the prompt text for exactly the cut span."""
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from benchlib import RUN, SR, sha
os.environ['HF_HOME'] = 'D:/OmniVoice/cache/hf'; os.environ['HF_HUB_OFFLINE'] = '1'
import numpy as np, soundfile as sf, torch, librosa
from transformers import pipeline
v, _ = sf.read(RUN / 'full/review-vocals.wav', dtype='float32'); v16 = librosa.resample(v, orig_sr=SR, target_sr=16000)
asr = pipeline('automatic-speech-recognition', model='openai/whisper-large-v3-turbo', dtype=torch.float16, device='cuda:0')
r = asr({'raw': v16[:28 * 16000], 'sampling_rate': 16000}, return_timestamps='word', generate_kwargs={'language': 'zh', 'task': 'transcribe'})
words = [dict(s=c['timestamp'][0], e=c['timestamp'][1] or c['timestamp'][0] + .3, w=c['text']) for c in r['chunks']]
best = None  # span starting and ending at pauses >= .2 s, 6-11 s, most speech
for i in range(len(words)):
    if i and words[i]['s'] - words[i - 1]['e'] < .2: continue
    for j in range(i, len(words)):
        d = words[j]['e'] - words[i]['s']
        if d > 11: break
        if d >= 6 and (j + 1 == len(words) or words[j + 1]['s'] - words[j]['e'] >= .2):
            if not best or d > best[2]: best = (i, j, d)
i, j, _ = best; s, e = max(0., words[i]['s'] - .08), words[j]['e'] + .12
seg = v[int(s * SR):int(e * SR)]
dest = RUN / 'refs-origreview/narrator-long.wav'
sf.write(dest, librosa.resample(seg * (.9 / abs(seg).max()), orig_sr=SR, target_sr=24000), 24000)
text = ''.join(w['w'] for w in words[i:j + 1]).strip()
(RUN / 'refs-origreview/refs-long.json').write_text(json.dumps({'m': dict(path=str(dest), text=text, span=[s, e], hash=sha(dest))}, ensure_ascii=False, indent=2), encoding='utf-8')
print(round(s, 2), round(e, 2), text)
