"""Cross-lingual voice clone test (Chinese actor refs -> Vietnamese lines), dialogue 30 s.
Same cues/refs/fit as the OmniVoice actor-zh run so results are comparable.
  clone-voxcpm venv:   python run_clone.py voxcpm-ref | voxcpm-ultimate
  clone-viterbox venv: python run_clone.py viterbox"""
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from benchlib import RUN, OLD, cues, sha, fit_and_place, Timer
os.environ['HF_HOME'] = 'D:/DuAnKhoiNghiep/DubFlow/repo-tests/runtime/hf-cache'
os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'
os.environ['PATH'] = 'D:/OmniVoice/tools;' + os.environ.get('PATH', '')
import numpy as np, soundfile as sf, torch

variant = sys.argv[1]; names = sys.argv[2].split(',') if len(sys.argv) > 2 else ['dialogue']; SEED = 9527
REFS = {'m': (OLD / 'more-repos/actor-m-reference.wav', '我知道不严重，就是看着不放心。慢点，我扶你。'),
        'f': (OLD / 'more-repos/actor-f-reference.wav', '看你怎么比我还紧张。没事，可以松了。')}
tag = 'actor-zh'
if len(sys.argv) > 3:  # refs.json {sp: {path, text}} e.g. OmniVoice built-in voices
    REFS = {sp: (Path(v['path']), v['text']) for sp, v in json.loads(Path(sys.argv[3]).read_text(encoding='utf-8')).items()}
    tag = Path(sys.argv[3]).parent.name.replace('refs-', '')
torch.cuda.reset_peak_memory_stats()
if variant.startswith('voxcpm'):
    from voxcpm import VoxCPM
    model = VoxCPM.from_pretrained('openbmb/VoxCPM2', load_denoiser=False, optimize=False, cache_dir=os.environ['HF_HOME'])
    SR = model.tts_model.sample_rate if hasattr(model, 'tts_model') else 48000
    def gen(text, ref, reftext):
        kw = dict(reference_wav_path=str(ref)) if variant == 'voxcpm-ref' else dict(prompt_wav_path=str(ref), prompt_text=reftext)
        return np.asarray(model.generate(text=text, cfg_value=2.0, inference_timesteps=10, **kw), np.float32).reshape(-1)
    params = dict(cfg_value=2.0, inference_timesteps=10, mode=variant)
else:
    sys.path.insert(0, 'D:/DuAnKhoiNghiep/DubFlow/repo-tests/viterbox')
    from viterbox import Viterbox
    model = Viterbox.from_pretrained('cuda'); SR = model.sr
    def gen(text, ref, reftext):
        return model.generate(text=text, language='vi', audio_prompt=str(ref), exaggeration=0.6, cfg_weight=0.5, split_sentences=False).detach().float().cpu().numpy().reshape(-1)
    params = dict(exaggeration=0.6, cfg_weight=0.5, temperature=0.8)

for name in names:
    work = RUN / f'{variant}-{tag}-{name}'; (work / 'lines').mkdir(parents=True, exist_ok=True)
    files, manifest = [], []
    for i, c in enumerate(cues(name)):
        ref, reftext = REFS[c['speaker']]
        key = sha(dict(text=c['text'], ref=sha(Path(ref)), seed=SEED, params=params, engine=variant))
        dest = work / 'lines' / f'{i:03d}-{key}.wav'; took = None
        if not dest.exists():
            torch.manual_seed(SEED); np.random.seed(SEED)
            with Timer() as tm:
                w = gen(c['text'], ref, reftext)
            assert len(w) and np.isfinite(w).all()
            sf.write(dest, w * min(1., .9 / max(float(abs(w).max()), 1e-9)), SR, subtype='FLOAT'); took = tm.s
            print(variant, name, i, c['speaker'], f'{tm.s}s', c['text'], flush=True)
        files.append(dest)
        manifest.append(dict(i=i, speaker=c['speaker'], ref=str(ref), ref_hash=sha(Path(ref)), text=c['text'], seed=SEED, cache_key=key, file=str(dest), synth_seconds=took))
    rows = fit_and_place(name, files, work, trim=True)
    (work / 'manifest.json').write_text(json.dumps(dict(engine=variant, params=params, refs=tag, peak_vram_mb=round(torch.cuda.max_memory_allocated() / 2**20), lines=manifest, placements=rows), ensure_ascii=False, indent=2), encoding='utf-8')
    print('DONE', variant, name, 'peak VRAM MB', round(torch.cuda.max_memory_allocated() / 2**20), 'overlaps', sum(r['overlap_next_s'] > 0 for r in rows), flush=True)
