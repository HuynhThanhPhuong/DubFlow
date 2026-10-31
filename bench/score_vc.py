"""Per-line Whisper check of a converted voice track, sliced by the source manifest timing.
  python score_vc.py <wav> [<wav> ...]   (manifest: v60/tmr/manifest.json; source track scores 0)"""
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from benchlib import decode, RUN
from score_all_lib import tok, dist
os.environ['HF_HOME'] = 'D:/OmniVoice/cache/hf'; os.environ['HF_HUB_OFFLINE'] = '1'
import torch
from transformers import pipeline
a = pipeline('automatic-speech-recognition', model='openai/whisper-large-v3-turbo', dtype=torch.float16, device='cuda:0')
L = json.loads((RUN / 'v60/tmr/manifest.json').read_text(encoding='utf-8'))['lines']
for p in sys.argv[1:]:
    w = decode(p, 16000); tot = 0; bad = []
    for l in L:
        h = a({'raw': w[int(l['start'] * 16000):int((l['end'] + .1) * 16000)], 'sampling_rate': 16000}, generate_kwargs={'language': 'vi', 'num_beams': 1})['text'].strip()
        d = dist(tok(l['text'].lower().replace('vi rút', 'virus')), tok(h.lower())); tot += d
        if d: bad.append(f"  {l['i']} {d} {l['text']} => {h}")
    print(Path(p).name, 'TOTAL', tot, '/', sum(len(tok(l['text'])) for l in L), 'bad lines', len(bad))
    if '-v' in os.environ.get('VC_VERBOSE', ''): print('\n'.join(bad))
