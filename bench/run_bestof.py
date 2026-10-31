"""Best-of-N VoxCPM2 ultimate clone with the original actor voices (dialogue 30 s).
  gen  (clone-voxcpm venv): N seeds per line -> lines/{i:03d}-s{seed}.wav
  pick (OmniVoice venv):    Whisper each candidate, keep the lowest edit distance, then fit/place.
Two stages because VoxCPM2 + Whisper do not fit together in 6 GB."""
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from benchlib import RUN, OLD, cues, decode, fit_and_place
stage, name = sys.argv[1], 'dialogue'; SEEDS = [9527, 11, 22, 33]
REFS = {'m': (OLD / 'more-repos/actor-m-reference.wav', '我知道不严重，就是看着不放心。慢点，我扶你。'),
        'f': (OLD / 'more-repos/actor-f-reference.wav', '看你怎么比我还紧张。没事，可以松了。')}
work = RUN / f'voxcpm-ultimate-bestof-{name}'; (work / 'lines').mkdir(parents=True, exist_ok=True)
cand = lambda i, s: work / 'lines' / f'{i:03d}-s{s}.wav'
import numpy as np, soundfile as sf, torch
if stage == 'gen':
    os.environ['HF_HOME'] = 'D:/DuAnKhoiNghiep/DubFlow/repo-tests/runtime/hf-cache'
    from voxcpm import VoxCPM
    model = VoxCPM.from_pretrained('openbmb/VoxCPM2', load_denoiser=False, optimize=False, cache_dir=os.environ['HF_HOME'])
    for i, c in enumerate(cues(name)):
        ref, txt = REFS[c['speaker']]
        for s in SEEDS:
            if cand(i, s).exists():
                continue
            torch.manual_seed(s); np.random.seed(s)
            w = np.asarray(model.generate(text=c['text'], prompt_wav_path=str(ref), prompt_text=txt, cfg_value=2.0, inference_timesteps=10), np.float32).reshape(-1)
            sf.write(cand(i, s), w * min(1., .9 / max(float(abs(w).max()), 1e-9)), 48000, subtype='FLOAT'); print('gen', i, s, flush=True)
else:
    os.environ['HF_HOME'] = 'D:/OmniVoice/cache/hf'; os.environ['HF_HUB_OFFLINE'] = '1'
    from transformers import pipeline
    from score_all_lib import tok, dist
    asr = pipeline('automatic-speech-recognition', model='openai/whisper-large-v3-turbo', dtype=torch.float16, device='cuda:0')
    files, manifest = [], []
    for i, c in enumerate(cues(name)):
        scored = []
        for s in SEEDS:
            h = asr({'raw': decode(cand(i, s), 16000), 'sampling_rate': 16000}, generate_kwargs={'language': 'vi', 'task': 'transcribe', 'num_beams': 1})['text']
            scored.append((dist(tok(c['text']), tok(h)), len(decode(cand(i, s))) , s, h))
        d, _, s, h = min(scored)
        files.append(cand(i, s)); manifest.append(dict(i=i, speaker=c['speaker'], text=c['text'], seed=s, asr=h.strip(), edits=d, all=[x[0] for x in scored], file=str(cand(i, s))))
        print(i, c['speaker'], 'edits per seed', [x[0] for x in scored], '-> seed', s, flush=True)
    rows = fit_and_place(name, files, work, trim=True)
    (work / 'manifest.json').write_text(json.dumps(dict(engine='voxcpm-ultimate-bestof', seeds=SEEDS, lines=manifest, placements=rows), ensure_ascii=False, indent=2), encoding='utf-8')
    print('DONE overlaps', sum(r['overlap_next_s'] > 0 for r in rows), 'chosen edits', sum(m['edits'] for m in manifest))
