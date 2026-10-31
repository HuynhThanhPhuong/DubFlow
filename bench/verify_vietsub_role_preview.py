import hashlib
import json
import subprocess
from pathlib import Path
import numpy as np
import pysubs2

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'bench/runs/20261030/vietsub-role-preview'
VIDEO=ROOT/'outputs/DubFlow-vietsub-xung-ho-ban-thu-59s-20261030.mp4'
SOURCE=ROOT/'data/jobs/76b9aa4c51744e2783633fbc9e50fde1/source.mp4'
FF='D:/OmniVoice/tools/ffmpeg.exe'
FP='D:/OmniVoice/tools/ffprobe.exe'
plan=json.loads((OUT/'edited-cues.json').read_text(encoding='utf-8'))
subs=pysubs2.load(str(OUT/'preview.vi.srt'),encoding='utf-8')
assert len(subs)==len(plan)==22
assert sorted(i for c in plan for i in c['source_ids'])==[f'ASR_{i:04d}' for i in range(1,24)]
for i,c in enumerate(subs):
    assert c.start<c.end and c.end<=59000 and c.plaintext.strip()
    if i:
        assert subs[i-1].end<=c.start
    assert not any('\u4e00'<=letter<='\u9fff' for letter in c.plaintext)
probe=json.loads(subprocess.check_output([FP,'-v','error','-show_streams','-show_format','-of','json',str(VIDEO)]))
v=next(s for s in probe['streams'] if s['codec_type']=='video')
a=next(s for s in probe['streams'] if s['codec_type']=='audio')
assert (v['width'],v['height'])==(1080,1920)
assert abs(float(probe['format']['duration'])-59)<.1
decode=subprocess.run([FF,'-v','error','-i',str(VIDEO),'-map','0:v:0','-map','0:a:0','-f','null','-'],capture_output=True)
assert decode.returncode==0 and not decode.stderr.strip(),decode.stderr.decode(errors='replace')
def audio(path):
    return np.frombuffer(subprocess.check_output([FF,'-v','error','-i',str(path),'-t','59','-vn','-ac','1','-ar','16000','-f','f32le','-']),np.float32)
original,final=audio(SOURCE),audio(VIDEO)
n=min(len(original),len(final));corr=float(np.corrcoef(original[:n],final[:n])[0,1])
assert corr>.98,corr
assert hashlib.file_digest(SOURCE.open('rb'),'sha256').hexdigest()=='3c8f36d826c1fccf93fe64555d3e1f1fa68125980345ffa0eff3acc006cc48fa'
for t in [3,14,35,42.8,50.8,52,54,57]:
    subprocess.run([FF,'-hide_banner','-loglevel','error','-y','-ss',str(t),'-i',str(VIDEO),'-frames:v','1',str(OUT/f'final-encoded-{t:g}.jpg')],check=True)
report={'output':str(VIDEO),'duration':float(probe['format']['duration']),'size_bytes':VIDEO.stat().st_size,
    'resolution':[v['width'],v['height']],'video_codec':v['codec_name'],'audio_codec':a['codec_name'],
    'subtitle_cues':22,'source_ids_covered':23,'cue_overlaps':0,'full_file_decode_errors':0,
    'original_audio_correlation_mono16k':round(corr,6),'audio_check_is_not_human_listening':True,
    'source_unchanged':True,'translation':'manual edited draft for user preview; not automatic translation benchmark',
    'provisional_role_choices_not_approved_for_production':True,'erasure_quality':'sample frames exported for visual review; not certified perfect over all frames',
    'sha256':hashlib.file_digest(VIDEO.open('rb'),'sha256').hexdigest()}
(OUT/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
