"""Validate source/config alignment and preserve both unedited outputs."""
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
old_dir = root/'bench/runs/20261030/rtsubs-qwen7'
new_dir = root/'bench/runs/20261030/rtsubs-qwen7-no-bible'
read = lambda p: json.loads(p.read_text(encoding='utf-8'))
old, new = [read(p/'rtsubs-results.json') for p in (old_dir,new_dir)]
before, after = [read(p/'manifest.json') for p in (old_dir,new_dir)]
old_calls, new_calls = [read(p/'calls.json') for p in (old_dir,new_dir)]
assert len(old) == len(new) == 23
assert read(new_dir/'rtsubs-bible.json') == {}
assert after['story_bible_enabled'] is False and after['source_transcript_enabled'] is True
for key in ('model','download','translator_sha256','runtime_args','runtime_exe_sha256','temperature','seed','output_limit','batch_size','context_pairs'):
    assert before[key] == after[key], key
previous_translate = next(c for c in old_calls if c['messages'][0]['content'].startswith('Bạn là dịch giả'))
current_translate = new_calls[0]
assert previous_translate['messages'][0] == current_translate['messages'][0]
assert previous_translate['messages'][2:] == current_translate['messages'][2:]
assert 'chưa có' in current_translate['messages'][1]['content']
rows=[]
for a,b in zip(old,new):
    for key in ('start','end','zh'):
        assert a[key] == b[key], key
    rows.append({k:a[k] for k in ('start','end','zh')} | {'with_bible':a['vi'],'without_bible':b['vi']})
summary = {'source_chunks':23,'same_model_and_generation_settings':True,'same_first_translation_system_source_and_batch':True,
    'with_bible_seconds':before['total_seconds_including_load'],'without_bible_seconds':after['total_seconds_including_load'],
    'with_bible_requests':len(old_calls),'without_bible_requests':len(new_calls),
    'new_request_finish_reasons':[c['finish_reason'] for c in new_calls],
    'source_fallback_count_before':sum(a['vi']==a['zh'] for a in old),
    'source_fallback_count_after':sum(a['vi']==a['zh'] for a in new),
    'contains_cjk_before':sum(bool(re.search('[\u4e00-\u9fff]',a['vi'])) for a in old),
    'contains_cjk_after':sum(bool(re.search('[\u4e00-\u9fff]',a['vi'])) for a in new)}
(new_dir/'comparison.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
(new_dir/'verification.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
lines=['# Đối chứng rtsubs: bật/tắt story bible', '',
'Cùng model Qwen2.5 7B Q4_K_M,23 câu ASR,0–59 giây. Không hiệu đính lời Trung hoặc Việt. Chỉ bỏ bước understand và thay story bible bằng giá trị rỗng gốc; vẫn giữ system prompt, toàn bộ transcript59giây, history10cặp, batch6,slotthời gian và native parser/retry. Đã đối chiếu hash/runtime/model/seed/temperature/cấu hình và đầu vào lần dịch đầu.', '',
'Đây là component ablation có adapter localhost, chưa tích hợp web. Model/runtimethử giữ nguyên,CPU4threads; GPU vẫn không được runtime nhận. Các lượt sau có history khác nhau vì bản dịch trước đó đã khác: đây là hệ quả tự nhiên của hai nhánh pipeline.', '',
f"Thời gian gồm load và retry: bật {summary['with_bible_seconds']}giây, tắt {summary['without_bible_seconds']}giây. Sốrequest: {len(old_calls)} / {len(new_calls)}. Không xem đây là số đo tốc độ CUDA hoặc benchmark model khác nhau.", '',
'| Giây | Nguồn Trung | Có story bible | Không story bible |','|---|---|---|---|']
for r in rows:
    lines.append('| '+' | '.join(str(v).replace('|','/').replace('\n',' ') for v in [f"{r['start']:g}–{r['end']:g}",r['zh'],r['with_bible'],r['without_bible']])+' |')
(new_dir/'COMPARISON.md').write_text('\n'.join(lines),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
for i in (1,2,9,14,20,21,22):
    print(rows[i])
