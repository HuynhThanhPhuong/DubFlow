"""Dot12: automatic audit of the source cues (pure function, no I/O).

audit_cues(cues, duration) -> findings {code, severity, cue_ids, start, end, message_vi}. It reports what is wrong or
suspicious in the Chinese source lines a job holds, so the same kind of error seen in test2 ('KEIN', a sentence read twice,
a 0.2 s fragment) can be found in any other video. severity 'error' = a source-building bug or an unusable cue; 'warn' =
needs a human look (the audit cannot know which side is right).

Codes: NO_CJK, NEAR_DUPLICATE, FRAGMENT, UNCONFIRMED_SHORT, SAME_REGION_OVERLAP, OCR_ASR_MISMATCH, TOO_SHORT_FOR_TEXT, BAD_TIME.
"""
from __future__ import annotations

from difflib import SequenceMatcher

try:
    from .subtitle_cues import chinese
    from .subtitle_lines import is_chinese_text, line_key
except ImportError:  # top-level import (engine scripts)
    from subtitle_cues import chinese
    from subtitle_lines import is_chinese_text, line_key

SIMILARITY = .8          # NEAR_DUPLICATE: ratio of the two readings
DUPLICATE_GAP = 1.0      # NEAR_DUPLICATE: seconds between the two cues
FRAGMENT_SECONDS = .3
FRAGMENT_CHARS = 2
UNCONFIRMED_SECONDS = .65  # UNCONFIRMED_SHORT: a 1-2 character reading this short that only the picture shows
OVERLAP_TOLERANCE = .05  # SAME_REGION_OVERLAP: seconds of overlap that still count as touching
MISMATCH_BELOW = .4      # OCR_ASR_MISMATCH: source_agreement under this (the pipeline's own flag starts at .6)
MAX_CHARS_PER_SECOND = 12.0
NON_SPEECH_KINDS = ('lyrics', 'music', 'note', 'sfx')  # a music note or sound label has no Han and is not junk


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value


def _finding(code, cues, message, severity='error'):
    return dict(code=code, severity=severity, cue_ids=[c.get('id') for c in cues],
                start=min(float(c['start']) for c in cues), end=max(float(c['end']) for c in cues), message_vi=message)


def _supp(c):
    return c.get('kind') == 'supplementary' or c.get('orientation') == 'v'


def _group(c):
    """Cues that can be neighbours on screen: the same region; supplementary and ASR-only cues each have their own group."""
    return (c.get('region'), _supp(c))


def _label(c):
    return f"{c.get('id')} '{c.get('original', '')}' ({float(c['start']):.1f}-{float(c['end']):.1f} s)"


def _similar(a, b):
    """The two line keys are one sentence read twice: nearly equal, or the shorter (3+ characters) inside the longer."""
    if not a or not b:
        return False
    if a == b:
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) >= 3 and short in long:
        return True
    return len(short) >= 3 and SequenceMatcher(None, a, b, autojunk=False).ratio() >= SIMILARITY


def _same_place(a, b):
    """Overlap in time only matters when both cues sit in the same cluster / the same horizontal place of a region."""
    if _group(a) != _group(b):
        return False
    if _supp(a) or a.get('cluster') == b.get('cluster'):
        return True
    ba, bb = a.get('box'), b.get('box')
    if not ba or not bb:
        return a.get('cluster') is None and b.get('cluster') is None
    width = min(ba[2] - ba[0], bb[2] - bb[0])
    return width > 0 and min(ba[2], bb[2]) - max(ba[0], bb[0]) >= .5 * width


