"""Run the installed llm-subs CLI against a local Ollama, with isolated state."""
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
import pysubs2

ROOT = Path(__file__).resolve().parents[1]
TARGET = sys.argv[1] if len(sys.argv)>1 else 'vi'
OUT = ROOT/('bench/runs/20261030/llm-subs-cli-qwen4-vietnamese' if TARGET=='Vietnamese' else 'bench/runs/20261030/llm-subs-cli-qwen4')
CLI = ROOT/'repo-tests/llm-subs-runtime/Scripts/llm-subs.exe'
MODEL = 'qwen3:4b-instruct-2507-q4_K_M'

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/'commands.json').exists():
        raise RuntimeError('Existing run; refusing to overwrite')
    source = ROOT/'data/jobs/76b9aa4c51744e2783633fbc9e50fde1/source-asr.json'
    chunks = [c for c in json.loads(source.read_text(encoding='utf-8'))['chunks'] if c['timestamp'][1] <= 60]
    subs = pysubs2.SSAFile()
    for c in chunks:
        subs.events.append(pysubs2.SSAEvent(start=round(c['timestamp'][0]*1000),end=round(c['timestamp'][1]*1000),text=c['text']))
    input_path = OUT/'source.zh.srt'
    output_path = OUT/'translation.vi.srt'
    subs.save(str(input_path),encoding='utf-8')
    env = os.environ.copy()
    env.update(OLLAMA_HOST='http://127.0.0.1:11439',XDG_DATA_HOME=str(OUT/'state'),XDG_CACHE_HOME=str(OUT/'cache'),
        PYTHONIOENCODING='utf-8',NO_COLOR='1',TERM='dumb',COLUMNS='150')
    env.pop('LLM_SUBS_DATA_DIR',None)
    env.pop('TRANSLATE_SUBS_DATA_DIR',None)
    env.pop('LLM_SUBS_HOME',None)
    env.pop('TRANSLATE_SUBS_HOME',None)
    env['PATH'] = str(Path('D:/OmniVoice/tools'))+os.pathsep+env['PATH']
    commands = [
        ('doctor',[str(CLI),'doctor','--provider','ollama','--model',MODEL]),
        ('translate',[str(CLI),'translate',str(input_path),'--provider','ollama','--model',MODEL,'--lang','zh','--target',TARGET,
            '--format','srt','--output',str(output_path),'--project','dubflow-59s-clean-qwen4','--parallel','1','--timeout','600',
            '--retries','2','--fail-on-untranslated','--non-interactive']),
        ('validate',[str(CLI),'validate',str(output_path)]),
    ]
    (OUT/'commands.json').write_text(json.dumps(commands,ensure_ascii=False,indent=2),encoding='utf-8')
    metrics=[]
    for name,args in commands:
        print('Running',name,flush=True)
        started=time.perf_counter()
        with (OUT/f'{name}.log').open('w',encoding='utf-8') as log:
            result=subprocess.run(args,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        metrics.append({'stage':name,'exit_code':result.returncode,'seconds':round(time.perf_counter()-started,3)})
        (OUT/'metrics.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
        print(metrics[-1],flush=True)
        if result.returncode:
            raise RuntimeError(f'{name} failed: inspect {OUT/name}.log')
    translated=pysubs2.load(str(output_path),encoding='utf-8')
    assert len(translated)==len(subs)==23
    rows=[]
    for original,vi in zip(subs,translated):
        assert (original.start,original.end)==(vi.start,vi.end)
        rows.append({'start':original.start/1000,'end':original.end/1000,'zh':original.plaintext,'vi':vi.plaintext})
    (OUT/'results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    with urllib.request.urlopen('http://127.0.0.1:11439/api/tags') as response:
        tags=json.load(response)
    package=ROOT/'repo-tests/llm-subs-runtime/Lib/site-packages/translate_subs'
    manifest={'package':'llm-subs==0.8.0','model':MODEL,'models_metadata':tags,'source_job':source.parent.name,
        'source_asr_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'span':[0,59],'cues':23,
        'input_srt_sha256':hashlib.sha256(input_path.read_bytes()).hexdigest(),
        'output_srt_sha256':hashlib.sha256(output_path.read_bytes()).hexdigest(),
        'timing_identical':True,'target_option':TARGET,'manual_source_or_translation_correction':False,'pre_analyze':False,'initial_memory':'empty',
        'provider_options':'native OllamaRunner: format=json,think=false; no explicit temperature/seed/context override',
        'runtime_source_hashes':{str(p.relative_to(package)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [package/'ai/api_adapters.py',package/'ai/job_protocol.py',package/'ai/blocks.py']},
        'metrics':metrics,'local_endpoint':env['OLLAMA_HOST'],'state_root':env['XDG_DATA_HOME'],
        'scope':'actual unmodified llm-subs CLI translate and validate on ASR-derived SRT, no ASR/audio/video rendering'}
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    freeze=subprocess.run([str(CLI.parent/'python.exe'),'-m','pip','freeze'],capture_output=True,text=True)
    (OUT/'requirements-lock.txt').write_text(freeze.stdout,encoding='utf-8')
    req=urllib.request.Request('http://127.0.0.1:11439/api/generate',json.dumps({'model':MODEL,'keep_alive':0}).encode(),{'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=60) as response:
        response.read()
    print('Verified 23 cues with unchanged timing; model unloaded.',flush=True)

if __name__=='__main__':
    main()
