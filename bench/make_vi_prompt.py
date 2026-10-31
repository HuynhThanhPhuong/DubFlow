"""Vietnamese continuation prompt for VoxCPM2 'mix' mode: three verified (0-edit) 'Ke chuyen xom'
takes from the thuyet minh run, joined with short pauses; prompt text = their exact script."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from benchlib import RUN, SR, decode, sha
import numpy as np, soundfile as sf
L = {l['i']: l for l in json.loads((RUN / 'v60/tmr/manifest.json').read_text(encoding='utf-8'))['lines']}
parts, texts = [], []
for i in [21, 0, 14]:
    p = next((RUN / 'v60/tmr/lines').glob(f"{i:03d}-*-s{L[i]['seed']}-trim.wav"))
    parts += [decode(p), np.zeros(int(.25 * SR), np.float32)]; texts.append(L[i]['text'])
dest = RUN / 'refs-origreview/vi-prompt.wav'
sf.write(dest, np.concatenate(parts[:-1]), SR)
(RUN / 'refs-origreview/vi-prompt.json').write_text(json.dumps(dict(path=str(dest), text=' '.join(texts), hash=sha(dest)), ensure_ascii=False, indent=1), encoding='utf-8')
print(' '.join(texts), round(sum(len(x) for x in parts[:-1]) / SR, 2))
