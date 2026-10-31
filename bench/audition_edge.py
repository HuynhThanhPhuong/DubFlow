"""Edge-TTS audition (online: sends only the Vietnamese text). Beep between voices; order in audition-edge.json."""
import asyncio, json, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from benchlib import RUN, FF
import numpy as np, soundfile as sf, edge_tts

LINES = {'m': 'Em nhìn gì thế? Từ từ thôi, anh đỡ em.', 'f': 'Nhìn anh đó. Sao anh còn lo hơn cả em vậy?'}
CAND = {'m': [('vi-VN-NamMinhNeural', '+0%', '+0Hz'), ('vi-VN-NamMinhNeural', '+6%', '+8Hz'), ('vi-VN-NamMinhNeural', '+8%', '+15Hz'),
              ('en-US-AndrewMultilingualNeural', '+0%', '+0Hz'), ('en-US-BrianMultilingualNeural', '+0%', '+0Hz'), ('en-AU-WilliamMultilingualNeural', '+0%', '+0Hz'), ('ko-KR-HyunsuMultilingualNeural', '+0%', '+0Hz')],
        'f': [('vi-VN-HoaiMyNeural', '+0%', '+0Hz'), ('vi-VN-HoaiMyNeural', '+6%', '+8Hz'), ('vi-VN-HoaiMyNeural', '+8%', '+15Hz'),
              ('en-US-AvaMultilingualNeural', '+0%', '+0Hz'), ('en-US-EmmaMultilingualNeural', '+0%', '+0Hz'), ('pt-BR-ThalitaMultilingualNeural', '+0%', '+0Hz')]}
SR = 24000
d = RUN / 'audition'; tmp = d / 'edge-tmp'; tmp.mkdir(parents=True, exist_ok=True)

async def main():
    order = {}
    for sp, cands in CAND.items():
        beep = (0.2 * np.sin(2 * np.pi * 880 * np.arange(int(.15 * SR)) / SR)).astype(np.float32); gap = np.zeros(int(.5 * SR), np.float32)
        parts, t, rows = [], 0., []
        for k, (v, rate, pitch) in enumerate(cands):
            mp3 = tmp / f'{sp}{k}.mp3'
            for attempt in range(5):
                try:
                    await edge_tts.Communicate(LINES[sp], v, rate=rate, pitch=pitch).save(str(mp3)); break
                except edge_tts.exceptions.NoAudioReceived:
                    await asyncio.sleep(2 + 2 * attempt)
            else:
                print('NO AUDIO after 5 tries:', v); continue
            w = np.frombuffer(subprocess.check_output([FF, '-v', 'error', '-i', str(mp3), '-ac', '1', '-ar', str(SR), '-f', 'f32le', '-']), np.float32)
            rows.append(dict(n=len(rows) + 1, voice=v, rate=rate, pitch=pitch, start_s=round(t, 1)))
            parts += [beep, gap, w, gap]; t += (len(beep) + 2 * len(gap) + len(w)) / SR
        sf.write(d / f'edge-{sp}.wav', np.concatenate(parts), SR)
        subprocess.run([FF, '-v', 'error', '-y', '-i', str(d / f'edge-{sp}.wav'), '-b:a', '160k', str(d / f'edge-{sp}.mp3')], check=True)
        order[f'edge-{sp}'] = rows
    (d / 'audition-edge.json').write_text(json.dumps(order, indent=2), encoding='utf-8')
    for k, rows in order.items():
        for r in rows: print(k, r)
asyncio.run(main())
