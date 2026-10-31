import hashlib
import json
import urllib.request
from pathlib import Path

root = Path(__file__).resolve().parents[1]
out = root / 'repo-tests/models/qwen2.5-7b-instruct-gguf'
out.mkdir(parents=True, exist_ok=True)
repo = 'Qwen/Qwen2.5-7B-Instruct-GGUF'
meta = json.load(urllib.request.urlopen('https://huggingface.co/api/models/' + repo + '?blobs=true'))
revision = meta['sha']
files = []
for shard in (1, 2):
    name = f'qwen2.5-7b-instruct-q4_k_m-0000{shard}-of-00002.gguf'
    target = out / name
    partial = target.with_suffix('.partial')
    url = f'https://huggingface.co/{repo}/resolve/{revision}/{name}'
    expected = next(item for item in meta['siblings'] if item['rfilename'] == name)['lfs']
    if not target.exists() and partial.exists() and partial.stat().st_size == expected['size']:
        partial.replace(target)
    if not target.exists():
        with urllib.request.urlopen(url, timeout=120) as response, partial.open('wb') as stream:
            while block := response.read(4*1024*1024):
                stream.write(block)
        partial.replace(target)
    digest = hashlib.file_digest(target.open('rb'), 'sha256').hexdigest()
    assert digest == expected['sha256'], f'Checksum mismatch: {name}'
    files.append({'file':name,'bytes':target.stat().st_size,'sha256':digest})
    print(name, target.stat().st_size, flush=True)
(out / 'download-manifest.json').write_text(json.dumps({'repo':repo,'revision':revision,'files':files},indent=2),encoding='utf-8')
