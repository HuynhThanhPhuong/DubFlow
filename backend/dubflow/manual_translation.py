"""Chế độ dịch thủ công: lệnh mẫu cho AI chat và nhập SRT Việt khớp theo số thứ tự."""
from __future__ import annotations

import re

TIME = re.compile(r'\d{1,2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[,.]\d{3}')

_MODE_RULES = {
    'vietsub': 'Đây là phụ đề (vietsub). Mỗi khối chỉ tối đa {cps:g} ký tự trên mỗi giây hiển thị, tính theo thời lượng '
               'của chính khối đó (số ký tự tối đa = thời lượng giây x {cps:g}). Văn phong ngắn gọn, dễ đọc lướt, bỏ từ đệm không cần thiết.',
    'tm': 'Đây là thuyết minh: một giọng đọc duy nhất đọc lại lời thoại đã dịch. Vẫn dịch từng câu như lời nhân vật nói '
          '(giữ ngôi và xưng hô của nhân vật), KHÔNG chuyển thành lời kể ngôi thứ ba. Câu văn nói tự nhiên, dễ đọc thành tiếng; '
          'độ dài mỗi khối phải khớp với thời lượng của khối đó (khoảng 4,5 âm tiết mỗi giây, sai lệch trong 15%).',
    'dub': 'Đây là lồng tiếng: viết lời thoại nói được thành tiếng cho từng nhân vật, hợp tính cách và cảm xúc '
           '(khẩu ngữ, ngắt nhịp tự nhiên). Độ dài mỗi khối phải khớp với thời lượng của khối đó '
           '(khoảng 4,5 âm tiết mỗi giây, sai lệch trong 15%).',
}


def prompt_text(mode: str, cps, terminology: str = '') -> str:
    if mode not in _MODE_RULES:
        raise ValueError(f'Chế độ dịch không hợp lệ: {mode}.')
    parts = [
        'Bạn là biên dịch viên Trung - Việt chuyên nghiệp cho video. Tôi gửi kèm một file phụ đề SRT tiếng Trung. '
        'Hãy dịch sang tiếng Việt tự nhiên như người bản ngữ, sát nghĩa nhưng không dịch từng chữ, không thêm ý, không bỏ ý.',
        'YÊU CẦU ĐỊNH DẠNG:\n'
        '- Giữ nguyên số thứ tự và dòng thời gian, chỉ thay phần chữ Trung bằng tiếng Việt.\n'
        '- Mỗi khối 1-2 dòng chữ.\n'
        '- Không gộp hay tách khối; số khối trả về phải bằng số khối đã gửi.\n'
        '- Trả về đúng định dạng SRT, không bọc kết quả trong khối code, không ghi chú, không giải thích, không phiên âm pinyin, không để chữ Hán.',
        'YÊU CẦU THEO CHẾ ĐỘ:\n' + _MODE_RULES[mode].format(cps=float(cps)),
        'XƯNG HÔ: suy ra quan hệ giữa các nhân vật từ lời thoại rồi chọn đại từ tự nhiên, và dùng nhất quán xuyên suốt; '
        'tên người Trung Quốc dùng âm Hán-Việt trừ khi bảng thuật ngữ nói khác.',
    ]
    if (terminology or '').strip():
        parts.append('THUẬT NGỮ BẮT BUỘC TUÂN THEO:\n' + terminology.strip())
    return '\n\n'.join(parts) + '\n'


def parse_indexed_srt(text: str) -> list[dict]:
    """Tách các khối SRT, giữ số thứ tự (None nếu thiếu). Chịu BOM, CRLF, CR và chữ nhiều dòng."""
    text = text.lstrip('\ufeff').replace('\r\n', '\n').replace('\r', '\n')
    text = '\n'.join(ln for ln in text.split('\n') if not ln.strip().startswith('```')).strip()
    blocks = []
    for raw in re.split(r'\n\s*\n', text):
        lines = [ln.strip() for ln in raw.strip().split('\n')]
        stamp = next((i for i, ln in enumerate(lines) if TIME.search(ln)), None)
        if stamp is None:
            # Dòng trống nằm giữa chữ: nối đoạn này vào khối trước.
            body = '\n'.join(ln for ln in lines if ln)
            if not body:
                continue
            if not blocks:
                raise ValueError(f'Không hiểu dòng "{lines[0][:60]}": chưa có số thứ tự và dòng thời gian trước nó.')
            blocks[-1]['text'] = (blocks[-1]['text'] + '\n' + body).strip('\n')
            continue
        number = None
        if stamp > 0:
            prev = lines[stamp - 1].lstrip('\ufeff')
            if re.fullmatch(r'[0-9]+', prev):
                number = int(prev)
            elif prev.isdigit():
                raise ValueError(f'Số thứ tự "{prev}" không hợp lệ, chỉ dùng chữ số 0-9.')
        body = '\n'.join(ln for ln in lines[stamp + 1:] if ln)
        blocks.append(dict(number=number, text=body))
    if not blocks:
        raise ValueError('Không tìm thấy câu phụ đề SRT hợp lệ.')
    return blocks


def _listing(nums) -> str:
    nums = list(nums)
    shown = ', '.join(str(n) for n in nums[:10])
    return shown + (f' (và {len(nums) - 10} số khác)' if len(nums) > 10 else '')


def match_by_index(blocks: list[dict], ids: list[str]) -> dict[str, str]:
    """Khớp khối SRT với id câu thoại theo số thứ tự 1..len(ids). Lỗi -> ValueError (tiếng Việt)."""
    total = len(ids)
    if len(blocks) != total:
        raise ValueError(f'File có {len(blocks)} câu, video có {total} câu thoại. '
                         'Hãy giữ nguyên số câu như file SRT Trung đã xuất.')
    seen: dict[int, int] = {}
    for b in blocks:
        if b['number'] is not None:
            seen[b['number']] = seen.get(b['number'], 0) + 1
    missing = [n for n in range(1, total + 1) if n not in seen]
    duplicate = sorted(n for n, k in seen.items() if k > 1)
    if missing or duplicate:
        bits = []
        if missing:
            bits.append('Thiếu số ' + _listing(missing))
        if duplicate:
            bits.append('Trùng số ' + _listing(duplicate))
        raise ValueError('Số thứ tự trong file phải đủ từ 1 đến %d, không trùng. %s.' % (total, '; '.join(bits)))
    empty = [b['number'] for b in blocks if not b['text'].strip()]
    if empty:
        raise ValueError('Có câu chưa có chữ tiếng Việt, số thứ tự: ' + _listing(sorted(empty)) + '.')
    return {ids[b['number'] - 1]: b['text'] for b in blocks}
