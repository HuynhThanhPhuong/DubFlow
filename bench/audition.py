"""Voice audition: every candidate reads the same two lines; one MP3 per engine+gender,
a beep between voices, order written to audition-order.json. Usage:
  VietVoice venv: python audition.py vietvoice
  runtime venv:   python audition.py vieneu"""
import json, os, subprocess, sys, tarfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from benchlib import RUN, FF
import numpy as np, soundfile as sf
os.environ['PATH'] = 'D:/OmniVoice/tools;' + os.environ.get('PATH', '')
LINES = {'m': 'Em nhìn gì thế? Từ từ thôi, anh đỡ em.', 'f': 'Nhìn anh đó. Sao anh còn lo hơn cả em vậy?'}
SR = 24000
OUTD = RUN / 'audition'; OUTD.mkdir(exist_ok=True)

def bundle(name, clips):
    beep = (0.2 * np.sin(2 * np.pi * 880 * np.arange(int(.15 * SR)) / SR)).astype(np.float32)
    gap = np.zeros(int(.5 * SR), np.float32)
    parts = []
    for w in clips:
        parts += [beep, gap, w.astype(np.float32), gap]
    wav = OUTD / f'{name}.wav'; sf.write(wav, np.concatenate(parts), SR)
    subprocess.run([FF, '-v', 'error', '-y', '-i', str(wav), '-b:a', '160k', str(OUTD / f'{name}.mp3')], check=True)

order_file = OUTD / 'audition-order.json'
order = json.loads(order_file.read_text(encoding='utf-8')) if order_file.exists() else {}
engine = sys.argv[1]
if engine == 'vietvoice':
    import onnxruntime as ort
    lib = 'D:/OmniVoice/venv/Lib/site-packages/torch/lib'; os.add_dll_directory(lib); ort.preload_dlls(directory=lib)
    from vietvoicetts import ModelConfig, TTSApi
    MODEL = Path('D:/DuAnKhoiNghiep/DubFlow/VietVoice-TTS/models')
    CAND = {'m': [139, 38, 47, 63, 78, 101, 124, 168, 193], 'f': [159, 7, 14, 37, 62, 85, 132, 169, 170]}
    t = tarfile.open(MODEL / 'model-bin.pt'); meta = json.load(t.extractfile('audio_metadata.json'))
    with TTSApi(ModelConfig(model_cache_dir=str(MODEL), speed=1.0, intra_op_num_threads=4, inter_op_num_threads=1)) as api:
        for sp, ids in CAND.items():
            clips = []
            for idx in ids:
                ref = RUN / 'vietvoice-refs' / f'reference-{idx}.wav'
                if not ref.exists():
                    ref.write_bytes(t.extractfile('cleaned_audios/' + meta[idx]['file_name']).read())
                ort.set_seed(9527)
                x, _ = api.synthesize(LINES[sp], reference_audio=str(ref), reference_text=meta[idx]['text'])
                x = x.astype(np.float32).reshape(-1) / (32768 if np.issubdtype(x.dtype, np.integer) else 1)
                clips.append(x * min(1., .75 / max(float(abs(x).max()), 1e-9)))
            bundle(f'vietvoice-{sp}', clips)
            order[f'vietvoice-{sp}'] = [dict(n=k + 1, ref_id=i, gender=meta[i]['gender'], area=meta[i]['area'], emotion=meta[i]['emotion'], source=meta[i]['name_character']) for k, i in enumerate(ids)]
elif engine == 'vieneu':
    from vieneu import Vieneu
    tts = Vieneu(mode='v3turbo', device='cpu', backend='onnx', precision='int8', threads=4)
    voices = tts.list_preset_voices()
    print(voices)
    clips = {'m': [], 'f': []}; names = {'m': [], 'f': []}
    for desc, vid in voices:
        sp = 'f' if any(k in desc.lower() for k in ['nữ', 'female', 'woman']) else 'm'
        w = np.asarray(tts.infer(LINES[sp], voice=vid), dtype=np.float32).reshape(-1)
        sr = getattr(tts, 'sample_rate', 48000)
        if sr != SR:
            w = np.frombuffer(subprocess.run([FF, '-v', 'error', '-f', 'f32le', '-ar', str(sr), '-ac', '1', '-i', '-', '-ar', str(SR), '-f', 'f32le', '-'], input=w.tobytes(), capture_output=True, check=True).stdout, np.float32)
        clips[sp].append(w); names[sp].append(dict(n=len(names[sp]) + 1, voice=vid, desc=desc))
    for sp in 'mf':
        if clips[sp]:
            bundle(f'vieneu-{sp}', clips[sp]); order[f'vieneu-{sp}'] = names[sp]
order_file.write_text(json.dumps(order, ensure_ascii=False, indent=2), encoding='utf-8')
print('DONE', engine)
