"""VietVoice-TTS per-cue synthesis with pinned reference IDs (m=139, f=159).
Usage: python run_vietvoice.py [review|dialogue] [--speed 1.0] [--seed 9527]"""
import argparse, json, os, sys, tarfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from benchlib import RUN, cues, sha, fit_and_place, Timer
os.environ['PATH'] = 'D:/OmniVoice/tools;' + os.environ.get('PATH', '')
import numpy as np, soundfile as sf, onnxruntime as ort

p = argparse.ArgumentParser()
p.add_argument('names', nargs='*', default=['dialogue', 'review'])
p.add_argument('--speed', type=float, default=1.0)
p.add_argument('--seed', type=int, default=9527)
p.add_argument('--refs', help='refs.json {m:{path,text,voice},f:{...}} to clone instead of packaged IDs')
p.add_argument('--tag', default='')
args = p.parse_args()

lib = 'D:/OmniVoice/venv/Lib/site-packages/torch/lib'
os.add_dll_directory(lib); ort.preload_dlls(directory=lib)
from vietvoicetts import ModelConfig, TTSApi

MODEL = Path('D:/DuAnKhoiNghiep/DubFlow/VietVoice-TTS/models')
PIN = {'m': 139, 'f': 159}
refdir = RUN / 'vietvoice-refs'; refdir.mkdir(exist_ok=True)
with tarfile.open(MODEL / 'model-bin.pt') as t:
    meta = json.load(t.extractfile('audio_metadata.json'))
    refs = {}
    for sp, idx in PIN.items():
        path = refdir / f'reference-{idx}.wav'
        if not path.exists():
            path.write_bytes(t.extractfile('cleaned_audios/' + meta[idx]['file_name']).read())
        refs[sp] = dict(id=idx, path=path, text=meta[idx]['text'], hash=sha(path), gender=meta[idx]['gender'], emotion=meta[idx]['emotion'])
if args.refs:
    ext = json.loads(Path(args.refs).read_text(encoding='utf-8'))
    refs = {sp: dict(id=v['voice'], path=Path(v['path']), text=v['text'], hash=sha(Path(v['path'])), gender=sp, emotion='n/a') for sp, v in ext.items()}
model_fp = dict(size=(MODEL / 'model-bin.pt').stat().st_size, mtime=int((MODEL / 'model-bin.pt').stat().st_mtime))

cfg = ModelConfig(model_cache_dir=str(MODEL), speed=args.speed, min_target_duration=0.5, max_chunk_duration=25.0, intra_op_num_threads=4, inter_op_num_threads=1)
with TTSApi(cfg) as api:
    for name in args.names:
        work = RUN / ('VietVoice-' + (args.tag + '-' if args.tag else '') + name); (work / 'lines').mkdir(parents=True, exist_ok=True)
        files, manifest = [], []
        for i, c in enumerate(cues(name)):
            r = refs[c['speaker']]
            key = sha(dict(text=c['text'], ref=r['id'], ref_hash=r['hash'], seed=args.seed, speed=args.speed, model=model_fp, engine='vietvoice-d4e8a22'))
            dest = work / 'lines' / f'{i:02d}-{key}.wav'
            took = None
            if not dest.exists():
                ort.set_seed(args.seed)
                with Timer() as tm:
                    x, sr = api.synthesize(c['text'], reference_audio=str(r['path']), reference_text=r['text'])
                x = x.astype(np.float32).reshape(-1) / (32768 if np.issubdtype(x.dtype, np.integer) else 1)
                assert np.isfinite(x).all()
                x -= x.mean(); x *= min(1., .75 / max(float(abs(x).max()), 1e-9))
                sf.write(dest, x, 24000, subtype='FLOAT'); took = tm.s
                print(name, i, c['speaker'], f'{tm.s}s', c['text'], flush=True)
            files.append(dest)
            manifest.append(dict(i=i, speaker=c['speaker'], ref_id=r['id'], ref_hash=r['hash'], text=c['text'], text_hash=sha(c['text']), seed=args.seed, speed=args.speed, cache_key=key, file=str(dest), synth_seconds=took))
        rows = fit_and_place(name, files, work)
        (work / 'manifest.json').write_text(json.dumps(dict(engine='VietVoice-TTS', repo_commit='d4e8a22525437fc976ee9bc4dfd41ceb4b311248', model=str(MODEL / 'model-bin.pt'), model_fp=model_fp, device='onnxruntime ' + ','.join(ort.get_available_providers()), pinned_refs={k: dict(id=v['id'], hash=v['hash'], gender=v['gender'], emotion=v['emotion']) for k, v in refs.items()}, emotion_control='none (fixed ref per speaker; emotion not switched)', lines=manifest, placements=rows), ensure_ascii=False, indent=2), encoding='utf-8')
        print('DONE', name, 'max rate', max(r['speed_rate'] for r in rows), 'overlaps', sum(r['overlap_next_s'] > 0 for r in rows), flush=True)
