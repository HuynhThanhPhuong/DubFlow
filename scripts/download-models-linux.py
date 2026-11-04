#!/usr/bin/env python3
"""Download the DubFlow models into the Linux cache layout from official sources.

Layout (DUBFLOW_MODELS_DIR, default <repo>/models):
  cache/hf-asr/hub   openai/whisper-large-v3-turbo, k2-fsa/OmniVoice      (DUBFLOW_ASR_CACHE)
  cache/hf-tts/hub   openbmb/VoxCPM2                                      (DUBFLOW_MODEL_CACHE)
  cache/torch/hub/checkpoints/955717e8-8726e21a.th   HTDemucs             (TORCH_HOME=cache/torch)
  lama/lama_fp32.onnx                                                     (DUBFLOW_LAMA_MODEL)
  speaker-ecapa-voxceleb/                                                 (DUBFLOW_SPEAKER_MODEL)

Needs `huggingface_hub` (it is in requirements/asr.txt):  runtime/asr/.venv/bin/python scripts/download-models-linux.py
Examples:  --list | --small | --only lama,speaker | --verify-hash
Sizes are always checked; sha256 is checked when the source publishes it (LaMa pin below, HF LFS hashes with --verify-hash).
"""
import argparse
import hashlib
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = Path(os.environ.get('DUBFLOW_MODELS_DIR', ROOT / 'models'))
CACHE = MODELS / 'cache'
ASR_CACHE = Path(os.environ.get('DUBFLOW_ASR_CACHE', CACHE / 'hf-asr'))
TTS_CACHE = Path(os.environ.get('DUBFLOW_MODEL_CACHE', CACHE / 'hf-tts'))
TORCH_HOME = Path(os.environ.get('TORCH_HOME', CACHE / 'torch'))
LAMA = Path(os.environ.get('DUBFLOW_LAMA_MODEL', MODELS / 'lama' / 'lama_fp32.onnx'))
SPEAKER = Path(os.environ.get('DUBFLOW_SPEAKER_MODEL', MODELS / 'speaker-ecapa-voxceleb'))

# sha256/size recorded when the model was first downloaded on the Windows machine (task 7 report of the LaMa work).
LAMA_URL = 'https://huggingface.co/Carve/LaMa-ONNX/resolve/main/lama_fp32.onnx'
LAMA_SIZE = 208044816
LAMA_SHA256 = '1faef5301d78db7dda502fe59966957ec4b79dd64e16f03ed96913c7a4eb68d6'
# Demucs HTDemucs checkpoint 955717e8; torch.hub names the file <signature>-<first 8 hex of sha256>.th. URL not verified from this repo.
DEMUCS_URL = 'https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/955717e8-8726e21a.th'
DEMUCS_PREFIX = '8726e21a'
ECAPA_REPO = 'speechbrain/spkrec-ecapa-voxceleb'
ECAPA_FILES = ['hyperparams.yaml', 'embedding_model.ckpt', 'mean_var_norm_emb.ckpt', 'classifier.ckpt', 'label_encoder.txt']
HF_MODELS = {  # key -> (repo, cache dir, approx. GB, light-test alternative)
    'whisper': ('openai/whisper-large-v3-turbo', ASR_CACHE, 1.6),
    'omnivoice': ('k2-fsa/OmniVoice', ASR_CACHE, 3.1),
    'voxcpm2': ('openbmb/VoxCPM2', TTS_CACHE, 4.7),
}
# --small: only models that are small or have a light stand-in; the pipeline itself still needs the full models above.
SMALL = ['speaker', 'lama', 'whisper-tiny']


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def fetch(url, dest, size=None, sha=None, sha_prefix=None):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and (size is None or dest.stat().st_size == size):
        print(f'  da co: {dest}')
    else:
        part = dest.with_name(dest.name + '.part')
        print(f'  tai {url}')
        urllib.request.urlretrieve(url, part)
        part.replace(dest)
    if size is not None and dest.stat().st_size != size:
        raise SystemExit(f'Sai dung luong {dest}: {dest.stat().st_size} != {size}')
    digest = sha256_of(dest) if (sha or sha_prefix) else None
    if sha and digest != sha:
        raise SystemExit(f'Sai sha256 {dest}: {digest}')
    if sha_prefix and not digest.startswith(sha_prefix):
        raise SystemExit(f'Sai sha256 {dest}: {digest} khong bat dau bang {sha_prefix}')
    print(f'  ok: {dest} ({dest.stat().st_size} bytes)')


