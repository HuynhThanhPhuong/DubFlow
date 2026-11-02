"""Kiểm tra chữ nguồn có cần dịch không (không import model)."""
import re

_CJK = re.compile('[㐀-鿿豈-﫿]')


def needs_translation(text) -> bool:
    """True chỉ khi có ít nhất một chữ Hán; nhiễu OCR như 'V', '50' thì không."""
    return bool(_CJK.search(str(text or '')))


NOISE_SECONDS = .5
NOISE_CHARS = 2


def screen_text_noise(region, regions=()):
    """True for an OCR flicker: at most two characters on screen for under half a second ('可', '可电').

    Equal text in touching regions counts as one stretch (a longer caption cut into 0.25 s slices is not noise)."""
    text = lambda r: re.sub(r'\s+', '', str(r.get('text') or ''))
    word = text(region)
    if not word or len(word) > NOISE_CHARS:
        return False
    try:
        start, end = float(region['start']), float(region['end'])
        group, grown = [region], True
        while grown:
            grown = False
            for other in regions:
                if all(other is not g for g in group) and other.get('enabled') and text(other) == word:
                    o_start, o_end = float(other['start']), float(other['end'])
                    if o_start <= end + .05 and o_end >= start - .05:
                        group.append(other)
                        start, end, grown = min(start, o_start), max(end, o_end), True
        return end - start < NOISE_SECONDS
    except (KeyError, TypeError, ValueError):
        return False
