"""Run native translation components with a local transport adapter, no app installs."""
import ast
import json
import re
import threading
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace as NS
from trial_hymt2_text import call, ROOT

OUT = ROOT / 'bench/runs/20261030/repo-translation'
CHUNKS = json.loads((ROOT / 'data/jobs/76b9aa4c51744e2783633fbc9e50fde1/source-asr.json').read_text(encoding='utf-8'))['chunks']
CHUNKS = [c for c in CHUNKS if c['timestamp'][1] <= 60]
CALLS = json.loads((OUT / 'calls.json').read_text(encoding='utf-8')) if (OUT / 'calls.json').exists() else []

def infer(model, messages, limit=600):
    started = time.perf_counter()
    body = {'model': model, 'stream': False, 'keep_alive': '10m',
        'options': {'temperature': 0, 'seed': 42, 'num_ctx': 4096, 'num_predict': min(limit, 1800), 'num_thread': 4}}
    if model.startswith('hf.co/tencent'):
        body.update(raw=True, prompt='<｜hy_begin▁of▁sentence｜><｜hy_User｜>' + messages[-1]['content'] + '<｜hy_Assistant｜>')
        result = call('generate', body)
        content = result['response']
    else:
        body['messages'] = messages
        result = call('chat', body)
        content = result['message']['content']
    CALLS.append({'model': model, 'messages': messages, 'raw': content, 'seconds': time.perf_counter()-started,
        'done_reason': result.get('done_reason'), 'eval_count': result.get('eval_count'), 'load_duration': result.get('load_duration')})
    (OUT / 'calls.json').write_text(json.dumps(CALLS, ensure_ascii=False, indent=2), encoding='utf-8')
    return content

def haizflow():
    env = {'re': re, 'json': json, '_CONTEXT_SEGMENTS': 3, '_MAX_CONTEXT_CHARACTERS': 1200, '_MAX_BACKGROUND_CHARACTERS': 2400}
    timing = {}
    exec(compile((OUT / 'haizflow-translation_timing.py').read_text(encoding='utf-8'), 'translation_timing.py', 'exec'), timing)
    env['timing_instruction'] = timing['timing_instruction']
    tree = ast.parse((OUT / 'haizflow-hymt2_worker.py').read_text(encoding='utf-8'))
    names = {'_context_before_start', '_context_after_end', '_context_indices', '_is_standalone_label', '_build_prompt', '_clean_single_translation'}
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    exec(compile(ast.Module(body=functions, type_ignores=[]), 'haizflow-native-functions', 'exec'), env)
    rows = []
    texts = [c['text'] for c in CHUNKS]
    model = 'hf.co/tencent/Hy-MT2-1.8B-GGUF:Q8_0'
    for i, c in enumerate(CHUNKS):
        prompt = env['_build_prompt'](texts, ['Chinese'] * len(texts), i, 'Vietnamese', duration_seconds=c['timestamp'][1]-c['timestamp'][0])
        raw = infer(model, [{'role': 'user', 'content': prompt}])
        rows.append({**c, 'vi': env['_clean_single_translation'](raw), 'label_branch': env['_is_standalone_label'](c['text'])})
        (OUT / 'haizflow-results.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
        print('HaizFlow', i, rows[-1]['vi'], flush=True)
    call('generate', {'model': model, 'keep_alive': 0})

class LocalCompletions:
    def create(self, model, messages, max_tokens):
        content = infer(model, messages, max_tokens)
        return NS(choices=[NS(message=NS(content=content))], usage=None)

def rtsubs(model='qwen3:4b-instruct-2507-q4_K_M', use_bible=True):
    path = ROOT / 'repo-tests/rtsubs/server/rtsubs/translate.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    tree.body = [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom)) or
        isinstance(n, ast.ImportFrom) and n.module == '__future__']
    env = {'json': json, 're': re, 'threading': threading}
    exec(compile(tree, str(path), 'exec'), env)
    translator = env['Translator'].__new__(env['Translator'])
    translator.s = NS(model=model, context_pairs=10, chars_per_sec=18, transcript_max_chars=20000)
    translator.client = NS(chat=NS(completions=LocalCompletions()))
    translator.history = []
    translator._lock = threading.Lock()
    translator._bible_text = env['EMPTY_BIBLE_TEXT']
    translator._transcript_text = ''
    translator.bible = {}
    source_lines = [(c['timestamp'][0], c['text']) for c in CHUNKS]
    if use_bible:
        translator.understand(source_lines, complete=False)
    else:
        translator._transcript_text = env['_transcript_message'](source_lines, False, translator.s.transcript_max_chars)
    (OUT / 'rtsubs-bible.json').write_text(json.dumps(translator.bible, ensure_ascii=False, indent=2), encoding='utf-8')
    rows = []
    for start in range(0, len(CHUNKS), 6):
        group = CHUNKS[start:start+6]
        segs = [NS(start=c['timestamp'][0], end=c['timestamp'][1], zh=c['text'], vi='') for c in group]
        translator.translate(segs, [s.end-s.start for s in segs])
        rows.extend(dict(start=s.start, end=s.end, zh=s.zh, vi=s.vi) for s in segs)
        (OUT / 'rtsubs-results.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
        print('rtsubs', start, [s.vi for s in segs], flush=True)
    call('generate', {'model': translator.s.model, 'keep_alive': 0})

def pyvideo():
    template = (OUT / 'pyvideo-localllm.txt').read_text(encoding='utf-8')
    model = 'qwen3:4b-instruct-2507-q4_K_M'
    rows = []
    for start in range(0, len(CHUNKS), 6):
        group = CHUNKS[start:start+6]
        prompt = template.replace('{lang}', 'Vietnamese').replace('{GLOSSARY_DICT}', '').replace('{batch_input}', '\n'.join(c['text'] for c in group))
        raw = infer(model, [{'role': 'system', 'content': 'You are a top-tier Subtitle Translation Engine.'}, {'role': 'user', 'content': prompt}], 1800)
        match = re.search(r'<TRANSLATE_TEXT>(.*?)</TRANSLATE_TEXT>', raw, re.S)
        lines = (match.group(1) if match else raw).strip().splitlines()
        if len(lines) != len(group):
            raise ValueError(f'pyVideoTrans prompt line mismatch: {len(lines)} vs {len(group)}')
        rows.extend({**c, 'vi': line} for c, line in zip(group, lines))
        (OUT / 'pyvideotrans-results.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
        print('pyVideoTrans', start, lines, flush=True)
    call('generate', {'model': model, 'keep_alive': 0})

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'pyvideo':
        pyvideo()
    elif len(sys.argv) > 1 and sys.argv[1] == 'rtsubs':
        rtsubs()
    else:
        haizflow()
        rtsubs()