def audit_cues(cues, duration):
    """Findings for a list of source cues (dicts with start/end/original and, when known, source/region/cluster/kind/box/
    source_agreement/asr_text). `duration` is the video length in seconds."""
    rows = [c for c in cues if isinstance(c, dict) and _number(c.get('start')) and _number(c.get('end'))]
    rows.sort(key=lambda c: (float(c['start']), float(c['end'])))
    findings = []
    chinese_source = is_chinese_text([str(c.get('original') or '') for c in rows])

    for c in rows:
        s, e = float(c['start']), float(c['end'])
        text = str(c.get('original') or '')
        han = chinese(text)
        if e <= s + 1e-9 or s < -1e-6 or (duration and e > float(duration) + .5):
            findings.append(_finding('BAD_TIME', [c], f"Thời gian câu không hợp lệ hoặc vượt video: {_label(c)}."))
        if chinese_source and not han and line_key(text) and c.get('kind') not in NON_SPEECH_KINDS:
            findings.append(_finding('NO_CJK', [c], f"Lời gốc không có chữ Hán nào (nhiều khả năng là rác OCR): {_label(c)}."))
        key = line_key(text)
        if key and e - s <= FRAGMENT_SECONDS + 1e-9 and len(key) <= FRAGMENT_CHARS:
            findings.append(_finding('FRAGMENT', [c], f"Mảnh quá ngắn ({e - s:.2f} s, {len(key)} ký tự), có thể là chữ cụt: {_label(c)}.",
                                     'warn' if c.get('source_uncertain') else 'error'))
        elif key and len(key) <= FRAGMENT_CHARS and e - s <= UNCONFIRMED_SECONDS + 1e-9 and c.get('source') == 'ocr' and han and not _supp(c)                 and not (c.get('kind') in NON_SPEECH_KINDS):
            findings.append(_finding('UNCONFIRMED_SHORT', [c], f"Câu rất ngắn ({len(key)} ký tự, {e - s:.2f} s) chỉ thấy trên hình, không có giọng nói xác nhận; có thể là hoa văn trên hình bị đọc nhầm: {_label(c)}.", 'warn'))
        elif len(han) >= 3 and e > s and len(han) / (e - s) > MAX_CHARS_PER_SECOND:
            findings.append(_finding('TOO_SHORT_FOR_TEXT', [c], f"Câu quá ngắn so với số chữ ({len(han) / (e - s):.0f} chữ/giây, đọc không kịp): {_label(c)}.", 'warn'))
        agreement = c.get('source_agreement')
        if agreement is not None and len(chinese(c.get('asr_text', '') or '')) >= 2 and float(agreement) < MISMATCH_BELOW:
            findings.append(_finding('OCR_ASR_MISMATCH', [c], f"Chữ trên hình và giọng nói lệch nhiều (độ khớp {float(agreement):.0%}): {_label(c)}; ASR nghe '{c.get('asr_text')}'.", 'warn'))

    # neighbours of one group: the same sentence twice, or two readings of one place on screen at once
    groups = {}
    for c in rows:
        groups.setdefault(_group(c), []).append(c)
    seen = set()
    for members in groups.values():
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                gap = float(b['start']) - float(a['end'])
                if gap > DUPLICATE_GAP:
                    break  # sorted by start: every later cue is further away still
                seen.add((id(a), id(b)))
                overlap = min(float(a['end']), float(b['end'])) - max(float(a['start']), float(b['start']))
                if overlap > OVERLAP_TOLERANCE and _same_place(a, b):
                    findings.append(_finding('SAME_REGION_OVERLAP', [a, b], f"Hai câu cùng vùng chồng thời gian {overlap:.2f} s: {_label(a)} và {_label(b)}."))
                if gap <= DUPLICATE_GAP + 1e-9 and (_supp(a) or _supp(b) or _same_place(a, b) or a.get('region') is None) \
                        and _similar(line_key(a.get('original', '')), line_key(b.get('original', ''))):
                    findings.append(_finding('NEAR_DUPLICATE', [a, b], f"Hai câu liền nhau gần giống nhau (cách {max(gap, 0):.1f} s), có thể là một câu bị đọc hai lần: {_label(a)} và {_label(b)}."))
    # the same dialogue line read in two regions at the same time (overlapping bands both see one displayed line)
    dialogue_rows = [c for c in rows if c.get('source') != 'asr' and not _supp(c)]
    for i, a in enumerate(dialogue_rows):
        for b in dialogue_rows[i + 1:]:
            if float(b['start']) >= float(a['end']):
                continue
            if a.get('region') == b.get('region') or (id(a), id(b)) in seen                     or min(float(a['end']), float(b['end'])) - float(b['start']) < .1:
                continue
            ka, kb = line_key(a.get('original', '')), line_key(b.get('original', ''))
            if min(len(ka), len(kb)) >= 4 and _similar(ka, kb):
                seen.add((id(a), id(b)))
                findings.append(_finding('NEAR_DUPLICATE', [a, b], f"Cùng một câu bị đọc ở hai vùng ({a.get('region')} và {b.get('region')}): {_label(a)} và {_label(b)}."))
    # an ASR-only cue repeating the dialogue line that is displayed right next to it
    dialogue = [c for c in rows if c.get('source') != 'asr' and not _supp(c)]
    for a in (c for c in rows if c.get('source') == 'asr'):
        for b in dialogue:
            if (id(a), id(b)) in seen or (id(b), id(a)) in seen:
                continue
            gap = max(float(a['start']) - float(b['end']), float(b['start']) - float(a['end']))
            if gap <= DUPLICATE_GAP + 1e-9 and _similar(line_key(a.get('original', '')), line_key(b.get('original', ''))):
                findings.append(_finding('NEAR_DUPLICATE', [a, b], f"Câu từ giọng nói lặp lại câu trên hình ngay cạnh: {_label(a)} và {_label(b)}."))
    findings.sort(key=lambda f: (f['start'], f['end'], f['code']))
    return findings
