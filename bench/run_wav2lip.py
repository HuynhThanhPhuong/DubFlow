"""Wav2Lip (GAN) lip-sync on a dubbed clip, headless, streaming (low RAM).
Mouth is regenerated only inside dub cue windows; other frames stay original.
Face = largest S3FD face per frame (not speaker-aware). Weights loaded weights_only.
Usage: python run_wav2lip.py <engine-tag> [name]   e.g.  Edge-span dialogue"""
import json, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from benchlib import RUN, OUT, FF, VIDEOS, cues
REPO = Path('D:/DuAnKhoiNghiep/DubFlow/repo-tests/Wav2Lip'); W = Path('D:/DuAnKhoiNghiep/DubFlow/repo-tests/wav2lip-weights')
sys.path.insert(0, str(REPO))
import numpy as np, cv2, torch, librosa
import audio as w2a
from hparams import hparams as hp
from models import Wav2Lip
from face_detection.detection.sfd.net_s3fd import s3fd
from face_detection.detection.sfd.detect import batch_detect
from face_detection.detection.sfd.bbox import nms

engine, name = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else 'dialogue')
w2a._build_mel_basis = lambda: librosa.filters.mel(sr=hp.sample_rate, n_fft=hp.n_fft, n_mels=hp.num_mels, fmin=hp.fmin, fmax=hp.fmax)
dev = 'cuda'
work = RUN / f'{engine}-{name}'; t0 = time.time()

det = s3fd(); det.load_state_dict(torch.load(W / 's3fd-619a316812.pth', weights_only=True)); det.to(dev).eval()
model = Wav2Lip(); ck = torch.load(W / 'wav2lip_gan.pth', weights_only=True)
model.load_state_dict({k.replace('module.', ''): v for k, v in ck['state_dict'].items()}); model.to(dev).eval()

src = VIDEOS[name]; LEN = 30.0
cap = cv2.VideoCapture(src); fps = cap.get(cv2.CAP_PROP_FPS); Wd, Ht = int(cap.get(3)), int(cap.get(4)); N = int(LEN * fps)
cs = cues(name); active = np.zeros(N, bool)
for c in json.loads((work / 'placements.json').read_text(encoding='utf-8')):
    active[max(0, int((c['actual_start'] - .08) * fps)):min(N, int((c['actual_end'] + .08) * fps) + 1)] = True

# pass 1: faces on half-res frames
S = 2; boxes = []; batch = []
def flush():
    if not batch: return
    with torch.no_grad():
        bl = batch_detect(det, np.array(batch), device=dev)
    for i in range(bl.shape[1]):
        b = bl[nms(bl[:, i, :], 0.3), i, :]; b = [x for x in b if x[-1] > 0.5]
        boxes.append(max(b, key=lambda x: (x[2] - x[0]) * (x[3] - x[1]))[:4] * S if b else None)
    batch.clear()
for f in range(N):
    ok, fr = cap.read()
    if not ok: break
    batch.append(cv2.resize(fr, (Wd // S, Ht // S))[..., ::-1].copy())
    if len(batch) == 16: flush()
flush(); cap.release(); N = len(boxes)
have = np.array([b is not None for b in boxes]); arr = np.array([b if b is not None else [0] * 4 for b in boxes], float)
for i in range(N):  # temporal smoothing over 5 valid neighbours
    if have[i]:
        win = [j for j in range(max(0, i - 2), min(N, i + 3)) if have[j]]; arr[i] = arr[win].mean(0)

# audio: dry Vietnamese voice drives the mouth
wav = w2a.load_wav(str(work / 'dry.wav'), 16000); mel = w2a.melspectrogram(wav)
def mel_chunk(i):
    s = int(i * 80. / fps)
    return mel[:, s:s + 16] if s + 16 <= mel.shape[1] else mel[:, -16:]

# pass 2: generate + stream to ffmpeg
tmp = work / 'wav2lip-video.mp4'
enc = subprocess.Popen([FF, '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{Wd}x{Ht}', '-r', str(fps), '-i', '-', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p', str(tmp)], stdin=subprocess.PIPE)
cap = cv2.VideoCapture(src); done = 0; buf = []
def run(buf):
    global done
    idx = [k for k, (i, fr, bx) in enumerate(buf) if bx is not None]
    if idx:
        faces = []; mels = []
        for k in idx:
            i, fr, (x1, y1, x2, y2) = buf[k]
            y2 = min(Ht, y2 + 20); face = cv2.resize(fr[int(y1):int(y2), int(x1):int(x2)], (96, 96)); faces.append(face); mels.append(mel_chunk(i))
        f = np.array(faces); m = f.copy(); m[:, 48:] = 0
        x = torch.from_numpy(np.concatenate([m, f], 3).transpose(0, 3, 1, 2) / 255.).float().to(dev)
        y = torch.from_numpy(np.array(mels)[:, None]).float().to(dev)
        with torch.no_grad():
            pred = (model(y, x).cpu().numpy().transpose(0, 2, 3, 1) * 255.)
        for k, p in zip(idx, pred):
            i, fr, (x1, y1, x2, y2) = buf[k]; y2 = min(Ht, y2 + 20); x1, y1, x2, y2 = map(int, (x1, y1, x2, y2))
            patch = cv2.resize(p.astype(np.uint8), (x2 - x1, y2 - y1))
            mask = np.zeros(patch.shape[:2], np.float32); h, w = mask.shape  # feather lower face only
            mask[h // 2:, w // 8:w - w // 8] = 1; mask = cv2.GaussianBlur(mask, (0, 0), max(2, w / 20))[..., None]
            fr[y1:y2, x1:x2] = (patch * mask + fr[y1:y2, x1:x2] * (1 - mask)).astype(np.uint8); done += 1
    for _, fr, _ in buf:
        enc.stdin.write(fr.tobytes())
for i in range(N):
    ok, fr = cap.read()
    if not ok: break
    bx = tuple(arr[i]) if have[i] and active[i] else None
    buf.append((i, fr, bx))
    if len(buf) == 32: run(buf); buf = []
run(buf); cap.release(); enc.stdin.close(); enc.wait()

# mux with the already-mixed final audio of that engine's sample
final = OUT / f'DubFlow-20261027-{engine}-{name}-30s.mp4'; dest = OUT / f'DubFlow-20261027-{engine}-{name}-wav2lip-30s.mp4'
subprocess.run([FF, '-v', 'error', '-y', '-i', str(tmp), '-i', str(final), '-map', '0:v', '-map', '1:a', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-vf', 'drawbox=x=0:y=970:w=iw:h=110:color=black:t=fill,ass=captions.ass', '-c:a', 'copy', '-shortest', '-movflags', '+faststart', str(dest)], check=True, cwd=work)
rep = dict(engine='Wav2Lip GAN', repo_commit='bac9a81e63ecc153202353372e5724b83d9e6322', weights='camenduru/Wav2Lip (HF mirror) wav2lip_gan.pth + s3fd', fps=fps, frames=N, frames_with_face=int(have.sum()), frames_lipsynced=done, seconds=round(time.time() - t0, 1), peak_vram_mb=round(torch.cuda.max_memory_allocated() / 2**20), output=str(dest), limits='96x96 mouth region; largest face only (not speaker-aware); only inside dub cue windows')
(work / 'wav2lip-report.json').write_text(json.dumps(rep, indent=2), encoding='utf-8'); print(json.dumps(rep, indent=1))
