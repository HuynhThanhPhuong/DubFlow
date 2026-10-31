import json
import re
from pathlib import Path
import pysubs2

root=Path(__file__).resolve().parents[1]
base=root/'bench/runs/20261030'
out=base/'chatgpt-subtitle-agent-budget8000-full-context'
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
short=read(base/'chatgpt-subtitle-agent-budget8000/results.json')
full=read(out/'results-59s.json')
old=read(base/'llm-subs-cli-qwen4-vietnamese/results.json')
assert len(short)==len(full)==len(old)==23
assert all((a['start'],a['end'],a['zh'])==(b['start'],b['end'],b['zh'])==(c['start'],c['end'],c['zh']) for a,b,c in zip(short,full,old))
source=pysubs2.load(str(out/'source.zh.srt'),encoding='utf-8')
translated=pysubs2.load(str(out/'translation.vi.srt'),encoding='utf-8')
assert len(source)==len(translated)==38
assert all((a.start,a.end)==(b.start,b.end) for a,b in zip(source,translated))
log=(out/'agent.log').read_text(encoding='utf-8')
summary={'native_cli_exit_code':read(out/'metrics.json')['exit_code'],'whole_transcript_seconds':106.06,
    'whole_source_cues':38,'reviewed_first_59s_cues':23,'cue_timings_unchanged':True,
    'generic_ban_cau_cues_first59s':sum(bool(re.search(r'\b(bạn|cậu)\b',r['vi'],re.I)) for r in full),
    'overview_present':'Overview:' in log,'context_summary_present':'Context summary:' in log,
    'refined_instruction_present':'Refined instruction:' in log,'planning_failure_markers':re.findall(r'^.*(?:step failed|batch error|refinement failed).*$',log,re.M),
    'seconds':read(out/'metrics.json')['seconds'],
    'meaning_and_pronoun_quality':'not passed; human reading, no automatic quality certification'}
(out/'verification.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
lines=['# chatgpt-subtitle-translator: thử agent và xưng hô theo ngữ cảnh', '',
'Repo Cerlancism/chatgpt-subtitle-translator, commit02791299d4bef424b93a6c381d4a9357d00fa788, version3.3.2. Chạy CLI gốc không sửa mã, modelQwen3-4B-Instruct-2507 Q4_K_M trên Ollama localhost. Custom system instruction chung yêu cầu suy ra vai/quan hệ, giữ xưng hô nhất quán, không mặc định bạn–tôi và không tự bịa quan hệ. Không đưa bản dịch mẫu, glossary dịch tay hoặc nhãn vai từng câu vào đầu vào.', '',
'## Các lượt thử', '',
'- Run2000token: overview vàscan bị hết outputbudget; repo tự fallback sang dịch thường. Dù exit0, không xem là hoàn tất phân tích agent. Output/log được giữ ở chatgpt-subtitle-agent.',
'- Runbudget8000 với59giây: overview,scan,consolidation,refine chạy được; bản dịch vẫn dùng bạn/cậu/tôi và sai thành ngữ. Không hiệu đính.',
'- Runbudget8000 với106.06giây: thêm ngữ cảnh gốc về người mẹ hỏi chuyện con và lời gọi念念妈妈. Dịch toàn bộ38câu để agent đọc nguồn đầy đủ; chỉ so23câu0–59giây với các run trước. File translation-59s.vi.srt là cắt theo timestamp từ rawoutput, không sửa chữ.', '',
'--context8000 là ngân sáchhistory/planning của repo, không phải xác nhận runtime có cửa sổ8K. Trước đó các run4K/seed/temperaturekhác nên không dùng số liệu này để xếp hạng model nghiêm ngặt. No-fitting được bật để không chạy các vòng ép độ dàisummary, overview/planning/refine vẫn giữ nguyên.', '',
f"NativeCLI runfull106s exit0, mất{summary['seconds']}giây.38/38cue giữ nguyênstart/end. Trong23câu đầu, {summary['generic_ban_cau_cues_first59s']}câu còn bạn/cậu. Đây là chỉ báo kiểm tra, không phải điểm chất lượng dịch.", '',
'Runfull106s có overview/scan/contextsummary/refine nhưng bước agentinstruction trung gian bị lengthlimit rồi fallback. Vì vậy không mô tả run này là mọi bước agent đều thành công. Xem planning_failure_markers trong verification.json.', '',
'## Đánh giá', '',
'Không đạt yêu cầu dịch phim theo quan hệ nhân vật. Agent có phân tích nhưng ngữ cảnh tự sinh vẫn gán sai vai/chủ thể, hiểu sai sắc thái kiểm soát bằng video. Có bảnsummary còn nói video không dùng để đe dọa, trái với ngữ cảnh lời thoại. Chỉ thêmcontextkhông bảo đảm đúng.',
'SRT nguồn không cóspeakerID, nên hai người cùng xưng我 không được phân biệt bằng dữ liệu. Đại từ tiếngTrung cũng không tự xác định giới tính/địa vị người được nói tới. Không nên thay toàn bộ bạn/tôi thành anh/em; cảnh này có danh xưng校长 và phụ huynh, cần đối chiếu người nói thật và chốt bảngxưnghô theo vai trước khi sinh kịch bản.',
'FullsourceASR vẫn có lỗi “学习一场/学节异常” ở đoạn chuyện con; đã biết chữ trên hình là学籍异常. Không sửa trong run này để giữ nguồnASRnguyên bản, nên không được quy hết lỗi đó cho bước dịch.',
'Logoverview metadata còn suy thời lượng thành sốcuegiây (23/38) thay vì59/106.06giây. SRTxuất giữ timing đúng, nhưng metadata dùng trong phân tích không đáng tin tuyệt đối.', '',
'Chưa đổi bộdịch/web, chưa sinh giọng/render. Đã dùng model có sẵn, không tảiweightsmới hoặc gọi dịch vụ trả phí. requirements/package-lock vàmanifest pin điều kiện thử. Bảng dưới là outputnguyên bản.', '',
'| Giây | Trung | llm-subs trước | Agent ngữ cảnh59s | Agent ngữ cảnh106s |','|---|---|---|---|---|']
for a,b,c in zip(old,short,full):
    vals=[f"{a['start']:g}–{a['end']:g}",a['zh'],a['vi'],b['vi'],c['vi']]
    lines.append('| '+' | '.join(str(v).replace('|','/').replace('\n',' ') for v in vals)+' |')
(out/'REVIEW.md').write_text('\n'.join(lines),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
for i in (1,2,3,8,18,20):
    print(full[i])
