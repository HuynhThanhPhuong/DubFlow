"""Non-destructive 59s local translation smoke test using existing ASR/OCR."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from dubflow.pipeline import read,write,file_hash
from dubflow.subtitle_cues import source_chunks
from dubflow.translation import translate_files
from dubflow.review import load_state,quality_report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--run',required=True)
    parser.add_argument('--model',default='qwen3:4b-instruct-2507-q4_K_M')
    args=parser.parse_args()
    folder=Path(args.run).resolve()
    if not folder.is_relative_to(ROOT):raise ValueError('Run phải nằm trong workspace D.')
    folder.mkdir(parents=True,exist_ok=False)
    old=ROOT/'data/jobs/76b9aa4c51744e2783633fbc9e50fde1'
    source=old/'source.mp4'
    raw=read(old/'source-asr.json')
    raw['chunks']=[c for c in raw['chunks'] if c['timestamp'][0]<59]
    cues=source_chunks(raw,59)
    regions=[r for r in read(old/'regions.json',[]) if r.get('kind')=='subtitle' and r['start']<59]
    regions=[dict(r,end=min(r['end'],59)) for r in regions]
    job=dict(mode='vietsub',duration=59,width=1080,height=1920,source_path=str(source),export_kind='draft')
    write(folder/'job.json',job);write(folder/'cues.json',cues);write(folder/'regions.json',regions)
    write(folder/'manifest.json',dict(source_sha256=file_hash(source),reused_asr=True,reused_ocr=True,
        reran_asr=False,manual_translation_input=False,roles_confirmed=False,model=args.model,
        duration=59,scope='local translation and review only; not new end-to-end ASR benchmark'))
    load_state(folder)
    try:
        translate_files(folder,dict(mode='ollama',translation_model=args.model,translation_num_ctx=4096))
    finally:
        write(folder/'quality-report.json',quality_report(folder,job))
    from dubflow.publisher import srt_text
    (folder/'automatic.vi.srt').write_text(srt_text(read(folder/'cues.json')),encoding='utf-8-sig')
    print(json.dumps(dict(run=str(folder),cues=len(cues),report=quality_report(folder,job)['export_status']),ensure_ascii=False))

if __name__=='__main__':main()
