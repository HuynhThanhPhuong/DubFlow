import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
out = root / 'bench/runs/20261030/rtsubs-qwen7'
old = root / 'bench/runs/20261030/repo-translation'
new = json.loads((out/'rtsubs-results.json').read_text(encoding='utf-8'))
base = json.loads((old/'rtsubs-results.json').read_text(encoding='utf-8'))
assert len(new) == len(base) == 23
assert all((a['start'],a['end'],a['zh']) == (b['start'],b['end'],b['zh']) for a,b in zip(new,base))
manifest = json.loads((out/'manifest.json').read_text(encoding='utf-8'))
calls = json.loads((out/'calls.json').read_text(encoding='utf-8'))
assert all(c['finish_reason'] == 'stop' for c in calls)
rows = [{k:a[k] for k in ('start','end','zh')} | {'qwen3_4b':b['vi'],'qwen2_5_7b':a['vi']} for a,b in zip(new,base)]
(out/'comparison.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
lines = ['# rtsubs: Qwen2.5 7B đối chứng Qwen3 4B', '',
'Cùng 23 câu ASR của 0–59 giây video 7698707610815565097. Không sửa nguồn, bản dịch hoặc bảng nhân vật. Giữ native Translator.understand/translate, context_pairs=10, batch6, chars_per_sec=18, temperature0, seed42, context4K, output tối đa1800.', '',
'Model mới Qwen2.5-7B-Instruct GGUF Q4_K_M chính thức, checksum hai shard được đối chiếu metadata Hugging Face. Chạy bằng llama-server đi kèm Ollama, đọc weights trên D; CPU4threads. GPU-layers20 bị runtime bỏ qua vì không tìm được backendGPU; log server là bằng chứng, không được coi đây là test CUDA. Runtime khác bài Qwen3 trước nên thời gian không dùng để so tốc độ model một cách nghiêm ngặt.', '',
f"Tổng thời gian kể cả load: {manifest['total_seconds_including_load']} giây. Đây là component test có adapter transport local, không phải toàn bộ ứng dụng rtsubs. Chưa thay provider web, chưa sinh giọng hoặc render.", '',
'## Đầu ra máy chưa hiệu đính', '', '| Giây | Trung | Qwen3 4B trước | Qwen2.5 7B mới |','|---|---|---|---|']
for row in rows:
    lines.append('| '+' | '.join(str(x).replace('|','/').replace('\n',' ') for x in [f"{row['start']:g}–{row['end']:g}",row['zh'],row['qwen3_4b'],row['qwen2_5_7b']])+' |')
(out/'COMPARISON.md').write_text('\n'.join(lines),encoding='utf-8')
print('Verified 23 aligned source chunks and',len(calls),'completed requests; total seconds',manifest['total_seconds_including_load'])
for i in (1,2,20,21,22):
    print(rows[i])
