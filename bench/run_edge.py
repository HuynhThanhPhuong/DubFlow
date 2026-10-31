"""Edge-TTS (same engine pyVideoTrans uses) per cue, tuned younger: pitch/rate shift.
Online: sends only Vietnamese text. Usage: python run_edge.py [--rate +5%] [--pitch +12Hz]"""
import argparse, asyncio, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from benchlib import RUN, cues, sha, fit_and_place, Timer
import edge_tts
import numpy as np

p = argparse.ArgumentParser(); p.add_argument('--rate', default='+5%'); p.add_argument('--pitch', default='+12Hz'); p.add_argument('--tag', default='young')
p.add_argument('--match-span', action='store_true', help='re-synthesize each line with its own Edge rate so speech fills the source cue span (mouth movement), clamped -15%..+30%')
args = p.parse_args()
VOICE = {'m': 'vi-VN-NamMinhNeural', 'f': 'vi-VN-HoaiMyNeural'}

import subprocess
from benchlib import FF, TRIM, decode, SR

def speech_len(mp3):
    return len(np.frombuffer(subprocess.check_output([FF, '-v', 'error', '-i', str(mp3), '-af', TRIM, '-ac', '1', '-ar', str(SR), '-f', 'f32le', '-']), np.float32)) / SR

async def synth(text, voice, dest, rate=None):
    for attempt in range(12):  # Edge intermittently returns no audio (server-side throttling)
        try:
            await edge_tts.Communicate(text, voice, rate=rate or args.rate, pitch=args.pitch).save(str(dest)); return
        except edge_tts.exceptions.NoAudioReceived:
            await asyncio.sleep(min(30, 3 + 3 * attempt))
    raise RuntimeError(f'Edge returned no audio: {voice} {text}')

async def main():
    for name in ['dialogue', 'review']:
        work = RUN / f'Edge-{args.tag}-{name}'; (work / 'lines').mkdir(parents=True, exist_ok=True)
        files, manifest = [], []
        for i, c in enumerate(cues(name)):
            v = VOICE[c['speaker']]; key = sha(dict(text=c['text'], voice=v, rate=args.rate, pitch=args.pitch))
            dest = work / 'lines' / f'{i:02d}-{key}.mp3'; took = None
            if not dest.exists() or dest.stat().st_size == 0:
                with Timer() as tm:
                    await synth(c['text'], v, dest)
                took = tm.s
            line_rate = args.rate
            if args.match_span:
                base = 1 + int(args.rate.strip('%')) / 100
                want = round(((base * speech_len(dest) / (c['e'] - c['s'])) - 1) * 100)
                want = max(-15, min(30, want)) or 1  # Edge returns no audio for "+0%"
                line_rate = f'{want:+d}%'
                key2 = sha(dict(text=c['text'], voice=v, rate=line_rate, pitch=args.pitch))
                dest2 = work / 'lines' / f'{i:02d}-{key2}-span.mp3'
                if not dest2.exists() or dest2.stat().st_size == 0:
                    await synth(c['text'], v, dest2, line_rate)
                dest, key = dest2, key2
            files.append(dest); manifest.append(dict(i=i, speaker=c['speaker'], voice=v, rate=line_rate, pitch=args.pitch, text=c['text'], cache_key=key, file=str(dest), synth_seconds=took))
        rows = fit_and_place(name, files, work, trim=True)
        (work / 'manifest.json').write_text(json.dumps(dict(engine='Edge-TTS 7.3.1 (online, text only)', voices=VOICE, rate=args.rate, pitch=args.pitch, note='Edge has no Southern Vietnamese voice; younger feel via pitch/rate only', lines=manifest, placements=rows), ensure_ascii=False, indent=2), encoding='utf-8')
        print('DONE', name, 'max rate', max(r['speed_rate'] for r in rows), 'overlaps', sum(r['overlap_next_s'] > 0 for r in rows), flush=True)
asyncio.run(main())
