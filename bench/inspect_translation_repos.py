import json
import urllib.request
from pathlib import Path

OUT = Path(__file__).parent / 'runs/20261030/repo-translation'
OUT.mkdir(parents=True, exist_ok=True)
for name, repo in {'haizflow': 'MachHongHai/HaizFlow', 'pyvideotrans': 'jianchang512/pyvideotrans'}.items():
    req = urllib.request.Request(f'https://api.github.com/repos/{repo}/git/trees/main?recursive=1', headers={'User-Agent': 'DubFlow'})
    data = json.load(urllib.request.urlopen(req))
    (OUT / f'{name}-tree.json').write_text(json.dumps(data), encoding='utf-8')
    print(name, data['sha'])
    paths = [x['path'] for x in data['tree'] if x['type'] == 'blob' and any(s in x['path'].lower() for s in ['hymt', 'ollama', 'prompt'])]
    print('\n'.join(paths[:50]))
    for path in paths:
        if path.endswith('.py') and ('hymt2_worker' in path or 'ollama' in path):
            content = urllib.request.urlopen(f'https://raw.githubusercontent.com/{repo}/{data["sha"]}/{path}').read()
            (OUT / f'{name}-{Path(path).name}').write_bytes(content)
