"""60 s deliverables, zero-error loop, NO time-stretch (natural speed, no atempo).
  dub : review video, VoxCPM2 ultimate cloning the original narrator (refs-origreview/refs-long.json)
  tm  : dialogue video, thuyet minh with ONE ready-made Vietnamese voice (OmniVoice 'Ke chuyen xom')
  tmb : same, voice 'Bao Trung Review Phim'
Stages (VoxCPM2 and Whisper do not fit together in 6 GB):
  gen  <job>  (clone-voxcpm venv): candidates for every line that has no accepted take yet
  pick <job>  (OmniVoice venv):    Whisper every new candidate; accept a take only at 0 word edits;
                                   lines still failing get more seeds next round; then place.
Text overrides (shorter wording for lines that do not fit) live in v60/<job>-text.json."""
import json, os, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from benchlib import RUN, SR, FF, TRIM, cues, decode, sha
import numpy as np, soundfile as sf
stage, job = sys.argv[1], sys.argv[2]; LEN = 60.0
V = RUN / 'v60'; work = V / job; (work / 'lines').mkdir(parents=True, exist_ok=True)
REF = (json.loads((RUN / 'refs-origreview/refs-long.json').read_text(encoding='utf-8'))['m'] if job in ('dub', 'mix')
       else json.loads((RUN / 'refs-omni/refs.json').read_text(encoding='utf-8'))['b' if job == 'tmb' else 't'])
over = json.loads((V / f'{job}-text.json').read_text(encoding='utf-8')) if (V / f'{job}-text.json').exists() else {}
CS = [dict(c, text=over.get(str(i), c['text'])) for i, c in enumerate(cues('dialogue-full' if job in ('tm', 'tmb') else 'review-full')) if c['s'] < LEN - .5 and over.get(str(i), c['text'])]  # '' = merged into the previous line
state_f = work / 'state.json'
state = json.loads(state_f.read_text(encoding='utf-8')) if state_f.exists() else {}
PROMPT = json.loads((RUN / 'refs-origreview/vi-prompt.json').read_text(encoding='utf-8')) if job == 'mix' else None
def tkey(c): return sha(dict(t=c['text'], r=REF['hash'], p=PROMPT and PROMPT['hash']))
def todo():  # (i, seed) candidates still to make: 4 seeds first, +4 each failed round, max 24
    for i, c in enumerate(CS):
        st = state.get(tkey(c), {})
        if st.get('ok'): continue
        for s in range(st.get('nseeds', 4)):
            yield i, c, 1000 + s
def cand(i, c, s):  # a take is identified by text+ref+seed; the index prefix is cosmetic (lines can be merged)
    hit = [p for p in (work / 'lines').glob(f'*-{tkey(c)}-s{s}.wav')]
    return hit[0] if hit else work / 'lines' / f'{i:03d}-{tkey(c)}-s{s}.wav'

if stage == 'gen':
    os.environ['HF_HOME'] = 'D:/DuAnKhoiNghiep/DubFlow/repo-tests/runtime/hf-cache'
    import torch
    from voxcpm import VoxCPM
    model = VoxCPM.from_pretrained('openbmb/VoxCPM2', load_denoiser=False, optimize=False, cache_dir=os.environ['HF_HOME'])
    for i, c, s in todo():
        if cand(i, c, s).exists(): continue
        torch.manual_seed(s); np.random.seed(s)
        kw = dict(reference_wav_path=REF['path'], prompt_wav_path=PROMPT['path'], prompt_text=PROMPT['text']) if PROMPT else dict(prompt_wav_path=REF['path'], prompt_text=REF['text'])
        w = np.asarray(model.generate(text=c['text'], cfg_value=2.0, inference_timesteps=10, **kw), np.float32).reshape(-1)
        sf.write(cand(i, c, s), w * min(1., .9 / max(float(abs(w).max()), 1e-9)), 48000, subtype='FLOAT')
        print('gen', i, s, flush=True)
    sys.exit()

