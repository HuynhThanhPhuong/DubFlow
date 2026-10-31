"""VieNeu v3 Turbo per-cue with fixed presets (m=Minh Triết, f=Ngọc Linh, chosen 27/10).
Also writes shared reference clips (ref-m.wav / ref-f.wav + text) so other engines clone the same voices."""
import json, os, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from benchlib import RUN, FF, cues, sha, fit_and_place, Timer
os.environ['PATH'] = 'D:/OmniVoice/tools;' + os.environ.get('PATH', '')
import numpy as np, soundfile as sf
from vieneu import Vieneu

VOICE = {'m': 'Minh Triết', 'f': 'Ngọc Linh'}
REF_TEXT = {'m': 'Hôm nay trời đẹp quá, mình ra ngoài đi dạo một chút nha. Em có muốn uống gì không, để anh mua cho.',
            'f': 'Anh đừng lo cho em quá như vậy. Em không sao đâu, chỉ hơi mệt một chút thôi mà.'}
TAG = 'young'
tts = Vieneu(mode='v3turbo', device='cpu', backend='onnx', precision='int8', threads=4)
SRV = int(getattr(tts, 'sample_rate', 48000))
refdir = RUN / f'refs-{TAG}'; refdir.mkdir(exist_ok=True)
for sp in 'mf':
    p = refdir / f'ref-{sp}.wav'
    if not p.exists():
        sf.write(p, np.asarray(tts.infer(REF_TEXT[sp], voice=VOICE[sp]), np.float32).reshape(-1), SRV)
(refdir / 'refs.json').write_text(json.dumps({sp: dict(voice=VOICE[sp], path=str(refdir / f'ref-{sp}.wav'), text=REF_TEXT[sp], hash=sha(refdir / f'ref-{sp}.wav')) for sp in 'mf'}, ensure_ascii=False, indent=2), encoding='utf-8')

for name in sys.argv[1:] or ['dialogue', 'review']:
    work = RUN / f'VieNeu-{TAG}-{name}'; (work / 'lines').mkdir(parents=True, exist_ok=True)
    files, manifest = [], []
    for i, c in enumerate(cues(name)):
        v = VOICE[c['speaker']]
        key = sha(dict(text=c['text'], voice=v, engine='vieneu-3.8.3-v3turbo-int8'))
        dest = work / 'lines' / f'{i:02d}-{key}.wav'; took = None
        if not dest.exists():
            with Timer() as tm:
                w = np.asarray(tts.infer(c['text'], voice=v), np.float32).reshape(-1)
            if not len(w):
                raise ValueError('Empty VieNeu audio')
            sf.write(dest, w, SRV); took = tm.s; print(name, i, v, f'{tm.s}s', c['text'], flush=True)
        files.append(dest)
        manifest.append(dict(i=i, speaker=c['speaker'], voice=v, text=c['text'], text_hash=sha(c['text']), cache_key=key, file=str(dest), synth_seconds=took))
    rows = fit_and_place(name, files, work)
    (work / 'manifest.json').write_text(json.dumps(dict(engine='VieNeu-TTS v3 Turbo', sdk='vieneu==3.8.3', device='cpu onnx int8', voices=VOICE, style='none (deprecated in v3 Turbo)', lines=manifest, placements=rows), ensure_ascii=False, indent=2), encoding='utf-8')
    print('DONE', name, 'max rate', max(r['speed_rate'] for r in rows), 'overlaps', sum(r['overlap_next_s'] > 0 for r in rows), flush=True)
