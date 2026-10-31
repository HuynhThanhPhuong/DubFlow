"""Mix dry voice with the shared Demucs bed (same settings as the earlier 4-repo render) and render 30s MP4s."""
import json, subprocess, sys, textwrap
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from benchlib import RUN, OLD, OUT, FF, SR, VIDEOS, LENGTH, cues, background
import numpy as np, soundfile as sf
sys.path.insert(0, 'D:/DuAnKhoiNghiep/DubFlow/repo-tests/rtsubs/server')
from rtsubs.config import Settings
from rtsubs.mixer import mix_chunk
settings = Settings(); settings.tts_gain = .85; settings.bgm_gain = .8
JOBS = [('VietVoice', 'review', 'VietVoice | ghim ref 139'), ('VietVoice', 'dialogue', 'VietVoice | nam 139 / nu 159'),
        ('VoiceStudio-OmniVoice-actor-zh', 'dialogue', 'OmniVoice | ref dien vien Trung'), ('VoiceStudio-OmniVoice-clean-vi', 'dialogue', 'OmniVoice | ref Viet 139/159')]
if sys.argv[1:] == ['young']:
    JOBS = [(e, n, f'{lbl} | nam Minh Triet / nu Ngoc Linh') for e, lbl in [('VieNeu-young', 'VieNeu'), ('VietVoice-young', 'VietVoice clone'), ('VoiceStudio-OmniVoice-young', 'OmniVoice clone')] for n in ['review', 'dialogue']]
if sys.argv[1:] == ['edge']:
    JOBS = [('Edge-young', n, 'Edge-TTS (pyVideoTrans engine) | tre hoa: pitch +12Hz, rate +5%') for n in ['review', 'dialogue']]
if sys.argv[1:] == ['span']:
    JOBS = [('Edge-span', n, 'Edge-TTS | tre hoa + khop do dai khau hinh') for n in ['review', 'dialogue']]
if sys.argv[1:2] == ['clone']:
    labels = {'viterbox': 'Viterbox clone giong dien vien', 'voxcpm-ref': 'VoxCPM2 clone (ref) giong dien vien', 'voxcpm-ultimate': 'VoxCPM2 ultimate clone giong dien vien'}
    JOBS = [(f'{v}-actor-zh', 'dialogue', labels[v]) for v in sys.argv[2:]]
if sys.argv[1:2] == ['full']:
    labels = {'viterbox': 'Viterbox', 'voxcpm-ref': 'VoxCPM2 (ref)', 'voxcpm-ultimate': 'VoxCPM2 ultimate'}
    JOBS = [(f'{v}-omni', n, f'{labels[v]} | giong OmniVoice: Anh Tuan / Thuy Trang') for v in sys.argv[2:] for n in ['review-full', 'dialogue-full']]
if sys.argv[1:] == ['bestof']:
    JOBS = [('voxcpm-ultimate-bestof', 'dialogue', 'VoxCPM2 ultimate | giong goc dien vien | chon ban it loi nhat / 4')]
if sys.argv[1:] == ['orig30']:
    JOBS = [('voxcpm-ultimate-origreview', 'review', 'VoxCPM2 ultimate | clone giong goc video')]
if sys.argv[1:] == ['orig']:
    JOBS = [('voxcpm-ultimate-origreview', 'review-full', 'VoxCPM2 ultimate | clone giong goc video'), ('voxcpm-ultimate-orig', 'dialogue-full', 'VoxCPM2 ultimate | clone giong goc video')]
header =(OLD / 'pyVideoTrans-review/captions.ass').read_text(encoding='utf-8-sig').split('[Events]')[0] + '[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
ts = lambda t: (lambda cs: f'{cs // 360000}:{cs // 6000 % 60:02}:{cs // 100 % 60:02}.{cs % 100:02}')(round(t * 100))
report = []
for engine, name, label in JOBS:
    work = RUN / f'{engine}-{name}'
    L = LENGTH.get(name, 30.0)
    if not (work / 'manifest.json').exists():
        print('SKIP (not generated yet)', work.name, flush=True); continue
    dry, _ = sf.read(work / 'dry.wav', dtype='float32'); bed, _ = sf.read(background(name), dtype='float32')
    n = min(len(dry), len(bed)); mixed = mix_chunk(bed[:n], [(0., dry[:n])], settings); sf.write(work / 'dub.wav', mixed, SR, subtype='PCM_24')
    ev = [f'Dialogue: 1,0:00:00.00,{ts(L)},Label,,0,0,0,,{label}'] + [f'Dialogue: 0,{ts(c["s"])},{ts(c["e"])},Default,,0,0,0,,{{\\pos(960,1023)}}' + '\\N'.join(textwrap.wrap(c['text'], 70)) for c in cues(name)]
    (work / 'captions.ass').write_text(header + '\n'.join(ev), encoding='utf-8-sig')
    dest = OUT / (f'DubFlow-20261027-{engine}-{name}.mp4' if name.endswith('-full') else f'DubFlow-20261027-{engine}-{name}-30s.mp4')
    cmd = [FF, '-hide_banner', '-y', '-i', VIDEOS[name], '-i', str(work / 'dub.wav'), '-map', '0:v:0', '-map', '1:a:0', '-t', str(L), '-vf', 'scale=1920:1080,drawbox=x=0:y=970:w=iw:h=110:color=black:t=fill,ass=captions.ass', '-af', 'loudnorm=I=-17:TP=-2.5:LRA=11', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '21', '-threads', '4', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-movflags', '+faststart', str(dest)]
    with (work / 'render.log').open('w', encoding='utf-8') as log:
        subprocess.run(cmd, cwd=work, stdout=log, stderr=log, check=True)
    report.append(dict(engine=engine, type=name, output=str(dest), peak_before_loudnorm=float(np.abs(mixed).max())))
    print('RENDERED', dest, flush=True)
(RUN / f'render-report{"-" + "-".join(sys.argv[1:]) if sys.argv[1:] else ""}.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
