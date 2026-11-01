"""Pure display translation for current and persisted errors/warnings.

Call translate_message(job.get('error')) and map it over warnings in public_job
or health responses. Unknown text is returned unchanged. Never apply to raw logs.
No files, model imports, network access or persisted records are touched.
"""
from __future__ import annotations

import re

_MESSAGES = {
    'Invalid take duration':
        'Thời lượng bản thu không hợp lệ. Hãy tạo lại giọng cho câu này.',
    'Pipeline cancelled':
        'Đã dừng tác vụ.',
    'Review source transcript and enter Vietnamese text in cues; offline manual translation is the default':
        'Hãy duyệt lời gốc và nhập tiếng Việt cho từng câu phụ đề; mặc định hệ thống dùng bản dịch thủ công ngoại tuyến.',
    'No speech detected; add or import cues':
        'Không phát hiện lời nói. Hãy thêm câu phụ đề hoặc nhập tệp SRT.',
    'Vietnamese cue text must be reviewed before synthesis':
        'Hãy nhập và duyệt tiếng Việt cho tất cả câu phụ đề trước khi tạo giọng.',
    'Choose a voice with a reference audio and transcript':
        'Hãy chọn giọng có tệp âm thanh mẫu và lời gốc tương ứng.',
    'Some cues failed exact Vietnamese ASR after 24 seeds; rewrite and retry':
        'Một số câu chưa khớp nhận dạng tiếng Việt sau 24 lần tạo. Hãy sửa lời Việt và tạo lại giọng.',
    'Review Vietnamese text before rendering':
        'Hãy nhập và duyệt lời tiếng Việt trước khi xuất video.',
    'Cue or voice settings changed; synthesize again':
        'Nội dung câu hoặc thiết lập giọng đã thay đổi. Hãy tạo lại giọng trước khi xuất.',
    'Reference audio changed; synthesize again':
        'Âm thanh mẫu đã thay đổi. Hãy tạo lại giọng trước khi xuất.',
    'Synthesis is missing, changed or exceeds source duration':
        'Âm thanh tạo giọng bị thiếu, đã thay đổi hoặc vượt thời lượng video gốc. Hãy kiểm tra lời Việt và tạo lại giọng.',
    'Cue timing changed; synthesize placements again':
        'Thời gian câu phụ đề đã thay đổi. Hãy tạo lại giọng để sắp xếp lại thời gian.',
    'Dub requires separated background.wav':
        'Chưa có nhạc nền đã tách (background.wav). Hãy phân tích lại video trước khi lồng tiếng.',
    'Part bounds exceed source duration':
        'Mốc chia phần vượt thời lượng video gốc. Hãy chọn lại thời gian bắt đầu và kết thúc.',
    'Part boundary cuts a spoken word; move boundary into silence':
        'Mốc chia phần cắt ngang lời nói. Hãy chuyển mốc vào khoảng lặng.',
    'Reference needs word timestamps to select a clean end':
        'Mẫu giọng thiếu mốc thời gian từng từ. Hãy phân tích lại lời gốc hoặc chọn mẫu giọng khác.',
    'Reference is silent or too quiet':
        'Mẫu giọng im lặng hoặc quá nhỏ. Hãy chọn đoạn có lời nói rõ ràng.',
    'Incomplete OCR frame':
        'Khung hình nhận dạng chữ không đầy đủ. Hãy kiểm tra video nguồn và phân tích lại.',
    'OCR decoder failed':
        'Không giải mã được video để nhận dạng chữ. Hãy kiểm tra video nguồn và nhật ký ocr.log rồi thử lại.',
}


def translate_message(message: str | None) -> str | None:
    """Translate a known display message, preserving None and unknown details."""
    if message is None:
        return None
    if message in _MESSAGES:
        return _MESSAGES[message]
    match = re.fullmatch(r'(.+): configured Python environment is unavailable', message)
    if match:
        return f'{match[1]}: không tìm thấy môi trường Python đã cấu hình. Hãy kiểm tra đường dẫn runtime đã cài rồi thử lại.'
    match = re.fullmatch(r'(.+) unavailable or failed \(exit (-?\d+)\); see (.+) \(no model downloads attempted\)', message)
    if match:
        return f'Bước {match[1]} không khả dụng hoặc thất bại (mã thoát {match[2]}). Hãy kiểm tra {match[3]} và runtime/model đã cài rồi thử lại; hệ thống không tự tải model.'
    match = re.fullmatch(r'Speech ends at (.+)s past video duration (.+)s; shorten text or choose another take', message)
    if match:
        return f'Lời nói kết thúc ở {match[1]} giây, vượt thời lượng video {match[2]} giây. Hãy rút ngắn lời Việt hoặc chọn bản thu khác.'
    for prefix in ('Timing needs review; shorten or move affected cues: ', 'Timing needs review: '):
        if message.startswith(prefix):
            return 'Cần duyệt thời gian. Hãy rút ngắn lời hoặc dời các câu bị ảnh hưởng: ' + '; '.join(translate_message(part) for part in message[len(prefix):].split('; '))
    match = re.fullmatch(r'Cue (\d+): delay (.+)s, overrun (.+)s', message)
    if match:
        return f'Câu {match[1]}: trễ {match[2]} giây, vượt khung {match[3]} giây. Hãy rút ngắn lời hoặc điều chỉnh thời gian câu.'
    match = re.fullmatch(r'Installed HTDemucs checkpoint missing: (.+)', message)
    if match:
        return f'Thiếu checkpoint HTDemucs đã cài: {match[1]}. Hãy kiểm tra hoặc khôi phục tệp model cục bộ.'
    match = re.fullmatch(r'No clean >=6s single-speaker reference for (.+); edit speaker labels/reference', message)
    if match:
        return f'Không tìm thấy mẫu giọng sạch dài ít nhất 6 giây cho {match[1]}. Hãy sửa nhãn người nói hoặc chọn lại mẫu giọng.'
    return message
