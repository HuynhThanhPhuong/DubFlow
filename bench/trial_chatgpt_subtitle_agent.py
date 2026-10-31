"""Actual upstream agent CLI, local model, context/pronoun-focused instructions."""
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
import pysubs2

ROOT=Path(__file__).resolve().parents[1]
REPO=ROOT/'repo-tests/chatgpt-subtitle-translator'
BUDGET=int(sys.argv[1]) if len(sys.argv)>1 else 2000
FULL_CONTEXT='--full-context' in sys.argv
OUT=ROOT/('bench/runs/20261030/chatgpt-subtitle-agent' if BUDGET==2000 else f'bench/runs/20261030/chatgpt-subtitle-agent-budget{BUDGET}')
if FULL_CONTEXT:
    OUT=OUT.with_name(OUT.name+'-full-context')
MODEL='qwen3:4b-instruct-2507-q4_K_M'
INSTRUCTION=('Dịch phụ đề phim tiếng Trung sang tiếng Việt tự nhiên, đúng nghĩa và sắc thái. '
    'Dựa vào toàn cảnh và từng lượt thoại để xác định người nói, người nghe, địa vị, quan hệ và cách xưng hô. '
    'Không mặc định dùng bạn–tôi; chỉ dùng anh–em khi ngữ cảnh có căn cứ, không tự coi hai người nam nữ là người yêu. '
    'Giữ danh xưng và xưng hô nhất quán theo từng vai; nếu chưa chắc thì ưu tiên lược đại từ thay vì bịa quan hệ. '
    'Giữ đúng người thực hiện hành động, lời đe dọa, phủ định, thành ngữ và thông tin quan trọng. '
    'Không chép số thứ tự, ký hiệu người nói hoặc lời giải thích vào câu dịch. Chỉ dịch nội dung được yêu cầu.')

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/'command.json').exists():
        raise RuntimeError('Existing run; refusing overwrite')
    source=ROOT/'bench/runs/20261030/llm-subs-cli-qwen4/source.zh.srt'
    target=OUT/'source.zh.srt'
    if FULL_CONTEXT:
        chunks=json.loads((ROOT/'data/jobs/76b9aa4c51744e2783633fbc9e50fde1/source-asr.json').read_text(encoding='utf-8'))['chunks']
        full=pysubs2.SSAFile()
        for c in chunks:
            full.events.append(pysubs2.SSAEvent(start=round(c['timestamp'][0]*1000),end=round(c['timestamp'][1]*1000),text=c['text']))
        full.save(str(target),encoding='utf-8')
    else:
        target.write_bytes(source.read_bytes())
    output=OUT/'translation.vi.srt'
    args=['node',str(REPO/'cli/translator.mjs'),'agent','--input',str(target),'--output',str(output),
        '--from','Chinese','--to','Vietnamese','--model',MODEL,'--system-instruction',INSTRUCTION,
        '--context',str(BUDGET),'--max-batch-size','23','--temperature','0','--reasoning_effort','none',
        '--no-stream','--no-fitting','--log-level','debug']
    env=os.environ.copy()
    env.update(OPENAI_API_KEY='local-only-no-paid-key',OPENAI_BASE_URL='http://127.0.0.1:11439/v1',
        OPENAI_DEFAULT_MODEL=MODEL,OPENAI_SESSION_ID='dubflow-local-context-59s',NO_COLOR='1')
    env.pop('OPENAI_ORG_ID',None)
    env.pop('OPENAI_PROJECT_ID',None)
    (OUT/'command.json').write_text(json.dumps(args,ensure_ascii=False,indent=2),encoding='utf-8')
    started=time.perf_counter()
    with (OUT/'agent.log').open('w',encoding='utf-8') as log:
        result=subprocess.run(args,cwd=OUT,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW,timeout=1200)
    metrics={'exit_code':result.returncode,'seconds':round(time.perf_counter()-started,3)}
    (OUT/'metrics.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
    print(metrics,flush=True)
    if result.returncode:
        raise RuntimeError('CLI failed; inspect agent.log')
    original=pysubs2.load(str(target),encoding='utf-8')
    translated=pysubs2.load(str(output),encoding='utf-8')
    assert len(original)==len(translated)
    if not FULL_CONTEXT:
        assert len(original)==23
    rows=[]
    for zh,vi in zip(original,translated):
        assert (zh.start,zh.end)==(vi.start,vi.end)
        rows.append({'start':zh.start/1000,'end':zh.end/1000,'zh':zh.plaintext,'vi':vi.plaintext})
    (OUT/'results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    clip=[row for row in rows if row['end']<=60]
    (OUT/'results-59s.json').write_text(json.dumps(clip,ensure_ascii=False,indent=2),encoding='utf-8')
    clip_subs=pysubs2.SSAFile()
    clip_subs.events=[event for event in translated if event.end<=60000]
    clip_subs.save(str(OUT/'translation-59s.vi.srt'),encoding='utf-8')
    commit=subprocess.run(['git','-C',str(REPO),'rev-parse','HEAD'],capture_output=True,text=True).stdout.strip()
    with urllib.request.urlopen('http://127.0.0.1:11439/api/tags') as response:
        tags=json.load(response)
    manifest={'repo':'Cerlancism/chatgpt-subtitle-translator','commit':commit,'version':'3.3.2',
        'model':MODEL,'models_metadata':tags,'endpoint':env['OPENAI_BASE_URL'],'instruction':INSTRUCTION,
        'input_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'output_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
        'package_lock_sha256':hashlib.sha256((REPO/'package-lock.json').read_bytes()).hexdigest(),
        'span':[0,original[-1].end/1000],'cues':len(original),'review_span':[0,59],'timing_unchanged':True,'manual_source_or_translation_correction':False,
        'context_provenance':'upstream agent inference from supplied source transcript; no supplied story summary or per-line role labels',
        'no_fitting':True,'refine_enabled':True,'temperature':0,'reasoning_effort':'none','context_budget':BUDGET,
        'scope':'unmodified upstream CLI agent with custom general context/pronoun instruction, no ASR or rendering',
        'metrics':metrics}
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    req=urllib.request.Request('http://127.0.0.1:11439/api/generate',json.dumps({'model':MODEL,'keep_alive':0}).encode(),{'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=60) as response:
        response.read()
    print('Verified',len(original),'unchanged cue timings; model unloaded.',flush=True)

if __name__=='__main__':
    main()