def hf_download(repo, cache, verify_hash, files=None):
    try:
        from huggingface_hub import HfApi, snapshot_download
    except ImportError:
        raise SystemExit('Thieu huggingface_hub. Chay script nay bang python trong runtime/asr/.venv.')
    hub = Path(cache) / 'hub'
    hub.mkdir(parents=True, exist_ok=True)
    print(f'  {repo} -> {hub}')
    path = Path(snapshot_download(repo, cache_dir=str(hub), allow_patterns=files))
    info = HfApi().model_info(repo, files_metadata=True)
    for item in info.siblings:
        if files and item.rfilename not in files:
            continue
        target = path / item.rfilename
        if not target.exists():
            raise SystemExit(f'Thieu file {item.rfilename} trong {path}')
        if item.size is not None and target.stat().st_size != item.size:
            raise SystemExit(f'Sai dung luong {target}: {target.stat().st_size} != {item.size}')
        expected = getattr(getattr(item, 'lfs', None), 'sha256', None)
        if verify_hash and expected and sha256_of(target) != expected:
            raise SystemExit(f'Sai sha256 {target}')
    print(f'  ok: {repo} ({len(info.siblings)} file kiem tra kich thuoc{", sha256" if verify_hash else ""})')


def get_speaker(verify_hash):
    SPEAKER.mkdir(parents=True, exist_ok=True)
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        raise SystemExit('Thieu huggingface_hub. Chay script nay bang python trong runtime/asr/.venv.')
    for name in ECAPA_FILES:
        got = hf_hub_download(ECAPA_REPO, name, cache_dir=str(CACHE / 'hf-speaker'))
        (SPEAKER / name).write_bytes(Path(got).read_bytes())
        print(f'  ok: {SPEAKER / name}')


def get_lama(verify_hash):
    fetch(LAMA_URL, LAMA, LAMA_SIZE, LAMA_SHA256)


def get_demucs(verify_hash):
    fetch(DEMUCS_URL, TORCH_HOME / 'hub' / 'checkpoints' / '955717e8-8726e21a.th', sha_prefix=DEMUCS_PREFIX)


def main():
    steps = {
        'whisper': lambda v: hf_download(*HF_MODELS['whisper'][:2], v),
        'omnivoice': lambda v: hf_download(*HF_MODELS['omnivoice'][:2], v),
        'voxcpm2': lambda v: hf_download(*HF_MODELS['voxcpm2'][:2], v),
        'demucs': get_demucs, 'lama': get_lama, 'speaker': get_speaker,
        'whisper-tiny': lambda v: hf_download('openai/whisper-tiny', ASR_CACHE, v),
    }
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--small', action='store_true', help='chi tai model nhe de thu nhanh: ' + ', '.join(SMALL))
    parser.add_argument('--only', help='danh sach, cach nhau dau phay: ' + ', '.join(k for k in steps if k != 'whisper-tiny'))
    parser.add_argument('--verify-hash', action='store_true', help='tinh sha256 file HF LFS (cham voi VoxCPM2 4,7 GB)')
    parser.add_argument('--list', action='store_true', help='chi in vi tri va dung luong')
    args = parser.parse_args()
    full = ['whisper', 'omnivoice', 'voxcpm2', 'demucs', 'lama', 'speaker']
    chosen = SMALL if args.small else [s.strip() for s in args.only.split(',')] if args.only else full
    unknown = [s for s in chosen if s not in steps]
    if unknown:
        sys.exit('Khong biet: ' + ', '.join(unknown))
    approx = {'whisper': '1.6 GB', 'omnivoice': '3.1 GB', 'voxcpm2': '4.7 GB', 'demucs': 'khoang 80 MB (chua xac minh)',
              'lama': '0.2 GB', 'speaker': 'khoang 80 MB', 'whisper-tiny': 'khoang 0.15 GB (chi de thu, pipeline van can large-v3-turbo)'}
    for name in chosen:
        print(f'[{name}] {approx[name]}')
        if not args.list:
            steps[name](args.verify_hash)
    if args.small:
        print('Luu y: --small khong du de chay pipeline; whisper-large-v3-turbo, OmniVoice, VoxCPM2, Demucs van bat buoc cho tung che do.')


if __name__ == '__main__':
    main()
 