os.environ['HF_HOME'] = 'D:/OmniVoice/cache/hf'; os.environ['HF_HUB_OFFLINE'] = '1'
import torch
from transformers import pipeline
from score_all_lib import tok, dist
asr = pipeline('automatic-speech-recognition', model='openai/whisper-large-v3-turbo', dtype=torch.float16, device='cuda:0')
def trimmed(p):
    t = p.with_name(p.stem + '-trim.wav')
    if not t.exists():
        subprocess.run([FF, '-v', 'error', '-y', '-i', str(p), '-af', TRIM, '-ac', '1', '-ar', str(SR), str(t)], check=True)
    return t
for i, c, s in list(todo()):
    st = state.setdefault(tkey(c), dict(nseeds=4, takes={}))
    p = cand(i, c, s)
    if str(s) in st['takes'] or not p.exists(): continue
    h = asr({'raw': decode(trimmed(p), 16000), 'sampling_rate': 16000}, generate_kwargs={'language': 'vi', 'task': 'transcribe', 'num_beams': 1})['text'].strip()
    st['takes'][str(s)] = dict(edits=dist(tok(c['text']), tok(h)), asr=h, dur=round(len(decode(trimmed(p))) / SR, 3))
EQUIV = {'vi rút': 'virus', 'vi-rút': 'virus', 'tiểu mỹ': 'tiểu my'}
def norm(s):
    s = s.lower()
    for a, b in EQUIV.items(): s = s.replace(a, b)
    return s
fail = []
for i, c in enumerate(CS):
    st = state.setdefault(tkey(c), dict(nseeds=4, takes={}))
    slot = (CS[i + 1]['s'] if i + 1 < len(CS) else LEN) - c['s']
    for t in st['takes'].values():  # re-score with spelling equivalents Whisper writes differently (virus = vi rút)
        t['edits'] = dist(tok(norm(c['text'])), tok(norm(t['asr'])))
    good = {s: t for s, t in st['takes'].items() if t['edits'] == 0}
    if good:  # among error-free takes prefer the one that fits its slot, then the shortest
        s = min(good, key=lambda s: (good[s]['dur'] > slot, good[s]['dur'])); st['ok'] = s
    else:
        st.pop('ok', None); st['nseeds'] = min(24, len(st['takes']) + 4) if len(st['takes']) >= st['nseeds'] else st['nseeds']
        fail.append((i, c['text'], sorted((t['edits'], t['asr']) for t in st['takes'].values())[:1]))
state_f.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding='utf-8')
for f in fail: print('FAIL', *f)
if fail and '--force' not in sys.argv:
    print('ROUND_NEEDED', len(fail)); sys.exit()

# placement: natural speed only; a line that would collide starts after the previous one ends
dry = np.zeros(int(LEN * SR), np.float32); rows = []; prev_end = 0.
for i, c in enumerate(CS):
    st = state[tkey(c)]
    s = st.get('ok') or min(st['takes'], key=lambda s: st['takes'][s]['edits'])
    w = decode(trimmed(cand(i, c, int(s))))
    start = max(c['s'], prev_end + .08); end = start + len(w) / SR
    a = int(start * SR); b = min(len(dry), a + len(w)); dry[a:b] += w[:b - a]; prev_end = end
    slot_end = CS[i + 1]['s'] if i + 1 < len(CS) else LEN
    rows.append(dict(i=i, text=c['text'], seed=s, edits=st['takes'][s]['edits'], cue_start=c['s'], start=round(start, 3), end=round(end, 3),
                     delay=round(start - c['s'], 3), overrun=round(max(0, end - slot_end), 3), cropped=round(max(0, end - LEN), 3)))
    print(f"{i:2d} delay {start - c['s']:5.2f} overrun {max(0, end - slot_end):5.2f} dur {len(w) / SR:5.2f} slot {slot_end - c['s']:5.2f} | {c['text']}")
dry *= min(1., .95 / max(abs(dry).max(), 1e-9))
sf.write(work / 'dry.wav', dry, SR, subtype='FLOAT')
(work / 'manifest.json').write_text(json.dumps(dict(job=job, ref=REF, speed_change=False, lines=rows), ensure_ascii=False, indent=1), encoding='utf-8')
print('PLACED max delay', max(r['delay'] for r in rows), 'cropped', sum(r['cropped'] for r in rows))
