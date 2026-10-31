"""VoiceStudio/OmniVoice A/B on the dialogue clip: same cues, seed, steps;
only the reference changes (actor Chinese refs vs clean Vietnamese refs 139/159)."""
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from benchlib import RUN, OLD, REFS, cues, sha, fit_and_place, Timer
os.environ['OMNIVOICE_DATA_DIR'] = 'D:/DuAnKhoiNghiep/DubFlow/repo-tests/runtime/voicestudio-data'
os.environ['HF_HOME'] = 'D:/OmniVoice/cache/hf'; os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['PATH'] = 'D:/OmniVoice/tools;' + os.environ.get('PATH', '')
sys.path.insert(0, 'D:/DuAnKhoiNghiep/DubFlow/repo-tests/VoiceStudio')
sys.path.insert(0, 'D:/DuAnKhoiNghiep/DubFlow/repo-tests/VoiceStudio/backend')
import numpy as np, soundfile as sf, torch
from omnivoice import OmniVoice
from services.tts_backend import OmniVoiceBackend
from services.audio_dsp import trim_speech_padding

SEED, STEPS = 9527, 16
old = json.loads((REFS / 'references.json').read_text(encoding='utf-8'))
VARIANTS = {
    'actor-zh': {'m': (OLD / 'more-repos/actor-m-reference.wav', '我知道不严重，就是看着不放心。慢点，我扶你。'),
                 'f': (OLD / 'more-repos/actor-f-reference.wav', '看你怎么比我还紧张。没事，可以松了。')},
    'clean-vi': {'m': (REFS / 'reference-139.wav', old['139']['text']), 'f': (REFS / 'reference-159.wav', old['159']['text'])},
}
if len(sys.argv) > 1:  # e.g. refs-young/refs.json -> single variant named after the folder tag
    ext = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    VARIANTS = {Path(sys.argv[1]).parent.name.replace('refs-', ''): {sp: (Path(v['path']), v['text']) for sp, v in ext.items()}}
NAMES = sys.argv[2:] or ['dialogue']
model = OmniVoice.from_pretrained('k2-fsa/OmniVoice', device_map='cuda:0', dtype=torch.float16)
backend = OmniVoiceBackend(model=model)
torch.cuda.reset_peak_memory_stats()
for variant, refs, name in [(v, r, n) for v, r in VARIANTS.items() for n in NAMES]:
    work = RUN / f'VoiceStudio-OmniVoice-{variant}-{name}'; (work / 'lines').mkdir(parents=True, exist_ok=True)
    files, manifest = [], []
    for i, c in enumerate(cues(name)):
        ref, reftext = refs[c['speaker']]
        key = sha(dict(text=c['text'], ref=sha(Path(ref)), reftext=reftext, seed=SEED, steps=STEPS, engine='voicestudio-12fd194'))
        raw = work / 'lines' / f'{i:02d}-{key}.wav'; trimmed = work / 'lines' / f'{i:02d}-{key}-trim.wav'
        took = None
        if not raw.exists():
            torch.manual_seed(SEED)
            with Timer() as tm:
                w = backend.generate(c['text'], language='Vietnamese', ref_audio=str(ref), ref_text=reftext, num_step=STEPS, speed=1., denoise=False, postprocess_output=False)
            a = torch.as_tensor(w).detach().float().cpu().reshape(-1)
            sf.write(raw, a.numpy(), backend.sample_rate, subtype='FLOAT')
            sf.write(trimmed, trim_speech_padding(a, backend.sample_rate).numpy(), backend.sample_rate, subtype='FLOAT')
            took = tm.s; print(variant, i, c['speaker'], f'{tm.s}s', c['text'], flush=True)
        files.append(trimmed)
        manifest.append(dict(i=i, speaker=c['speaker'], ref=str(ref), ref_hash=sha(Path(ref)), text=c['text'], text_hash=sha(c['text']), seed=SEED, steps=STEPS, cache_key=key, raw=str(raw), placed_from=str(trimmed), synth_seconds=took))
    rows = fit_and_place(name, files, work)
    (work / 'manifest.json').write_text(json.dumps(dict(engine='OmniVoice via VoiceStudio OmniVoiceBackend', repo_commit='12fd1944f88dba7a061eb0977a74fcb6cbd984d0', model='k2-fsa/OmniVoice (D:/OmniVoice/cache/hf)', device='cuda:0 fp16', peak_vram_mb=round(torch.cuda.max_memory_allocated() / 2**20), variant=variant, lines=manifest, placements=rows), ensure_ascii=False, indent=2), encoding='utf-8')
    print('DONE', variant, name, flush=True)
