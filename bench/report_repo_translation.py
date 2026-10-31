import hashlib
import json
import urllib.request
from compare_repo_translation import OUT, ROOT

files = {'HaizFlow + HY-MT2 Q8': 'haizflow-results.json', 'rtsubs + Qwen3 4B Q4': 'rtsubs-results.json', 'pyVideoTrans prompt + Qwen3 4B Q4': 'pyvideotrans-results.json'}
data = {name: json.loads((OUT / path).read_text(encoding='utf-8')) for name, path in files.items()}
assert all(len(rows) == 23 for rows in data.values())
rows = []
for i in range(23):
    h = next(iter(data.values()))[i]
    row = {'start': h['timestamp'][0], 'end': h['timestamp'][1], 'zh': h['text']}
    row.update({name: values[i]['vi'] for name, values in data.items()})
    rows.append(row)
(OUT / 'comparison.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
calls = json.loads((OUT / 'calls.json').read_text(encoding='utf-8'))
with urllib.request.urlopen('http://127.0.0.1:11439/api/tags') as response:
    tags = json.load(response)
manifest = {'source_job': '76b9aa4c51744e2783633fbc9e50fde1', 'span': [0,59], 'chunks':23,
    'manual_translation_or_source_correction':False, 'temperature':0,'seed':42,'num_ctx':4096,'output_limit':1800,
    'haizflow_commit':'b5b28cca015d10e49324eb3d50b960e69c1a8198',
    'pyvideotrans_commit':'069403080ea15748aefd008460fc2342c517b83e',
    'rtsubs_commit':'94341bd62f5a07b7119c4b72473d682eac0382ad',
    'runtime':'Ollama 0.40.2 localhost:11439', 'models':tags,
    'scope':'native prompt/translation components through local transport adapters, NOT full application pipelines',
    'sources_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.iterdir() if p.suffix in ('.py','.txt')},
    'result_sha256':{path:hashlib.sha256((OUT/path).read_bytes()).hexdigest() for path in files.values()},
    'failed_attempts':'Initial native-helper adapter lacked json; fixed. 8K Qwen loading returned HTTP500; reduced to4K. Native retries without successful calls not counted as translations.'}
(OUT / 'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
report = ['# So sánh component dịch của các repo — 30/10/2026', '',
'Cùng 23 câu ASR nguyên bản, 0–59 giây video 7698707610815565097. Không hiệu đính tiếng Trung hoặc tiếng Việt. Không dùng OPUS làm đối chứng. Đây là test component/prompt, chưa chạy nguyên ứng dụng hoặc bộ ASR riêng của mỗi repo.', '',
'## Phạm vi đã chạy', '',
'- HaizFlow: nạp hàm dựng prompt và làm sạch đầu ra gốc bằng AST; HY-MT2 Q8 qua Ollama raw với template chính thức. Có hướng dẫn thời lượng gốc. Chưa chạy bộ nạp llama_cpp, checkpoint, fallback/kiểm tra đầy đủ của ứng dụng.',
'- rtsubs: chạy Translator.understand/translate và parser gốc qua adapter transport localhost. Qwen3-4B-Instruct-2507 Q4_K_M, nhóm 6 câu, context_pairs=10, chars_per_sec=18; ngữ cảnh 4K, đầu ra tối đa1800 thay mặc định6000/4000 để vừa máy. Bảng nhân vật do model tự lập, không sửa tay.',
'- pyVideoTrans: chạy prompt localllm và system message lấy đúng commit, nhóm6 câu, cùng Qwen như rtsubs. Không có glossary tự nhập. Kiểm tra đủ số dòng; không chạy nguyên lớp BaseTrans hoặc toàn bộ CLI.', '',
'## Nhận xét', '',
'Cả ba cấu hình chưa đạt chất lượng kịch bản phim. Không kết luận repo nào tuyệt đối tốt hơn từ 59 giây hoặc từ hai model/quantization khác nhau. rtsubs có cơ chế ngữ cảnh thích hợp để tiếp tục thử nhưng Qwen4B trong lượt này vẫn hiểu sai thành ngữ và dựng sai bảng nhân vật. pyVideoTrans đơn giản hơn nhưng không cải thiện các câu khó. HaizFlow dùng nhánh standalone-label ở toàn bộ23 câu Trung ngắn, làm ngữ cảnh không được đưa vào prompt; đây là điều cần kiểm tra trước khi thử lại.', '',
'Bảng rtsubs gọi 校长 là Giáo sư (đúng phải Hiệu trưởng), tóm tắt nhầm ai sở hữu/đe dọa bằng video; asr_fixes còn chứa câu dịch Việt thay vì bản sửa chữ nguồn. Không nên tin bảng này vô điều kiện.', '',
'## Đầu ra máy nguyên bản', '', '| Thời gian | Trung | HaizFlow | rtsubs | pyVideoTrans prompt |', '|---|---|---|---|---|']
for r in rows:
    vals=[f"{r['start']:g}–{r['end']:g}",r['zh']]+[r[name] for name in files]
    report.append('| '+' | '.join(str(v).replace('|','/').replace('\n',' ') for v in vals)+' |')
report += ['', 'Không sinh giọng hoặc xuất video, không đổi provider web. Model được tải về cache Ollama; không gửi media hoặc transcript tới dịch vụ cloud.',
'Không dùng thời gian này làm benchmark tốc độ repo: cách batch, token và cold load khác nhau; calls.json chứa thời gian từng request thành công. Không có peak RAM/VRAM được đo liên tục.']
(OUT / 'REVIEW.md').write_text('\n'.join(report),encoding='utf-8')
print('Verified: 3 x 23 non-manual translations, aligned timestamps; report and manifest written.')
print('HaizFlow label branch:',sum(r['label_branch'] for r in next(iter(data.values()))))
