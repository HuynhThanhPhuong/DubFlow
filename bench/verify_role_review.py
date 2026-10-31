import hashlib
import json
from pathlib import Path

root=Path(__file__).resolve().parents[1]
out=root/'bench/runs/20261030/role-review'
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
rows=read(out/'utterances-review.json')
turns=read(out/'draft-turns.json')
pronouns=read(out/'pronouns-proposed.json')
manifest=read(out/'manifest.json')
source=root/'data/jobs/76b9aa4c51744e2783633fbc9e50fde1/source-asr.json'
chunks=[c for c in read(source)['chunks'] if c['timestamp'][1]<=60]
assert len(rows)==len(chunks)==23
assert len({r['id'] for r in rows})==23
assert sorted(r['id'] for r in rows)==sorted(i for t in turns for i in t['utterance_ids'])
for i,(row,chunk) in enumerate(zip(rows,chunks)):
    assert row['original_zh']==chunk['text']
    assert [row['start'],row['end']]==chunk['timestamp']
    assert row['start']<row['end']
    if i:
        assert rows[i-1]['end']<=row['start']
    assert row['translated_vi'] is None and row['translation_ready'] is False
    assert row['listener_character'] is None
    if row['speaker_status']=='uncertain':
        assert row['speaker_label'] is None and row['character_speaker'] is None
assert pronouns['approved_by_user'] is False
pairs={(p['speaker'],p['listener']) for p in pronouns['directed_pairs']}
assert pairs=={('CHAR_M','CHAR_F'),('CHAR_F','CHAR_M')}
assert manifest['source_asr_sha256']==hashlib.sha256(source.read_bytes()).hexdigest()
previous=read(root/'bench/runs/20261030/llm-subs-cli-qwen4/manifest.json')
assert previous['source_asr_sha256']==manifest['source_asr_sha256']
assert manifest['source_video_sha256']=='3c8f36d826c1fccf93fe64555d3e1f1fa68125980345ffa0eff3acc006cc48fa'
for name in ['evidence-sheet-1.jpg','evidence-sheet-2.jpg','evidence-sheet-3.jpg','frame-052.0.jpg','frame-089.5.jpg','frame-093.0.jpg']:
    assert (out/name).is_file()
summary={'verified':True,'source_video_and_asr_unchanged':True,'unique_utterances':23,'draft_turns':len(turns),
    'speaker_uncertain_kept_null':sum(r['speaker_status']=='uncertain' for r in rows),
    'listener_candidates_not_silently_confirmed':23,'directed_pronoun_pairs':2,
    'translation_ready':0,'translation_or_render_executed':False,
    'limitations':['not continuous diarization','no human audio listening','visual/manual candidate character mapping','ASR timing not forced aligned']}
(out/'verification.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
