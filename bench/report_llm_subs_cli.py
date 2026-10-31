import json
import re
from pathlib import Path
import pysubs2

root=Path(__file__).resolve().parents[1]
out=root/'bench/runs/20261030/llm-subs-cli-qwen4-vietnamese'
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
rows=read(out/'results.json')
base=read(root/'bench/runs/20261030/repo-translation/rtsubs-results.json')
english=read(root/'bench/runs/20261030/llm-subs-cli-qwen4/results.json')
source=pysubs2.load(str(out/'source.zh.srt'),encoding='utf-8')
translated=pysubs2.load(str(out/'translation.vi.srt'),encoding='utf-8')
assert len(rows)==len(base)==len(english)==len(source)==len(translated)==23
assert all((a.start,a.end)==(b.start,b.end) for a,b in zip(source,translated))
assert all(a['zh']==b['zh']==c['zh'] for a,b,c in zip(rows,base,english))
manifest=read(out/'manifest.json')
summary={'cues':23,'timing_matches_source':True,'native_translate_exit_code':0,'native_validate_exit_code':0,
    'speaker_marker_leaks':sum(bool(re.match(r'^\?\s*:',r['vi'])) for r in rows),
    'source_cjk_leaks':sum(bool(re.search('[\u4e00-\u9fff]',r['vi'])) for r in rows),
    'translation_seconds':next(m['seconds'] for m in manifest['metrics'] if m['stage']=='translate'),
    'language_quality':'Vietnamese output produced after replacing target code vi with full target name Vietnamese; semantic errors remain',
    'format_validation_is_not_semantic_validation':True}
(out/'verification.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
lines=['# llm-subs CLI thực tế — 30/10/2026','',
'Cài llm-subs0.8.0 trong repo-tests/llm-subs-runtime, chạy executable CLI thật không sửa package. Provider Ollama chỉ localhost127.0.0.1:11439, model Qwen3-4B-Instruct-2507 Q4_K_M đã có. Không tải thêm model, không dùng CLI Claude/Codex/APIcloud. Dùng23câu ASR0–59giây, giữ timing, không sửa lời Trung/Việt. Projectmemory bắt đầu rỗng, không chạy analyze; đây là bài thử translate cơ bản, chưa kiểm chứng workflowanalyze→translate theo series.', '',
'## Hai lượt chạy', '',
'1. --target vi: CLI báo thành công/validateOK, nhưng cả23câu ra tiếng Anh, có ký hiệu người nói. Giữ nguyên ở thư mục llm-subs-cli-qwen4. Đây là lỗi ngôn ngữ đích dù file có đuôi.vi.srt.',
'2. --target Vietnamese: run/state/checkpointmới, CLI xuất tiếng Việt, đủ23câu, timing23/23trùng nguồn; validate báoValid. Không hiệu đính hoặc lọc ký hiệu?:.', '',
f"Lượt2dịch mất{summary['translation_seconds']}giây; {summary['speaker_marker_leaks']}/23câu chép?:vào lời dịch. Không so tốc độ trực tiếp với các runCPU7B; model,runtime,token/batch và tham số khác. Nativeprovider không đặt temperature/seed/context, chỉ format=json,think=false; các thử component trước có temperature0/seed42, nên không phải benchmark kiểm soát hoàn toàn.", '',
'## Nhận xét chất lượng', '',
'- 想死我了: bảnAnh “I\'ve missed you so much!” hiểu đúng, nhưng bảnViệt “Tôi đã muốn chết rồi!” sai ý nhớ nhung.',
'- 校长: tiếngAnh “Principal” đúng, Việt “Giáo sư” sai danh xưng.',
'- 你做夢: “Bạn đang mơ!” chưa tự nhiên bằng lời bác bỏ trong cảnh; vẫn chưa thể coi đạt diễn thoại.',
'- Câu mã hóa/sao lưu giữ được ý; câu hỏi điện thoại bị mất nhìn chung rõ.',
'- Có cô ấy vẫn lệch ngữ cảnh đe dọa bằng video; nguồnASR có她, chưa được hiệu chỉnh.',
'- Các chữ?:là ký hiệu người nói không xác định trong prompt bị model chép lại, không có trong SRTnguồn. Kiểm tra cấu trúc của tool không phát hiện việc này hoặc lỗi nghĩa/ngôn ngữ.', '',
'Kết luận: CLI chạy được local và giữ cấu trúc SRT; chưa cải thiện đủ lờiViệt với model4B này. Chưa tích hợp vào web, chưa sinh giọng/render và chưa xác nhận chất lượng sản phẩm. Việc bảnAnh/bảnViệt khác chất lượng là quan sát hai lượt, không đủ chứng minh nguyên nhân duy nhất do model; prompt,tham số và batching cũng có thể ảnh hưởng.', '',
'## Bảng đầu ra chưa sửa tay', '',
'| Giây | Trung | rtsubs/Qwen4 trước | llm-subs/Qwen4 Việt | Lượt vi bị ra Anh |','|---|---|---|---|---|']
for a,b,c in zip(rows,base,english):
    vals=[f"{a['start']:g}–{a['end']:g}",a['zh'],b['vi'],a['vi'],c['vi']]
    lines.append('| '+' | '.join(str(v).replace('|','/').replace('\n',' ') for v in vals)+' |')
(out/'REVIEW.md').write_text('\n'.join(lines),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
