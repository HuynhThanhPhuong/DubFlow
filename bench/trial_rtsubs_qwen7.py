"""rtsubs native translator via an isolated, local llama.cpp transport."""
import hashlib
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
import compare_repo_translation as baseline

ROOT = baseline.ROOT
NO_BIBLE = '--no-bible' in sys.argv
OUT = ROOT / ('bench/runs/20261030/rtsubs-qwen7-no-bible' if NO_BIBLE else 'bench/runs/20261030/rtsubs-qwen7')
OUT.mkdir(parents=True, exist_ok=True)
MODEL = 'Qwen2.5-7B-Instruct-Q4_K_M'
DLL = Path('C:/Users/PC/AppData/Local/Programs/Ollama/lib/ollama')
WEIGHT = ROOT / 'repo-tests/models/qwen2.5-7b-instruct-gguf/qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf'
calls = []

def infer(model, messages, limit=1800):
    payload = {'model':MODEL,'messages':messages,'temperature':0,'seed':42,'max_tokens':min(limit,1800),'stream':False}
    req = urllib.request.Request('http://127.0.0.1:11449/v1/chat/completions', json.dumps(payload).encode(), {'Content-Type':'application/json'})
    started = time.perf_counter()
    with urllib.request.urlopen(req, timeout=900) as response:
        result = json.load(response)
    text = result['choices'][0]['message']['content']
    calls.append({'messages':messages,'raw':text,'seconds':round(time.perf_counter()-started,3),'usage':result.get('usage'),
        'finish_reason':result['choices'][0]['finish_reason'],'timings':result.get('timings')})
    (OUT / 'calls.json').write_text(json.dumps(calls,ensure_ascii=False,indent=2),encoding='utf-8')
    print('request',len(calls),calls[-1]['seconds'],calls[-1]['finish_reason'],flush=True)
    return text

def main():
    if (OUT/'calls.json').exists():
        raise RuntimeError('Existing run: choose a new output directory; refusing to overwrite')
    args = [str(DLL/'llama-server.exe'),'-m',str(WEIGHT),'--host','127.0.0.1','--port','11449',
        '-c','4096','-np','1','-t','4','-ngl','20','--flash-attn','on']
    (OUT / 'runtime-command.json').write_text(json.dumps(args,indent=2),encoding='utf-8')
    started = time.perf_counter()
    with (OUT/'server.log').open('w',encoding='utf-8') as log:
        process = subprocess.Popen(args,cwd=DLL,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            for _ in range(180):
                if process.poll() is not None:
                    raise RuntimeError('llama-server exited: inspect server.log')
                try:
                    with urllib.request.urlopen('http://127.0.0.1:11449/health',timeout=2) as response:
                        if json.load(response).get('status') == 'ok':
                            break
                except (OSError,urllib.error.HTTPError):
                    time.sleep(1)
            else:
                raise RuntimeError('model startup timeout')
            baseline.OUT = OUT
            baseline.infer = infer
            baseline.call = lambda *args,**kwargs: None  # unload handled by owned standalone server lifetime
            baseline.rtsubs(MODEL, use_bible=not NO_BIBLE)
            manifest = {'model':MODEL,'download':json.loads((WEIGHT.parent/'download-manifest.json').read_text()),
                'source_job':'76b9aa4c51744e2783633fbc9e50fde1','span':[0,59],'chunks':23,
                'rtsubs_commit':'94341bd62f5a07b7119c4b72473d682eac0382ad',
                'translator_sha256':hashlib.sha256((ROOT/'repo-tests/rtsubs/server/rtsubs/translate.py').read_bytes()).hexdigest(),
                'runtime_args':args,'runtime_exe_sha256':hashlib.file_digest((DLL/'llama-server.exe').open('rb'),'sha256').hexdigest(),
                'temperature':0,'seed':42,'output_limit':1800,'batch_size':6,'context_pairs':10,
                'story_bible_enabled':not NO_BIBLE,'source_transcript_enabled':True,
                'manual_translation_or_source_correction':False,'total_seconds_including_load':round(time.perf_counter()-started,3),
                'scope':'native rtsubs understand/translate methods with local transport adapter, not whole application'}
            (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()

if __name__ == '__main__':
    main()
