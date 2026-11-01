"""Reuse 59s raw ASR/OCR to verify actual local candidate/context stages, no edits."""
from pathlib import Path
import sys
import json
import time
import argparse
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from dubflow.pipeline import read,write,engine,file_hash
from dubflow.config import Settings
from dubflow.translation import translate_files
from dubflow.review import load_state,quality_report

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--name',default='automatic-inline-v2');args=parser.parse_args()
    if not args.name.replace('-','').isalnum():raise ValueError('Tên run không hợp lệ.')
    folder=ROOT/'bench/runs/20261031'/args.name
    folder.mkdir(parents=True,exist_ok=False)
    old=ROOT/'bench/runs/20261031/scene-workflow-v2'
    job=read(old/'job.json');job['export_kind']='auto'
    cues=[dict(c,text='') for c in read(old/'review-state.json')['source_cues']]
    for c in cues:
        c['speaker']='unconfirmed';c.pop('translation_dependency',None)
    write(folder/'job.json',job);write(folder/'cues.json',cues);write(folder/'regions.json',read(old/'regions.json',[]))
    config=Settings()
    started=time.monotonic()
    engine('speakers',folder,config,dict(source=job['source_path']))
    # All assignments remain machine candidates; no manual role confirmation.
    load_state(folder)
    translate_files(folder,dict(mode='ollama',translation_model='qwen3:4b-instruct-2507-q4_K_M',translation_num_ctx=4096,auto_context=True))
    report=quality_report(folder,job);write(folder/'quality-report.json',report)
    result=dict(source_sha256=file_hash(job['source_path']),source_asr_reused=True,source_ocr_reused=True,
        manual_translation_or_role_input=False,seconds=round(time.monotonic()-started,3),cues=len(cues),
        speaker_clusters=read(folder/'speaker-candidates.json',{}).get('clusters'),context_status=read(folder/'auto-context.json',{}).get('status'),
        export_status=report['export_status'],semantic_quality_approved=False)
    write(folder/'smoke-result.json',result)
    print(json.dumps(result,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
