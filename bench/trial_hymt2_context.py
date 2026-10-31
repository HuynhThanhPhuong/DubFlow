"""Second trial: original ASR chunks, Chinese-only neighboring context."""
import json
import time
from trial_hymt2_text import ROOT, OUT, MODEL, call

chunks = json.loads((ROOT / 'data/jobs/76b9aa4c51744e2783633fbc9e50fde1/source-asr.json').read_text(encoding='utf-8'))['chunks']
rows = []
for i, chunk in enumerate(chunks):
    if chunk['timestamp'][1] > 60:
        break
    context = '\n'.join(c['text'] for c in chunks[max(0, i-3):i+3])
    prompt = ('[Background Information]\n' + context +
        '\nPlease translate the following text into Vietnamese, taking the provided background information into consideration. '
        'Use natural film dialogue. Only output the translation of the Source Text.\n[Source Text]\n' + chunk['text'])
    started = time.perf_counter()
    result = call('generate', {'model': MODEL, 'stream': False, 'raw': True,
        'prompt': '<｜hy_begin▁of▁sentence｜><｜hy_User｜>' + prompt + '<｜hy_Assistant｜>',
        'options': {'temperature': 0, 'seed': 42, 'num_ctx': 4096, 'num_predict': 160, 'num_thread': 4, 'num_gpu': 0}, 'keep_alive': '10m'})
    row = {**chunk, 'context_zh': context, 'hymt_raw': result['response'], 'seconds': round(time.perf_counter()-started,3),
        'done_reason': result.get('done_reason')}
    rows.append(row)
    (OUT / 'context-results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    print(i, row['hymt_raw'],flush=True)
call('generate', {'model': MODEL, 'keep_alive': 0})
