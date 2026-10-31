"""Text-only local translation benchmark; never modifies production cues."""
import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'bench/runs/20261030/hymt2-text'
MODEL = 'hf.co/tencent/Hy-MT2-1.8B-GGUF:Q8_0'

def call(endpoint, payload):
    req = urllib.request.Request('http://127.0.0.1:11439/api/' + endpoint,
        json.dumps(payload).encode(), {'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=900) as response:
        return json.load(response)

def main():
    cues = json.loads((ROOT / 'data/jobs/76b9aa4c51744e2783633fbc9e50fde1/cues.json').read_text(encoding='utf-8'))
    rows = []
    for cue in cues:
        if cue['end'] > 60:
            break
        prompt = 'Translate the following text into Vietnamese. Note that you should only output the translated result without any additional explanation:\n' + cue['original']
        started = time.perf_counter()
        result = call('generate', {'model': MODEL, 'stream': False, 'raw': True,
            'prompt': '<｜hy_begin▁of▁sentence｜><｜hy_User｜>' + prompt + '<｜hy_Assistant｜>',
            'options': {'temperature': 0, 'seed': 42, 'num_ctx': 4096, 'num_predict': 400, 'num_thread': 4}, 'keep_alive': '10m'})
        row = {**cue, 'baseline_opus': cue['text'], 'hymt_raw': result['response'],
            'seconds': round(time.perf_counter() - started, 3),
            'metrics': {k: result.get(k) for k in ('total_duration', 'load_duration', 'eval_count', 'eval_duration', 'done_reason')}}
        rows.append(row)
        (OUT / 'results.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
        print(cue['id'], row['hymt_raw'], flush=True)
    with urllib.request.urlopen('http://127.0.0.1:11439/api/tags') as response:
        tags = json.load(response)
    (OUT / 'manifest.json').write_text(json.dumps({'model': MODEL, 'tags': tags,
        'source_job': '76b9aa4c51744e2783633fbc9e50fde1', 'stage': 'unchanged merged ASR, first 59 seconds',
        'prompt': 'official default translation', 'temperature': 0, 'seed': 42,
        'num_ctx': 4096, 'num_predict': 400, 'manual_correction': False}, ensure_ascii=False, indent=2), encoding='utf-8')
    call('generate', {'model': MODEL, 'keep_alive': 0})

if __name__ == '__main__':
    main()
