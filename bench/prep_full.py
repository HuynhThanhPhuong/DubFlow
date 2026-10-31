"""Full-length prep: Demucs background stem (rtsubs Separator, 30 s chunks) for both videos,
then Whisper zh segments on the dialogue vocal stem with median F0 per segment (speaker hint only)."""
import json, os, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from benchlib import RUN, FF, SR, VIDEOS
os.environ['HF_HOME'] = 'D:/OmniVoice/cache/hf'; os.environ['HF_HUB_OFFLINE'] = '1'
sys.path.insert(0, 'D:/DuAnKhoiNghiep/DubFlow/repo-tests/rtsubs/server')
import numpy as np, soundfile as sf, torch, librosa
from rtsubs.config import Settings
from rtsubs.separate import Separator

full = RUN / 'full'; full.mkdir(exist_ok=True)
sep = Separator(Settings())
for name, src in VIDEOS.items():
    if (full / f'{name}-background.wav').exists():
        continue
    a = np.frombuffer(subprocess.check_output([FF, '-v', 'error', '-i', src, '-ac', '2', '-ar', str(SR), '-f', 'f32le', '-']), np.float32).reshape(-1, 2).copy()
    dur = len(a) / SR
    bed = np.concatenate([sep.bgm(a, t, min(dur, t + 30)) for t in np.arange(0, dur, 30)])
    sf.write(full / f'{name}-background.wav', bed, SR, subtype='FLOAT')
    sf.write(full / f'{name}-vocals.wav', (a[:len(bed)] - bed).mean(1), SR, subtype='FLOAT')
    print('separated', name, round(dur, 2), flush=True)
del sep; torch.cuda.empty_cache()

from transformers import pipeline
asr = pipeline('automatic-speech-recognition', model='openai/whisper-large-v3-turbo', dtype=torch.float16, device='cuda:0')
v, _ = sf.read(full / 'dialogue-vocals.wav', dtype='float32')
v16 = librosa.resample(v, orig_sr=SR, target_sr=16000)
r = asr({'raw': v16, 'sampling_rate': 16000}, chunk_length_s=30, return_timestamps=True, generate_kwargs={'language': 'zh', 'task': 'transcribe'})
segs = []
for c in r['chunks']:
    s, e = c['timestamp']; e = e or s + 1
    f0 = librosa.yin(v16[int(s * 16000):int(e * 16000)], fmin=70, fmax=400, sr=16000) if e - s > .2 else np.array([0])
    rms = librosa.feature.rms(y=v16[int(s * 16000):int(e * 16000)])[0] if e - s > .2 else np.array([0])
    voiced = f0[(f0 > 75) & (f0 < 380)]
    segs.append(dict(s=round(s, 2), e=round(e, 2), zh=c['text'], f0=round(float(np.median(voiced)), 0) if len(voiced) else None))
(full / 'dialogue-zh-segments.json').write_text(json.dumps(segs, ensure_ascii=False, indent=1), encoding='utf-8')
for x in segs:
    print(x['s'], x['e'], x['f0'], x['zh'])
