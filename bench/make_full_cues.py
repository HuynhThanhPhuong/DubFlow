"""Build full-length cue files + OmniVoice voice refs (copied to WAV; D:/OmniVoice untouched).
Translations: review = earlier hand-corrected 71 s file; dialogue = first 30 s reviewed cues +
Claude's in-session translation of Whisper zh (checked against burned-in Chinese subs on sampled frames)."""
import json, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from benchlib import RUN, OLD, FF, sha
full = RUN / 'full'
review = json.loads(Path('D:/Codex/2026-10-26/pha/work/dubflow-test2/translation.json').read_text(encoding='utf-8'))
(full / 'review-full-cues.json').write_text(json.dumps([dict(s=x['s'], e=x['e'], speaker='m', text=x['text']) for x in review], ensure_ascii=False, indent=1), encoding='utf-8')
first = json.loads((OLD / 'dialogue-cues.json').read_text(encoding='utf-8'))
extra = [dict(s=s, e=e, speaker=sp, text=t) for s, e, sp, t in json.loads((full / 'dialogue-full-extra.json').read_text(encoding='utf-8'))]
(full / 'dialogue-full-cues.json').write_text(json.dumps([dict(s=c['s'], e=c['e'], speaker=c['speaker'], text=c['text']) for c in first] + extra, ensure_ascii=False, indent=1), encoding='utf-8')

VOICES = {'m': 'anh-tuan', 'f': 'thuy-trang', 't': 'ke-chuyen-xom', 's': 'series'}
refdir = RUN / 'refs-omni'; refdir.mkdir(exist_ok=True); refs = {}
for sp, vid in VOICES.items():
    meta = json.loads(Path(f'D:/OmniVoice/voices/{vid}.json').read_text(encoding='utf-8'))
    dest = refdir / f'{vid}.wav'
    subprocess.run([FF, '-v', 'error', '-y', '-i', meta['ref_audio'], '-ac', '1', '-ar', '24000', str(dest)], check=True)
    refs[sp] = dict(voice=meta.get('name') or vid, path=str(dest), text=meta['ref_text'], hash=sha(dest))
(refdir / 'refs.json').write_text(json.dumps(refs, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(refs, ensure_ascii=False, indent=1))
print('cues', len(review), len(first) + len(extra))
