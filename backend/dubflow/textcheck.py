"""Kiểm tra chữ nguồn có cần dịch không (không import model)."""
import re

_CJK = re.compile('[㐀-鿿豈-﫿]')


def needs_translation(text) -> bool:
    """True chỉ khi có ít nhất một chữ Hán; nhiễu OCR như 'V', '50' thì không."""
    return bool(_CJK.search(str(text or '')))
