"""Rank OmniVoice built-in voices by speaker similarity to the original review narrator
(CAMPPlus embedding from the Seed-VC checkpoint, cosine). Run in seedvc-venv."""
import json, sys, glob
from pathlib import Path
sys.path.insert(0, 'D:/DuAnKhoiNghiep/DubFlow/repo-tests/seed-vc')
import torch, torchaudio, librosa
from modules.campplus.DTDNN import CAMPPlus
ck = glob.glob('D:/DuAnKhoiNghiep/DubFlow/repo-tests/seed-vc/checkpoints/models--funasr--campplus/snapshots/*/campplus_cn_common.bin')[0]
m = CAMPPlus(feat_dim=80, embedding_size=192); m.load_state_dict(torch.load(ck, map_location='cpu')); m.eval()
def emb(p, max_s=20):
    w, _ = librosa.load(p, sr=16000, mono=True, duration=max_s)
    x = torch.tensor(w)[None]
    f = torchaudio.compliance.kaldi.fbank(x, num_mel_bins=80, dither=0, sample_frequency=16000)
    f = f - f.mean(0, keepdim=True)
    with torch.no_grad(): return torch.nn.functional.normalize(m(f[None]), dim=-1)[0]
RUN = Path(__file__).resolve().parent / 'runs' / '20261027'
target = emb(str(RUN / 'refs-origreview/narrator-long.wav'))
rows = []
for j in glob.glob('D:/OmniVoice/voices/*.json'):
    meta = json.loads(Path(j).read_text(encoding='utf-8'))
    if 'ref_audio' not in meta: continue
    rows.append((float(target @ emb(meta['ref_audio'])), Path(j).stem, meta.get('name'), meta['ref_audio'], meta.get('ref_text', '')[:60]))
for r in sorted(rows, reverse=True): print(f'{r[0]:.3f}', *r[1:])
